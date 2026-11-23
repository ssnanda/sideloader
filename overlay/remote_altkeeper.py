"""Optional SideLoader remote iPhone backend via AltKeeper's RemotePairing engine.

AltKeeper owns the remote-pairing plist and its separate Apple account session.
No pairing material or Apple passwords cross the SideLoader HTTP API.
This module only connects to an AltKeeper instance in the *same Pod* over loopback.
"""
import base64
import http.client
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

REMOTE_URL = "SIDELOADER_REMOTE_ALTKEEPER_URL"
REMOTE_PIN = "SIDELOADER_REMOTE_ALTKEEPER_PIN"
REMOTE_UDID = "SIDELOADER_REMOTE_UDID"
REMOTE_PHONE = "SIDELOADER_REMOTE_PHONE"
MAX_IPA_BYTES = 1024 * 1024 * 1024
POLL_SECONDS = 2
JOB_TIMEOUT = 15 * 60
TEAM_SUFFIX = re.compile(r"^[A-Z0-9]{10}$")
CODE = re.compile(r"^[0-9]{6}$")
CACHE_SECONDS = 3.0

_cache_lock = threading.Lock()
_cache_data = None
_cache_time = 0.0


def enabled():
    return bool(os.getenv(REMOTE_URL, "").strip())


def bootstrap_device():
    """Register the explicitly selected remote iPhone in SideLoader's own data."""
    if not enabled():
        return
    udid = os.getenv(REMOTE_UDID, "").strip()
    if not re.fullmatch(r"[0-9A-Fa-f-]{20,64}", udid):
        raise ValueError("SIDELOADER_REMOTE_UDID must be a real paired iPhone UDID")
    from . import store
    if store.resolve_device(udid) is None:
        store.add_device(udid, os.getenv("SIDELOADER_REMOTE_DEVICE_NAME", "Remote iPhone"))


def _endpoint():
    raw = os.getenv(REMOTE_URL, "").strip()
    parsed = urllib.parse.urlsplit(raw)
    if (parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "localhost")
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in ("", "/") or parsed.port is None):
        raise ValueError("AltKeeper URL must be a local Pod loopback HTTP address including a port")
    return parsed.hostname, parsed.port


