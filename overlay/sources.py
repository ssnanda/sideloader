"""Small authenticated AltStore Classic JSON source extension for Sideloop.

Installed alongside sideloop/server.py by the MiniSideload bootstrapper.
No external Python packages; the source itself and IPA remain at their URLs.
"""
import hashlib
import ipaddress
import json
import os
import re
import shutil
import socket
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import config, ipa, store, github_sources, github_scan

MAX_SOURCE = 2 * 1024 * 1024
MAX_IPA = 2 * 1024 * 1024 * 1024
USER_AGENT = "MiniSideload/0.2"
_TEAM_SUFFIX = re.compile(r"^[A-Z0-9]{10}$")
_NUMERIC_VERSION = re.compile(r"^[0-9]+(?:\.[0-9]+)*$")


def _numeric_version(value):
    text = str(value or "").strip()
    if not _NUMERIC_VERSION.fullmatch(text):
        return None
    return tuple(int(piece) for piece in text.split("."))


def version_is_newer(version, current, build="", current_build=""):
    """Conservative version comparison; unknown/pre-release versions are not auto-updates."""
    new = _numeric_version(version)
    old = _numeric_version(current)
    if new is None or old is None:
        return False
    length = max(len(new), len(old))
    left = new + (0,) * (length - len(new))
    right = old + (0,) * (length - len(old))
    if left != right:
        return left > right
    new_build, old_build = _numeric_version(build), _numeric_version(current_build)
    return new_build is not None and old_build is not None and new_build > old_build


def _bundle_matches(installed, source):
    if installed == source:
        return True
    prefix = source + "."
    return installed.startswith(prefix) and bool(_TEAM_SUFFIX.fullmatch(installed[len(prefix):]))


_LOCK = threading.RLock()


