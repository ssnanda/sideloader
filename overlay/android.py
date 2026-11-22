"""SideLoader Android: Wireless-debugging ADB pairing and APK install.

Installed beside sideloop/server.py by patch-android.py. No Python packages;
the container image provides Debian's `adb`. APKs are already signed by their
developer, so there is no account, signing or refresh step: download the APK
from a GitHub release and `adb install -r` it on the paired phone.

Persistent state lives in DATA/android/ (ADB key, saved phones, extra repos,
cached APK metadata) so container rebuilds do not require re-pairing.
"""
import hashlib
import json
import os
import re
import socket
import struct
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import zipfile

from . import config, github_sources

ADB = os.environ.get("SIDELOADER_ADB", "adb")
# Container-local server port; a host adb on 5037 shares Linux host networking.
ADB_PORT = os.environ.get("SIDELOADER_ADB_PORT", "5038")
MAX_APK = 2 * 1024 * 1024 * 1024
CATALOG_TTL = 300
_LOCK = threading.RLock()
_CATALOG = {"at": 0, "key": None, "value": None}

ADDRESS = re.compile(r"^(?:\d{1,3}(?:\.\d{1,3}){3}|\[[0-9A-Fa-f:]+\]|[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?):\d{1,5}$")
PAIR_CODE = re.compile(r"^\d{6}$")
SERIAL = re.compile(r"^[A-Za-z0-9._:\[\]-]{1,200}$")
PACKAGE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+$")
GENERIC_NAMES = {"app-release", "app-debug", "app-universal-release", "release", "app", "base"}
REPO_URL = re.compile(r"^https://github\.com/([A-Za-z0-9-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?$")


def _dir():
    path = config.DATA / "android"
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, 0o700)
    return path


def _read(name, default):
    try:
        return json.loads((_dir() / name).read_text())
    except (FileNotFoundError, ValueError):
        return default


def _write(name, value):
    path = _dir() / name
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(value, f, indent=2)
    os.replace(tmp, path)


# ---------------------------------------------------------------- adb
#
# Two ways to reach phones:
#  * External adb server (SIDELOADER_ADB_SERVER=host:port, set to the Mac's
#    127.0.0.1:5037 in deploy/mac-host.yml). Docker Desktop cannot see Mac USB
#    devices, but the Mac's own adb server can: USB *and* Wi-Fi phones.
#  * Container-local server on ADB_PORT: Wi-Fi phones, plus USB on Linux
#    hosts that pass /dev/bus/usb into the container.
# The external server is used whenever it answers; otherwise the local one.

def _env(port):
    home = _dir() / "home"
    home.mkdir(exist_ok=True)
    # adb keeps its RSA identity in $HOME/.android; the phone trusts that key.
    return {**os.environ, "HOME": str(home), "ANDROID_USER_HOME": str(home / ".android"),
            "ANDROID_ADB_SERVER_PORT": str(port)}


def _external():
    value = os.environ.get("SIDELOADER_ADB_SERVER", "").strip()
    if not value:
        return None
    host, _, port = value.rpartition(":")
    if not host or not port.isdigit():
        return None
    return host.strip("[]"), int(port)


def _reachable(host, port):
    try:
        with socket.create_connection((host, port), timeout=0.6):
            return True
    except OSError:
        return False


def server():
    ext = _external()
    if ext and _reachable(*ext):
        return {"mode": "external", "host": ext[0], "port": ext[1], "usb": True}
    return {"mode": "local", "host": "127.0.0.1", "port": int(ADB_PORT),
            "usb": False, "external": f"{ext[0]}:{ext[1]}" if ext else ""}


def _run(argv, port, timeout):
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                              stdin=subprocess.DEVNULL, env=_env(port))
    except FileNotFoundError as exc:
        raise RuntimeError("adb is not installed in this image; rebuild with ./bin/build-docker.sh") from exc