def _request(path, payload=None, timeout=6):
    host, port = _endpoint()
    pin = os.getenv(REMOTE_PIN, "")
    if not pin:
        raise RuntimeError("Remote AltKeeper PIN secret is not configured")
    method = "POST" if payload is not None else "GET"
    url = "http://" + host + ":" + str(port) + path
    body = json.dumps(payload).encode() if payload is not None else None
    headers = {
        "Authorization": "Basic " + base64.b64encode(("sideloader:" + pin).encode()).decode(),
        "X-Requested-With": "altkeeper",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    try:
        with urllib.request.urlopen(
            urllib.request.Request(url, data=body, headers=headers, method=method),
            timeout=timeout
        ) as result:
            return json.loads(result.read(2 * 1024 * 1024))
    except urllib.error.HTTPError as error:
        try:
            details = json.loads(error.read(8192)).get("error")
        except (ValueError, OSError):
            details = None
        raise RuntimeError("Remote pairing backend rejected request: " +
                           str(details or "HTTP " + str(error.code))) from None
    except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
        raise RuntimeError("Remote pairing backend unavailable on Pod loopback") from error


def state(fresh=False):
    global _cache_time, _cache_data
    now = time.monotonic()
    with _cache_lock:
        if not fresh and _cache_data is not None and now - _cache_time < CACHE_SECONDS:
            return _cache_data
    info = _request("/api/state")
    if not isinstance(info, dict):
        raise RuntimeError("Remote pairing backend returned unexpected state")
    with _cache_lock:
        _cache_time, _cache_data = time.monotonic(), info
    return info


def _clear_cache():
    global _cache_data, _cache_time
    with _cache_lock:
        _cache_data, _cache_time = None, 0.0


def _profile_match(installed, bundle):
    if installed == bundle:
        return True
    prefix = bundle + "."
    return installed.startswith(prefix) and bool(TEAM_SUFFIX.fullmatch(installed[len(prefix):]))


def _account_ready(info):
    account = info.get("account") or {}
    return bool(account.get("present") and account.get("password_saved") and account.get("team"))


def _phone_ready(info):
    phone = info.get("phone") or {}
    checked_at = phone.get("checked_at")
    fresh = isinstance(checked_at, (float, int)) and abs(time.time() - checked_at) < 180
    return bool(info.get("pairing") and phone.get("reachable") is True and fresh)


def summary():
    if not enabled():
        return {"enabled": False}
    try:
        info = state()
    except (ValueError, RuntimeError) as error:
        return {"enabled": True, "available": False, "paired": False,
                "reachable": False, "account_ready": False,
                "message": str(error)}
    phone = info.get("phone") or {}
    return {
        "enabled": True,
        "available": True,
        "paired": bool(info.get("pairing")),
        "reachable": _phone_ready(info),
        "phone": {"address": phone.get("address"), "checked_at": phone.get("checked_at"),
                  "checking": bool(phone.get("checking")), "error": phone.get("error")},
        "account_ready": _account_ready(info),
        "verification_needed": (info.get("login") or {}).get("phase") == "needs_code",
        # These are provisioning profiles; they are NOT independently proven installed.
        "profiles": [
            {"bundle": str(a.get("bundle") or ""), "expires": a.get("expires")}
            for a in info.get("apps", []) if isinstance(a, dict) and a.get("bundle")
        ],
        "installation_verified": False,
    }


def enrich_state(result):
    if not enabled():
        return result
    remote = summary()
    result["remote_server"] = remote
    configured_device = os.getenv(REMOTE_UDID, "").strip()
    if configured_device and remote.get("reachable"):
        for device in result.get("registered", []):
            if device.get("udid", "").lower() == configured_device.lower():
                device["live"] = {
                    "reachable": True, "conn": "RemotePairing via VPN",
                    "name": device.get("name"), "udid": configured_device,
                }
    # Never mark saved IPA targets as installed based only on their profiles.
    return result


def _assert_device(udid):
    registered = os.getenv(REMOTE_UDID, "").strip()
    if not registered:
        raise ValueError("Configure SIDELOADER_REMOTE_UDID before remote operations")
    if not udid or udid.lower() != registered.lower():
        raise ValueError("Only the configured paired iPhone can use this remote connection")
    info = state(fresh=True)
    if not info.get("pairing"):
        raise RuntimeError("Remote pairing file is missing; pair once using USB")
    if not _phone_ready(info):
        raise RuntimeError("iPhone RemotePairing is not reachable; connect to Wi-Fi and NetBird")
    if not _account_ready(info):
        raise RuntimeError("Configure AltKeeper's separate Apple account and save its password")
    return info


def _match_profile(info, bundle):
    matched = [str(a.get("bundle")) for a in info.get("apps", [])
               if isinstance(a, dict) and _profile_match(str(a.get("bundle", "")), bundle)]
    if len(matched) != 1:
        raise ValueError("Remote profile for this IPA is missing or ambiguous; "
                         "use remote IPA installation instead")
    return matched[0]


def _progress(job, current, previous_lines):
    state_job = current.get("job") or {}
    lines = state_job.get("lines") or []
    if not isinstance(lines, list):
        return previous_lines
    # AltKeeper logs may contain private device/user data: do not relay raw logs.
    if len(lines) > previous_lines:
        job.say("Remote iPhone operation in progress (see AltKeeper for detailed logs)")
    login = current.get("login") or {}
    needs_code = login.get("phase") == "needs_code"
    job.remote_input = True
    with job.lock:
        job.needs_input = needs_code
        if needs_code:
            job.verification_delivery = "requested_unconfirmed"
    return len(lines)


def _follow(job, expected_kind):
    deadline = time.monotonic() + JOB_TIMEOUT
    previous_lines = 0
    seen_running = False
    while time.monotonic() < deadline and not job.cancelled:
        info = state(fresh=True)
        active = info.get("job") or {}
        if active.get("kind") not in expected_kind:
            raise RuntimeError("Remote backend switched to another job; check AltKeeper activity")
        previous_lines = _progress(job, info, previous_lines)
        if active.get("running"):
            seen_running = True
        elif seen_running or active.get("ok") is not None:
            if active.get("ok") is True:
                job.say("Remote operation completed by AltKeeper.")
                return
            raise RuntimeError("Remote operation failed; inspect the private AltKeeper activity log")
        time.sleep(POLL_SECONDS)
    if job.cancelled:
        raise RuntimeError("SideLoader stopped monitoring; AltKeeper may still be completing the operation")
    raise RuntimeError("Remote operation exceeded the monitoring timeout; check AltKeeper")


def renew_job(job, udid, bundle):
    info = _assert_device(udid)
    exact = _match_profile(info, bundle)
    job.say("Using paired iPhone and private NetBird route for remote profile renewal")
    _request("/api/renew", {"mode": "single", "bundle": exact})
    _follow(job, {"renew_one"})


def _upload_ipa(ipa_path):
    """Stream the IPA to the local AltKeeper sidecar; never load it into RAM."""
    path = Path(ipa_path)
    size = path.stat().st_size
    if not 0 < size <= MAX_IPA_BYTES:
        raise ValueError("Remote IPA must be between 1 byte and 1 GiB")
    host, port = _endpoint()
    pin = os.getenv(REMOTE_PIN, "")
    if not pin:
        raise RuntimeError("Remote AltKeeper PIN secret is missing")
    boundary = uuid.uuid4().hex
    pre = ('--' + boundary + '\r\n'
           'Content-Disposition: form-data; name="ipa"; filename="sideloader.ipa"\r\n'
           'Content-Type: application/octet-stream\r\n\r\n').encode()
    post = ('\r\n--' + boundary + '--\r\n').encode()
    authorization = base64.b64encode(("sideloader:" + pin).encode()).decode()
    connection = http.client.HTTPConnection(host, port, timeout=120)
    try:
        connection.putrequest("POST", "/api/install")
        connection.putheader("Authorization", "Basic " + authorization)
        connection.putheader("X-Requested-With", "altkeeper")
        connection.putheader("Content-Type", "multipart/form-data; boundary=" + boundary)
        connection.putheader("Content-Length", str(size + len(pre) + len(post)))
        connection.endheaders()
        connection.send(pre)
        with path.open("rb") as source:
            while True:
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                connection.send(chunk)
        connection.send(post)
        response = connection.getresponse()
        body = response.read(65536)
        if not 200 <= response.status < 300:
            raise RuntimeError("AltKeeper refused IPA installation (HTTP " +
                               str(response.status) + ")")
        parsed = json.loads(body)
        if not isinstance(parsed, dict) or parsed.get("ok") is not True:
            raise RuntimeError("AltKeeper did not acknowledge IPA installation")
    finally:
        connection.close()


def install_job(job, udid, ipa_path):
    _assert_device(udid)
    job.say("Sending saved IPA to remote-pairing service on Pod loopback")
    _upload_ipa(ipa_path)
    _follow(job, {"install"})


def latest_job(job, udid, app_id, bundle, sources):
    """Download the latest saved-source IPA, then install via RemotePairing.

    One SideLoader job owns both operations; SideLoader doesn't start a second
    Apple sign-in before the user's explicit Reinstall latest confirmation.
    """
    _assert_device(udid)
    available = sources.list().get("sources", [])
    candidates = [(source, record)
                  for source in available if not source.get("error")
                  for record in source.get("apps", [])
                  if record.get("bundleIdentifier") == bundle]
    if not candidates:
        raise ValueError("No matching saved GitHub/AltStore source is available")
    unique = {source["id"] for source, _record in candidates}
    if len(unique) != 1:
        raise ValueError("Multiple sources offer this bundle; select one in the Docker Sources list")
    source, listing = candidates[0]

    # The job already owns the SideLoader busy slot. Sources.install normally
    # asserts idle before importing; this no-op facade is scoped to this one
    # serialized import and explicitly forbids a secondary signing attempt.
    class _ImportOnly:
        def idle(self):
            return None

        def state(self):
            return {"configured": False}

        def refresh(self, _data):
            raise RuntimeError("Remote import cannot launch local AltServer signing")

    job.say("Downloading the current IPA from saved source " + str(source.get("name", "source"))[:80])
    result = sources.install(
        {"source": source["id"], "bundleIdentifier": bundle, "install_now": False},
        _ImportOnly(),
    )
    if result.get("app_id") != app_id:
        raise RuntimeError("Source imported a different IPA; remote installation refused")
    from . import config
    path = config.APPS / app_id / "app.ipa"
    _assert_device(udid)
    job.say("Latest source IPA downloaded and verified; installing through RemotePairing")
    _upload_ipa(path)
    _follow(job, {"install"})


def verification_code(data):
    code = str(data.get("code") or "").strip()
    if not CODE.fullmatch(code):
        raise ValueError("Enter the six-digit Apple verification code")
    info = state(fresh=True)
    if (info.get("login") or {}).get("phase") != "needs_code":
        raise ValueError("AltKeeper is not currently asking for a verification code")
    _request("/api/login/code", {"code": code})
    _clear_cache()
    return {"ok": True}


def diagnose():
    """A TCP connection is only an initial transport check, not Apple pairing proof."""
    status = summary()
    if not status["enabled"]:
        return status
    address = os.getenv(REMOTE_PHONE, "").strip()
    reachable = False
    message = "Set SIDELOADER_REMOTE_PHONE to the iPhone NetBird IP:49152"
    if address:
        try:
            parts = urllib.parse.urlsplit("tcp://" + address)
            host, port = parts.hostname, parts.port
            if not host or not port:
                raise ValueError("missing host/port")
            ip = ipaddress.ip_address(host)
            if not (ip.is_private or ip in ipaddress.ip_network("100.64.0.0/10")):
                raise ValueError("phone must use a private or CGNAT/VPN IP")
            with socket.create_connection((str(ip), port), timeout=3):
                reachable = True
            message = "TCP port reachable; authenticated pairing is separately checked by AltKeeper"
        except (ValueError, OSError) as error:
            message = "iPhone RemotePairing port not reachable over this VPN: " + str(error)[:150]
    status["transport"] = {"address": address, "tcp_reachable": reachable, "message": message}
    return status