def _allowed(url):
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("https", "http") or not parts.hostname or parts.username or parts.password:
        raise ValueError("use an HTTP(S) URL without embedded credentials")
    if parts.scheme == "http" and os.getenv("ALLOW_HTTP_SOURCES") != "1":
        raise ValueError("HTTPS required (set ALLOW_HTTP_SOURCES=1 to enable plain HTTP)")
    if parts.port not in (None, 80, 443) and os.getenv("ALLOW_PRIVATE_SOURCE_URLS") != "1":
        raise ValueError("nonstandard ports require ALLOW_PRIVATE_SOURCE_URLS=1")
    if os.getenv("ALLOW_PRIVATE_SOURCE_URLS") != "1":
        # Reject local services, private/reserved ranges, and DNS resolutions
        # outside the public internet. Useful defense against SSRF in a LAN UI.
        for address in {a[4][0] for a in socket.getaddrinfo(parts.hostname, parts.port or (443 if parts.scheme == "https" else 80), type=socket.SOCK_STREAM)}:
            if not ipaddress.ip_address(address).is_global:
                raise ValueError("local/private IP URLs are disabled by default")
    return url


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _allowed(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(SafeRedirect())


def _open(url):
    _allowed(url)
    private = github_sources.private_download(url)
    if private is not None:
        return private
    return _OPENER.open(urllib.request.Request(url, headers={"User-Agent": USER_AGENT}), timeout=35)


def _read_limited(response, limit):
    size = 0
    parts = []
    while True:
        buf = response.read(min(65536, limit + 1 - size))
        if not buf:
            break
        parts.append(buf)
        size += len(buf)
        if size > limit:
            raise ValueError("remote file exceeds size limit")
    return b"".join(parts)


def _latest(app, source_url):
    # AltStore Classic sources support either top-level downloadURL/version
    # or versions[] with per-version URLs (newer formats).
    versions = app.get("versions") or []
    if versions and isinstance(versions, list):
        version = next((v for v in versions if isinstance(v, dict) and v.get("downloadURL")), {})
    else:
        version = app
    url = version.get("downloadURL") or app.get("downloadURL")
    if not isinstance(url, str) or not url.strip():
        return None
    bundle_id = app.get("bundleIdentifier")
    if not isinstance(bundle_id, str) or not bundle_id.strip():
        return None
    return {
        "name": str(app.get("name") or bundle_id),
        "bundleIdentifier": bundle_id,
        "version": str(version.get("version") or app.get("version") or ""),
        "buildVersion": str(version.get("buildVersion") or app.get("buildVersion") or ""),
        "downloadURL": urllib.parse.urljoin(source_url, url),
    }


def _catalog(url):
    if github_sources.is_ref(url):
        obj, final_url = github_sources.source_contents(url, MAX_SOURCE)
    else:
        with _open(url) as response:
            obj = json.loads(_read_limited(response, MAX_SOURCE))
            final_url = response.geturl()
    if not isinstance(obj, dict) or not isinstance(obj.get("apps"), list):
        raise ValueError("not an AltStore-compatible source JSON (missing apps array)")
    apps = [_latest(a, final_url) for a in obj["apps"] if isinstance(a, dict)]
    return {"name": str(obj.get("name") or "Unnamed source"),
            "identifier": str(obj.get("identifier") or "").strip(),
            "apps": [a for a in apps if a]}


class Sources:
    def __init__(self):
        self.path = config.DATA / "minisideload-sources.json"

    def _urls(self):
        try:
            urls = json.loads(self.path.read_text())
        except FileNotFoundError:
            return []
        if not isinstance(urls, list):
            raise ValueError("corrupted saved sources file")
        return urls

    def _save(self, urls):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(urls, f, indent=2)
        os.replace(tmp, self.path)

    def list(self):
        result = []
        with _LOCK:
            urls = self._urls()
        for url in urls:
            sid = hashlib.sha256(url.encode()).hexdigest()[:16]
            try:
                source = _catalog(url)
                result.append({"id": sid, "url": url, **source})
            except (ValueError, OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
                result.append({"id": sid, "url": url, "name": url, "apps": [], "error": str(exc)[:250]})
        return {"sources": result, "installed": [a["bundle_id"] for a in (store.app_view(a) for a in store.app_ids())], "limit": 3}

    def add(self, data):
        url = str(data.get("url", "")).strip()
        _allowed(url)
        info = _catalog(url)  # refuse broken sources
        with _LOCK:
            urls = self._urls()
            known = {github_sources.dedup_key(u) for u in urls}
            if github_sources.dedup_key(url) not in known:
                if len(urls) >= 200:
                    raise ValueError("maximum 200 saved sources")
                self._save(urls + [url])
        return {"ok": True, "name": info["name"], "apps": len(info["apps"])}

    def remove(self, data):
        sid = str(data.get("id", ""))
        with _LOCK:
            urls = self._urls()
            matching = [u for u in urls if hashlib.sha256(u.encode()).hexdigest()[:16] == sid]
            if not matching:
                raise ValueError("source not found")
            self._save([u for u in urls if u not in matching])
        return {"ok": True}

    def install(self, data, app):
        sid = str(data.get("source", ""))
        bundle_id = str(data.get("bundleIdentifier", ""))
        with _LOCK:
            app.idle()
            urls = [u for u in self._urls() if hashlib.sha256(u.encode()).hexdigest()[:16] == sid]
            if not urls:
                raise ValueError("unknown source")
            source = _catalog(urls[0])
            matches = [a for a in source["apps"] if a["bundleIdentifier"] == bundle_id]
            if not matches:
                raise ValueError("app not found in current source")
            item = matches[0]
            updating = data.get("update_existing") is True
            installed_app = None
            saved_app = None
            if updating:
                # Updates are explicitly requested for an app already confirmed
                # on one registered phone; never reinstall a removed app here.
                udid = store.resolve_device(data.get("device", ""))
                if not udid:
                    raise ValueError("select a registered iPhone before updating")
                saved_id = re.sub(r"[^A-Za-z0-9._-]", "_", bundle_id)[:120]
                if saved_id not in store.app_ids():
                    raise ValueError("import this app first; it is not a saved SideLoader IPA")
                saved_app = store.app_view(saved_id)
                if saved_app["bundle_id"] != bundle_id:
                    raise ValueError("saved IPA bundle identifier does not match the update")
                from . import device_app_inventory
                scanned = device_app_inventory.inventory(udid)
                installed_app = next(
                    (row for row in scanned if _bundle_matches(row["bundle_id"], bundle_id)),
                    None
                )
                if installed_app is None:
                    raise ValueError("app is not installed on this iPhone; update refused")
                if not version_is_newer(
                    item["version"], installed_app.get("version", ""),
                    item.get("buildVersion", ""), installed_app.get("build", "")
                ):
                    raise ValueError("source does not offer a verified newer app version")
                # The newer IPA may already be imported. Re-use it instead of
                # overwriting the same artifact and risking an unnecessary download.
                cached = saved_app.get("info") or {}
                if version_is_newer(
                    saved_app["version"], installed_app.get("version", ""),
                    cached.get("build", ""), installed_app.get("build", "")
                ) and not version_is_newer(
                    item["version"], saved_app["version"],
                    item.get("buildVersion", ""), cached.get("build", "")
                ):
                    return {"ok": True, "app": item["name"], "app_id": saved_id,
                            "version": saved_app["version"], "already_imported": True,
                            "refresh": "not started"}
            # Stored IPA files are not active apps and do not consume Apple's
            # three-app device allowance until the user explicitly installs
            # them. Keep source browsing/import independent from that limit.
            # Download into a separate file; do not overwrite the global pending
            # upload used by Sideloop's browser upload endpoint.
            incoming = config.DATA / ".minisideload-source-download.ipa"
            try:
                with _open(item["downloadURL"]) as remote:
                    length = int(remote.headers.get("Content-Length", "0") or "0")
                    if length > MAX_IPA:
                        raise ValueError("IPA is over the 2 GiB download limit")
                    fd = os.open(incoming, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                    with os.fdopen(fd, "wb") as output:
                        received = 0
                        while chunk := remote.read(1024 * 1024):
                            received += len(chunk)
                            if received > MAX_IPA:
                                raise ValueError("IPA is over the 2 GiB download limit")
                            output.write(chunk)
                inspected = ipa.inspect(incoming)
                if "error" in inspected:
                    raise ValueError(inspected["error"])
                actual = inspected.get("bundle_id") or ""
                if not actual:
                    raise ValueError("IPA has no CFBundleIdentifier (broken or empty build); "
                                     "rebuild the IPA published by this source")
                if actual != bundle_id:
                    raise ValueError(f"IPA bundle ID {actual} differs from source listing "
                                     f"{bundle_id}; refusing installation")
                if updating:
                    if not version_is_newer(
                        inspected.get("version", ""), installed_app.get("version", ""),
                        inspected.get("build", ""), installed_app.get("build", "")
                    ):
                        raise ValueError("downloaded IPA is not newer than the installed version")
                    if inspected.get("version") != item["version"]:
                        raise ValueError("downloaded IPA version differs from the source listing")
                    if item.get("buildVersion") and str(inspected.get("build", "")) != item["buildVersion"]:
                        raise ValueError("downloaded IPA build differs from the source listing")
                    prior = config.APPS / saved_id / "app.ipa"
                    if not prior.is_file():
                        raise ValueError("previously saved IPA is unavailable; update refused")
                    # Preserve the last saved IPA, in case a new signing attempt
                    # fails. A failed download/inspection leaves it untouched.
                    shutil.copy2(prior, config.APPS / saved_id / "previous.ipa")
                app.idle()
                filename = item["downloadURL"].split("?")[0].rsplit("/", 1)[-1] or "source.ipa"
                app_id = store.add_app(incoming, inspected, filename)
            finally:
                incoming.unlink(missing_ok=True)
            result = {"ok": True, "app": item["name"], "app_id": app_id, "version": item["version"], "refresh": "not started"}
            if data.get("install_now", True) and store.device_ids() and app.state()["configured"]:
                try:
                    result["refresh"] = app.refresh({"app": app_id, "force": True})
                except (ValueError, RuntimeError) as exc:
                    result["refresh"] = f"not started: {exc}"
            return result

    def github_status(self):
        return github_scan.status()

    def disconnect_github(self, data):
        return github_scan.disconnect()

    def scan_github(self, data):
        return github_scan.scan(self, data)