def _start_local(port):
    # The first adb command forks the server daemon, which inherits and holds
    # the client's stdout/stderr open; capture_output then waits forever
    # ("adb devices timed out"). Start it with no pipes attached instead.
    try:
        subprocess.run([ADB, "start-server"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=30, env=_env(port), start_new_session=True)
    except FileNotFoundError as exc:
        raise RuntimeError("adb is not installed in this image; rebuild with ./bin/build-docker.sh") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("adb server did not start") from exc


def adb(*args, timeout=30, srv=None):
    srv = srv or server()
    if srv["mode"] == "local" and not _reachable("127.0.0.1", srv["port"]):
        _start_local(srv["port"])
    argv = [ADB, "-H", srv["host"], "-P", str(srv["port"]), *args]
    try:
        r = _run(argv, srv["port"], timeout)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"adb {args[0]} timed out") from exc
    return r.returncode, (r.stdout + r.stderr).strip()


def _address(value, label):
    value = str(value or "").strip()
    if not ADDRESS.fullmatch(value) or not 0 < int(value.rsplit(":", 1)[1]) < 65536:
        raise ValueError(f"enter the {label} as IP:port, as shown under Wireless debugging")
    return value


def _serial(value):
    value = str(value or "").strip()
    if not SERIAL.fullmatch(value) or value.startswith("-"):
        raise ValueError("select an Android phone")
    return value


def parse_devices(output):
    devices = []
    for line in output.splitlines():
        line = line.strip()
        if not line or line.startswith(("List of devices", "*")):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        info = dict(p.split(":", 1) for p in parts[2:] if ":" in p)
        wifi = ADDRESS.fullmatch(parts[0]) is not None or "._adb-tls-connect." in parts[0]
        devices.append({"serial": parts[0], "state": parts[1],
                        "model": info.get("model", "").replace("_", " "),
                        "product": info.get("product", ""),
                        "transport": "usb" if "usb" in info or not wifi else "wifi"})
    return devices


def parse_mdns(output):
    """`adb mdns services` rows for phones advertising Wireless debugging."""
    found = []
    for line in output.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[1].startswith("_adb-tls-connect.") and ADDRESS.fullmatch(parts[2]):
            found.append({"name": parts[0], "address": parts[2]})
    return found


def parse_packages(output):
    """`pm list packages -3 -i --show-versioncode` -> {package: {...}}."""
    installed = {}
    for line in output.splitlines():
        m = re.match(r"^package:(\S+)(.*)$", line.strip())
        if not m:
            continue
        rest = m.group(2)
        code = re.search(r"versionCode:(\d+)", rest)
        installer = re.search(r"installer=(\S+)", rest)
        installer = installer.group(1) if installer else None
        installed[m.group(1)] = {"versionCode": int(code.group(1)) if code else None,
                                 "installer": None if installer in (None, "null") else installer}
    return installed


# Apps put there by a store are not "sideloaded"; anything else (adb, a
# file manager or browser download) is listed by default, as on the Apple side.
STORES = {"com.android.vending", "com.amazon.venezia", "com.sec.android.app.samsungapps",
          "com.huawei.appmarket", "com.xiaomi.market", "com.heytap.market", "com.oppo.market",
          "com.bbk.appstore", "com.google.android.feedback"}


def _saved():
    saved = _read("devices.json", [])
    return [d for d in saved if isinstance(d, dict) and ADDRESS.fullmatch(str(d.get("address", "")))]


def _live(srv):
    code, out = adb("devices", "-l", timeout=15, srv=srv)
    if code != 0:
        raise RuntimeError(out or "adb is not responding")
    return {d["serial"]: d for d in parse_devices(out)}


def state(data=None):
    with _LOCK:
        srv = server()
        saved = _saved()
        live = _live(srv)
        # Reconnect remembered Wi-Fi phones quietly; the connect port survives
        # until Wireless debugging is toggled or the phone reboots.
        missing = [d for d in saved if d["address"] not in live]
        for d in missing:
            adb("connect", d["address"], timeout=6, srv=srv)
        if missing:
            live = _live(srv)
        _, mdns = adb("mdns", "services", timeout=6, srv=srv)
    devices = []
    for d in saved:
        row = live.pop(d["address"], None)
        devices.append({"address": d["address"], "name": d.get("name") or (row or {}).get("model") or d["address"],
                        "state": row["state"] if row else "offline", "transport": "wifi", "saved": True})
    for serial, row in live.items():
        devices.append({"address": serial, "name": row["model"] or serial, "state": row["state"],
                        "transport": row["transport"], "saved": False})
    known = {d["address"] for d in devices}
    view = {k: srv[k] for k in ("mode", "usb")}
    if srv["mode"] == "local" and srv.get("external"):
        view["hint"] = (f"USB phones need the computer's adb server at {srv['external']}; "
                        "it is not running. On the Mac run: adb start-server")
    return {"server": view, "devices": devices,
            "discovered": [m for m in parse_mdns(mdns) if m["address"] not in known]}


def pair(data):
    address = _address(data.get("address"), "pairing address")
    code = str(data.get("code", "")).strip()
    if not PAIR_CODE.fullmatch(code):
        raise ValueError("enter the 6-digit Wi-Fi pairing code")
    with _LOCK:
        rc, out = adb("pair", address, code, timeout=40)
    if rc != 0 or "Successfully paired" not in out:
        raise RuntimeError("Pairing failed: " + (out.replace(code, "******")[-300:] or "no response"))
    return {"ok": True, "message": "Paired. Now connect using the IP address & port on the Wireless debugging screen."}


def connect(data):
    address = _address(data.get("address"), "IP address & port")
    with _LOCK:
        srv = server()
        rc, out = adb("connect", address, timeout=20, srv=srv)
        if rc != 0 or not re.search(r"\b(connected|already connected) to\b", out):
            raise RuntimeError("Connect failed: " + (out[-300:] or "no response") +
                               ". Pair first, and use the port on the main Wireless debugging screen.")
        time.sleep(0.5)
        row = _live(srv).get(address)
        if row and row["state"] == "unauthorized":
            raise RuntimeError("Phone is connected but not authorized; pair it first")
        model = (row or {}).get("model") or ""
        if not model:
            rc, out = adb("-s", address, "shell", "getprop", "ro.product.model", timeout=10, srv=srv)
            model = (out.splitlines() or [""])[0].strip() if rc == 0 else ""
        model = model or address
        saved = [d for d in _saved() if d["address"] != address]
        # A phone gets a new connect port after Wireless debugging restarts;
        # keep one entry per phone name instead of piling up stale ports.
        saved = [d for d in saved if d.get("name") != model]
        _write("devices.json", saved + [{"address": address, "name": model}])
    return {"ok": True, "name": model}


def _wifi_ipv4(route_output, address_output=""):
    """Extract the phone's active Wi-Fi IPv4 address from Android `ip` output."""
    match = re.search(r"\bsrc\s+(\d{1,3}(?:\.\d{1,3}){3})\b", route_output)
    if not match:
        match = re.search(r"\binet\s+(\d{1,3}(?:\.\d{1,3}){3})/", address_output)
    if not match:
        return None
    parts = match.group(1).split(".")
    return match.group(1) if all(0 <= int(part) <= 255 for part in parts) else None


def enable_wifi(data):
    """Move an authorized USB phone to classic ADB-over-Wi-Fi automatically."""
    with _LOCK:
        srv = server()
        serial = _device(data, srv)
        live = _live(srv).get(serial, {})
        if live.get("transport") != "usb":
            raise ValueError("select an authorized USB-connected Android phone")
        rc, route = adb("-s", serial, "shell", "ip", "route", "get", "1.1.1.1",
                        timeout=10, srv=srv)
        _, addresses = adb("-s", serial, "shell", "ip", "-f", "inet", "addr", "show", "wlan0",
                           timeout=10, srv=srv)
        ip = _wifi_ipv4(route if rc == 0 else "", addresses)
        if not ip:
            raise RuntimeError("The phone has no active Wi-Fi address; connect it to Wi-Fi and try again")
        rc, out = adb("-s", serial, "tcpip", "5555", timeout=20, srv=srv)
        if rc != 0 or "restarting in TCP mode" not in out:
            raise RuntimeError("Could not enable ADB over Wi-Fi: " + (out[-240:] or "no response"))
        time.sleep(1)
    result = connect({"address": f"{ip}:5555"})
    return {**result, "address": f"{ip}:5555",
            "message": f"{result['name']} connected over Wi-Fi automatically."}


def disconnect(data):
    address = _address(data.get("address"), "device address")
    with _LOCK:
        adb("disconnect", address, timeout=10)
        if data.get("forget"):
            _write("devices.json", [d for d in _saved() if d["address"] != address])
    return {"ok": True}


def _device(data, srv):
    serial = _serial(data.get("device"))
    rows = _live(srv)
    if rows.get(serial, {}).get("state") != "device" and ADDRESS.fullmatch(serial):
        adb("connect", serial, timeout=10, srv=srv)
        rows = _live(srv)
    st = rows.get(serial, {}).get("state")
    if st == "unauthorized":
        raise RuntimeError("Unlock the phone and accept the 'Allow USB debugging?' prompt, then Refresh")
    if st != "device":
        raise RuntimeError("Android phone is not connected; check the cable or Wireless debugging")
    return serial


def installed(data):
    """Scan third-party apps; versionName only for sideloaded ones (cheap)."""
    with _LOCK:
        srv = server()
        serial = _device(data, srv)
        rc, out = adb("-s", serial, "shell", "pm", "list", "packages", "-3", "-i", "--show-versioncode",
                      timeout=30, srv=srv)
        if rc != 0 or "Unknown option" in out:
            rc, out = adb("-s", serial, "shell", "pm", "list", "packages", "-3", "-i", timeout=30, srv=srv)
        if rc != 0:
            raise RuntimeError(out[-300:] or "cannot list Android apps")
        packages = parse_packages(out)
        known = {a["package"]: a["name"] for a in _imported() if a.get("package")}
        known.update({k: v.get("name", "") for k, v in _read("apk-names.json", {}).items()})
        for pkg, row in packages.items():
            row["sideloaded"] = row["installer"] not in STORES
            row["name"] = known.get(pkg) or ""
            if row["sideloaded"] and PACKAGE.fullmatch(pkg):
                _, dump = adb("-s", serial, "shell", "dumpsys", "package", pkg, timeout=15, srv=srv)
                vn = re.search(r"versionName=(\S+)", dump)
                row["versionName"] = vn.group(1) if vn else ""
                if row["versionCode"] is None:
                    vc = re.search(r"versionCode=(\d+)", dump)
                    row["versionCode"] = int(vc.group(1)) if vc else None
    return {"packages": packages}


def uninstall(data):
    package = str(data.get("package", "")).strip()
    if not PACKAGE.fullmatch(package):
        raise ValueError("invalid Android package name")
    if data.get("acknowledge") is not True:
        raise ValueError("Confirm the uninstall; the app's data on the phone is deleted")
    with _LOCK:
        srv = server()
        serial = _device(data, srv)
        rc, out = adb("-s", serial, "uninstall", package, timeout=60, srv=srv)
    if rc != 0 or "Success" not in out:
        raise RuntimeError("Uninstall failed: " + (out[-300:] or "no response"))
    return {"ok": True}


# ---------------------------------------------------------------- imported APKs

def _apk_dir():
    path = _dir() / "apks"
    path.mkdir(exist_ok=True)
    return path


def _imported():
    rows = _read("apks.json", [])
    return [r for r in rows if isinstance(r, dict) and re.fullmatch(r"[0-9a-f]{16}", str(r.get("id", "")))
            and (_apk_dir() / f"{r['id']}.apk").is_file()]


def import_apk(stream, length, filename=""):
    if not 0 < length <= MAX_APK:
        raise ValueError("empty or too large APK")
    incoming = _apk_dir() / ".upload.apk"
    digest = hashlib.sha256()
    fd = os.open(incoming, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "wb") as out:
            left = length
            while left and (chunk := stream.read(min(left, 1 << 20))):
                digest.update(chunk)
                out.write(chunk)
                left -= len(chunk)
        if left:
            raise ValueError("upload interrupted")
        info = inspect_apk(incoming)
        apk_id = digest.hexdigest()[:16]
        os.replace(incoming, _apk_dir() / f"{apk_id}.apk")
    finally:
        incoming.unlink(missing_ok=True)
    name = re.sub(r"\.apk$", "", os.path.basename(str(filename)), flags=re.I).strip()[:80]
    if not name or name.lower() in GENERIC_NAMES:
        name = info["package"].rsplit(".", 1)[-1]
    row = {"id": apk_id, "name": name, "package": info["package"], "versionName": info.get("versionName", ""),
           "versionCode": info.get("versionCode"), "size": length, "added": int(time.time())}
    with _LOCK:
        rows = [r for r in _imported() if r["id"] != apk_id]
        _write("apks.json", rows + [row])
    return {"ok": True, "apk": row}


def remove_imported(data):
    apk_id = str(data.get("id", ""))
    if not re.fullmatch(r"[0-9a-f]{16}", apk_id):
        raise ValueError("unknown imported APK")
    with _LOCK:
        (_apk_dir() / f"{apk_id}.apk").unlink(missing_ok=True)
        _write("apks.json", [r for r in _imported() if r["id"] != apk_id])
    return {"ok": True}


def imported(data=None):
    return {"apks": _imported()}


# ---------------------------------------------------------------- APK metadata

ATTR_IDS = {0x0101021B: "versionCode", 0x0101021C: "versionName"}


def _string_pool(buf, off):
    count, _, flags, strings_start = struct.unpack_from("<IIII", buf, off + 8)
    utf8 = bool(flags & 0x100)
    offsets = struct.unpack_from(f"<{count}I", buf, off + 28)
    base = off + strings_start
    out = []
    for o in offsets:
        p = base + o
        if utf8:
            n = buf[p]; p += 2 if n & 0x80 else 1              # UTF-16 length (skip)
            n = buf[p]
            if n & 0x80:
                n = ((n & 0x7F) << 8) | buf[p + 1]; p += 2
            else:
                p += 1
            out.append(buf[p:p + n].decode("utf-8", "replace"))
        else:
            n = struct.unpack_from("<H", buf, p)[0]; p += 2
            if n & 0x8000:
                n = ((n & 0x7FFF) << 16) | struct.unpack_from("<H", buf, p)[0]; p += 2
            out.append(buf[p:p + n * 2].decode("utf-16-le", "replace"))
    return out


def parse_manifest(buf):
    """Return package/versionCode/versionName from binary AndroidManifest.xml."""
    if len(buf) < 8 or struct.unpack_from("<H", buf, 0)[0] != 0x0003:
        raise ValueError("not a binary Android manifest")
    strings, resmap, off = [], [], struct.unpack_from("<H", buf, 2)[0]
    while off + 8 <= len(buf):
        ctype, hsize, csize = struct.unpack_from("<HHI", buf, off)
        if csize < 8:
            break
        if ctype == 0x0001:
            strings = _string_pool(buf, off)
        elif ctype == 0x0180:
            resmap = list(struct.unpack_from(f"<{(csize - hsize) // 4}I", buf, off + hsize))
        elif ctype == 0x0102:
            name_idx = struct.unpack_from("<I", buf, off + 20)[0]
            if strings[name_idx] == "manifest":
                attr_start, attr_size, attr_count = struct.unpack_from("<HHH", buf, off + 24)
                result = {}
                for i in range(attr_count):
                    a = off + 16 + attr_start + i * attr_size
                    _, nidx, raw, _, _, dtype, value = struct.unpack_from("<IIIHBBI", buf, a)
                    name = ATTR_IDS.get(resmap[nidx]) if nidx < len(resmap) else None
                    name = name or (strings[nidx] if nidx < len(strings) else "")
                    text = strings[raw] if raw != 0xFFFFFFFF and raw < len(strings) else None
                    if dtype == 0x03 and value < len(strings):
                        text = strings[value]
                    if name == "package":
                        result["package"] = text
                    elif name == "versionCode":
                        result["versionCode"] = value if dtype in (0x10, 0x11) else int(text or 0)
                    elif name == "versionName":
                        result["versionName"] = text or ""
                if not PACKAGE.fullmatch(result.get("package") or ""):
                    raise ValueError("APK manifest has no valid package name")
                return result
        off += csize
    raise ValueError("APK manifest has no <manifest> element")


def inspect_apk(path):
    try:
        with zipfile.ZipFile(path) as z:
            return parse_manifest(z.read("AndroidManifest.xml"))
    except (zipfile.BadZipFile, KeyError, OSError) as exc:
        raise ValueError("not an Android APK (missing AndroidManifest.xml)") from exc
    except (struct.error, IndexError, UnicodeError) as exc:
        raise ValueError("unreadable APK manifest") from exc


# ---------------------------------------------------------------- catalog

def _repo_of(url):
    if github_sources.is_ref(url):
        owner, repo, _ = github_sources.split_ref(url)
        return owner, repo
    p = urllib.parse.urlsplit(url)
    parts = [x for x in p.path.split("/") if x]
    if p.hostname in ("raw.githubusercontent.com", "github.com") and len(parts) >= 2:
        if github_sources.OWNER.fullmatch(parts[0]) and github_sources.REPO.fullmatch(parts[1]):
            return parts[0], parts[1]
    return None


def repos(source_urls):
    found = {}
    for url in list(source_urls) + _read("repos.json", []):
        r = _repo_of(str(url))
        if r:
            found.setdefault((r[0].lower(), r[1].lower()), r)
    return sorted(found.values(), key=lambda r: (r[1].lower(), r[0].lower()))


def add_repo(data):
    url = str(data.get("url", "")).strip()
    m = REPO_URL.fullmatch(url)
    if not m:
        raise ValueError("enter a GitHub repository URL, such as https://github.com/owner/repo")
    with _LOCK:
        extra = [u for u in _read("repos.json", []) if isinstance(u, str)]
        key = (m.group(1).lower(), m.group(2).lower())
        if key not in {tuple(x.lower() for x in (_repo_of(u) or ("", ""))) for u in extra}:
            if len(extra) >= 100:
                raise ValueError("maximum 100 extra Android repositories")
            _write("repos.json", extra + [f"https://github.com/{m.group(1)}/{m.group(2)}"])
        _CATALOG["at"] = 0
    return {"ok": True}


def remove_repo(data):
    owner, repo = str(data.get("owner", "")).lower(), str(data.get("repo", "")).lower()
    with _LOCK:
        keep = []
        for u in _read("repos.json", []):
            r = _repo_of(str(u)) or ("", "")
            if (r[0].lower(), r[1].lower()) != (owner, repo):
                keep.append(u)
        _write("repos.json", keep)
        _CATALOG["at"] = 0
    return {"ok": True}


def _repo_apks(owner, repo, token):
    url = f"{github_sources.API}/repos/{owner}/{repo}/releases?per_page=10"
    try:
        releases = github_sources.read_json(url, token)
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403) and token:
            releases = github_sources.read_json(url, "")
        elif exc.code == 404:
            return [], ""
        else:
            return [], f"{repo}: GitHub releases unavailable (HTTP {exc.code})"
    meta = _read("apk-meta.json", {})
    apps = []
    # Newest release with any .apk wins; one row per APK file name.
    for rel in releases if isinstance(releases, list) else []:
        if rel.get("draft"):
            continue
        assets = [a for a in rel.get("assets", []) if str(a.get("name", "")).lower().endswith(".apk")]
        if not assets:
            continue
        for a in assets:
            aid = f"{a['id']}:{a.get('updated_at', '')}"
            m = meta.get(aid, {})
            apps.append({"id": str(a["id"]), "asset_key": aid, "owner": owner, "repo": repo,
                         "file": a["name"], "name": a["name"][:-4], "size": a.get("size", 0),
                         "tag": rel.get("tag_name", ""), "release": rel.get("name") or rel.get("tag_name", ""),
                         "published": rel.get("published_at") or "", "url": a.get("browser_download_url", ""),
                         "package": m.get("package", ""), "versionName": m.get("versionName", ""),
                         "versionCode": m.get("versionCode")})
        break
    # Gradle's default file names say nothing; show the repository instead.
    for app in apps:
        if app["name"].lower() in GENERIC_NAMES:
            app["name"] = repo
        app["origin"] = "release"
        app["source_name"] = f"{owner}/{repo} releases"
    return apps, ""


def _source_json(url):
    from .sources import _open, _read_limited, MAX_SOURCE
    if github_sources.is_ref(url):
        obj, final = github_sources.source_contents(url, MAX_SOURCE)
        return obj, final
    with _open(url) as response:
        return json.loads(_read_limited(response, MAX_SOURCE)), response.geturl()


def source_entries(obj, base_url):
    """Android entries in an AltStore source: a top-level "android" object or
    list, and/or an "android" object inside an iOS app entry. Fields:
    packageName, name, version, buildVersion (versionCode), downloadURL."""
    if not isinstance(obj, dict):
        return []
    found = []
    top = obj.get("android")
    found.extend(top if isinstance(top, list) else [top] if isinstance(top, dict) else [])
    for app in obj.get("apps") or []:
        if isinstance(app, dict) and isinstance(app.get("android"), dict):
            found.append({"name": app.get("name"), **app["android"]})
    rows = []
    for e in found:
        if not isinstance(e, dict) or str(e.get("type", "apk")).lower() != "apk":
            continue
        url = e.get("downloadURL")
        if not isinstance(url, str) or not url.strip():
            continue
        url = urllib.parse.urljoin(base_url, url.strip())
        if urllib.parse.urlsplit(url).scheme != "https":
            continue
        package = str(e.get("packageName") or "")
        code = str(e.get("buildVersion") or e.get("versionCode") or "")
        rows.append({"id": hashlib.sha256(url.encode()).hexdigest()[:16], "asset_key": "url:" + url,
                     "url": url, "name": str(e.get("name") or package or "Android app"),
                     "package": package if PACKAGE.fullmatch(package) else "",
                     "versionName": str(e.get("version") or ""),
                     "versionCode": int(code) if code.isdigit() else None,
                     "size": e.get("size") if isinstance(e.get("size"), int) else 0,
                     "origin": "source", "source_name": str(obj.get("name") or "Source")})
    return rows


def catalog(source_urls, force=False):
    token = github_sources.load_token()
    targets = repos(source_urls)
    key = tuple(targets)
    with _LOCK:
        if not force and _CATALOG["key"] == key and time.time() - _CATALOG["at"] < CATALOG_TTL:
            return _CATALOG["value"]
    apps, warnings = [], []
    # 1) Android entries declared in saved AltStore sources (same JSON file).
    for url in source_urls:
        try:
            obj, final = _source_json(url)
            apps.extend(source_entries(obj, final))
        except (OSError, ValueError, urllib.error.URLError) as exc:
            warnings.append(f"{url.rsplit('/', 2)[-2] if '/' in url else url}: source unreadable ({type(exc).__name__})")
    # 2) .apk assets of the newest GitHub release of each source repository.
    for owner, repo in targets:
        try:
            rows, warning = _repo_apks(owner, repo, token)
        except (OSError, ValueError, urllib.error.URLError) as exc:
            rows, warning = [], f"{repo}: {type(exc).__name__}"
        apps.extend(rows)
        if warning:
            warnings.append(warning)
    # A source entry usually points at a release asset too; keep one row per
    # download URL, preferring the source entry (it declares package/version).
    seen, unique = set(), []
    for app in apps:
        if app["url"] and app["url"] not in seen:
            seen.add(app["url"])
            unique.append(app)
    apps = unique
    extra = {(_repo_of(u) or ("", ""))[:2] for u in _read("repos.json", [])}
    value = {"apps": apps, "warnings": warnings,
             "repos": [{"owner": o, "repo": r, "extra": (o, r) in extra} for o, r in targets]}
    with _LOCK:
        _CATALOG.update(at=time.time(), key=key, value=value)
    return value


def _adb_install(address, path, srv):
    rc, out = adb("-s", address, "install", "-r", str(path), timeout=900, srv=srv)
    if rc != 0 or "Success" not in out:
        reason = re.search(r"INSTALL_[A-Z_]+[^\n]*", out)
        hint = ""
        if reason and "UPDATE_INCOMPATIBLE" in reason.group(0):
            hint = " The installed copy is signed with a different key; uninstall it on the phone first."
        if reason and "VERSION_DOWNGRADE" in reason.group(0):
            hint = " The phone has a newer version; uninstall it first to go back."
        raise RuntimeError("Install failed: " + (reason.group(0) if reason else out[-300:]) + hint)


def _remember_name(info, name):
    names = _read("apk-names.json", {})
    if name and info.get("package"):
        names[info["package"]] = {"name": name}
        _write("apk-names.json", dict(list(names.items())[-500:]))


def install(data, source_urls):
    from .sources import _open  # SSRF-checked opener with private-repo support
    if data.get("imported"):
        apk_id = str(data["imported"])
        with _LOCK:
            row = next((r for r in _imported() if r["id"] == apk_id), None)
            if not row:
                raise ValueError("imported APK not found")
            srv = server()
            address = _device(data, srv)
            _adb_install(address, _apk_dir() / f"{apk_id}.apk", srv)
            _remember_name(row, row["name"])
        return {"ok": True, "package": row["package"], "versionName": row.get("versionName", ""),
                "versionCode": row.get("versionCode")}
    asset_id = str(data.get("id", ""))
    with _LOCK:
        app = next((a for a in catalog(source_urls)["apps"] if a["id"] == asset_id), None)
        if not app:
            app = next((a for a in catalog(source_urls, force=True)["apps"] if a["id"] == asset_id), None)
        if not app:
            raise ValueError("APK not found in saved sources or GitHub releases")
        srv = server()
        address = _device(data, srv)
        incoming = _dir() / ".download.apk"
        try:
            with _open(app["url"]) as remote:
                if int(remote.headers.get("Content-Length", "0") or "0") > MAX_APK:
                    raise ValueError("APK is over the 2 GiB limit")
                fd = os.open(incoming, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                received = 0
                with os.fdopen(fd, "wb") as out:
                    while chunk := remote.read(1 << 20):
                        received += len(chunk)
                        if received > MAX_APK:
                            raise ValueError("APK is over the 2 GiB limit")
                        out.write(chunk)
            info = inspect_apk(incoming)
            if app.get("package") and info["package"] != app["package"]:
                raise ValueError(f"APK package {info['package']} differs from source listing "
                                 f"{app['package']}; refusing installation")
            meta = _read("apk-meta.json", {})
            meta[app["asset_key"]] = info
            _write("apk-meta.json", dict(list(meta.items())[-500:]))
            _CATALOG["at"] = 0
            _adb_install(address, incoming, srv)
            _remember_name(info, app["name"])
        finally:
            incoming.unlink(missing_ok=True)
    return {"ok": True, "package": info["package"], "versionName": info.get("versionName", ""),
            "versionCode": info.get("versionCode")}
