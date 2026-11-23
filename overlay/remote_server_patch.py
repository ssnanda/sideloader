"""Attach the optional remote-pairing adapter to an already patched Sideloop.

Runs from patch-apps-dashboard.py without editing ./bin scripts.
Disabled unless SIDELOADER_REMOTE_ALTKEEPER_URL is configured.
"""
from pathlib import Path
import sys


def _insert_once(source, before, after, label):
    if after in source:
        return source
    if source.count(before) != 1:
        raise SystemExit("Remote adapter patch " + label + ": unexpected backend layout")
    return source.replace(before, after, 1)


def apply(checkout, overlay):
    package = Path(checkout) / "sideloop"
    module = package / "remote_altkeeper.py"
    module.write_bytes((Path(overlay) / "remote_altkeeper.py").read_bytes())
    server = package / "server.py"
    source = server.read_text()
    # A few older apps-dashboard tests create a minimal server fixture with no
    # job runner. Do not introduce an incomplete remote integration into it.
    if "    def refresh(self, data):" not in source:
        return

    if "remote_altkeeper.bootstrap_device()" not in source:
        anchor = "        self.jobs, self.health, self.muxers = jobs, health, muxers"
        if source.count(anchor) != 1:
            raise SystemExit("Remote adapter cannot identify SideLoader startup")
        source = source.replace(
            anchor, anchor + "\n        remote_altkeeper.bootstrap_device()", 1
        )

    source = _insert_once(
        source,
        "from .installed import enrich_apps",
        "from . import remote_altkeeper\nfrom .installed import enrich_apps",
        "module import"
    )

    if "return remote_altkeeper.enrich_state(result)" not in source:
        marker = '        return {\n            "mode": MUX,'
        if source.count(marker) != 1:
            raise SystemExit("Remote adapter cannot identify state() response")
        source = source.replace(marker, '        result = {\n            "mode": MUX,', 1)
        marker = "\n    def logs(self):"
        if source.count(marker) != 1:
            raise SystemExit("Remote adapter cannot identify state() end")
        source = source.replace(marker, "\n        return remote_altkeeper.enrich_state(result)\n" + marker, 1)

    insertion = '''    def remote_install(self, data):
        app = self.app(data)
        udid = self.device(data)
        if not app or not udid:
            raise ValueError("Select one app and a registered iPhone for remote installation")
        self.idle()
        path = config.APPS / app["id"] / "app.ipa"
        if not path.is_file():
            raise ValueError("The saved IPA cannot be found")
        title = "Remote reinstall: " + app["name"]
        job = self.jobs.start("refresh", title,
                              lambda j: remote_altkeeper.install_job(j, udid, path))
        return {"job": job.id}

    def remote_latest(self, data):
        app = self.app(data)
        udid = self.device(data)
        if not app or not udid:
            raise ValueError("Select a saved IPA and the paired iPhone")
        self.idle()
        title = "Reinstall latest over VPN: " + app["name"]
        job = self.jobs.start("refresh", title,
                              lambda j: remote_altkeeper.latest_job(
                                  j, udid, app["id"], app["bundle_id"], self.sources,
                                  str(data.get("source") or "") or None
                              ))
        return {"job": job.id}

    def remote_code(self, data):
        return remote_altkeeper.verification_code(data)

'''
    if "    def remote_install(self, data):" not in source:
        marker = "    def refresh(self, data):"
        if source.count(marker) != 1:
            raise SystemExit("Remote adapter cannot identify refresh route")
        source = source.replace(marker, insertion + marker, 1)

    remote_guard = '''    def refresh(self, data):
        if remote_altkeeper.enabled():
            app = self.app(data)
            udid = self.device(data)
            if not app or not udid:
                raise ValueError("Remote renewal needs one explicit app and a paired iPhone; bulk is disabled until installed-app verification is available")
            self.idle()
            title = "Remote re-sign: " + app["name"]
            job = self.jobs.start("refresh", title,
                                  lambda j: remote_altkeeper.renew_job(j, udid, app["bundle_id"]))
            return {"job": job.id}
'''
    source = _insert_once(source, "    def refresh(self, data):\n",
                          remote_guard, "refresh adapter")

    route_anchor = '            "/api/refresh": self.refresh,'
    new_route = (route_anchor +
                 '\n            "/api/remote/install": self.remote_install,' +
                 '\n            "/api/remote/latest": self.remote_latest,' +
                 '\n            "/api/remote/code": self.remote_code,')
    source = _insert_once(source, route_anchor, new_route, "remote POST routes")

    get_anchor = '            if path == "/api/job":'
    new_get = ('            if path == "/api/remote/status":\n'
               '                return self.send(200, remote_altkeeper.diagnose())\n' +
               get_anchor)
    source = _insert_once(source, get_anchor, new_get, "remote status GET")
    server.write_text(source)

    # Keep SideLoader's existing Apple 2FA field. When remote, the current job
    # forwards its validated six-digit input to AltKeeper's waiting challenge,
    # rather than trying to write it to a nonexistent PTY.
    jobs_file = package / "jobs.py"
    jobs = jobs_file.read_text()
    accepting = '"accepts_input": self.fd is not None'
    remote_accept = '"accepts_input": self.fd is not None or getattr(self, "remote_input", False)'
    jobs = _insert_once(jobs, accepting, remote_accept, "remote verification UI")
    # The upstream Job.send has already been hardened by
    # patch-apple-2fa-safety.py. Inject remote handling before its PTY logic,
    # preserving the strict 6-digit validation and one-use challenge rules.
    send_anchor = '''    def send(self, text):
        # This endpoint is exclusively for an active 2FA challenge.'''
    send_remote = '''    def send(self, text):
        if getattr(self, "remote_input", False):
            code = text.strip()
            if not re.fullmatch(r"[0-9]{6}", code):
                raise ValueError("Enter exactly six digits from the Apple verification prompt")
            with self.lock:
                if self.kind != "refresh" or not self.running or not self.needs_input:
                    raise RuntimeError("No Apple verification code is currently requested")
            from . import remote_altkeeper
            remote_altkeeper.verification_code({"code": code})
            with self.lock:
                self.needs_input = False
                self.verification_deadline = None
                self.lines.append("Remote Apple verification code submitted [redacted]")
            return
        # This endpoint is exclusively for an active 2FA challenge.'''
    jobs = _insert_once(jobs, send_anchor, send_remote, "remote code forwarding")
    jobs_file.write_text(jobs)

    # The legacy SideLoader watcher operates through usbmuxd. In remote mode
    # AltKeeper owns any scheduled renewals; never let the old watcher start
    # competing Apple sign-ins against an unreachable legacy device channel.
    watcher_file = package / "watcher.py"
    watcher = watcher_file.read_text()
    if "from . import remote_altkeeper" not in watcher:
        anchor = "from . import config, retry_guard, store"
        if watcher.count(anchor) != 1:
            raise SystemExit("Remote adapter cannot locate the legacy watcher imports")
        watcher = watcher.replace(anchor, anchor + "\nfrom . import remote_altkeeper", 1)
    if "if remote_altkeeper.enabled():" not in watcher:
        anchor = "        while True:\n            time.sleep(5)"
        if watcher.count(anchor) != 1:
            raise SystemExit("Remote adapter cannot locate the legacy watcher loop")
        watcher = watcher.replace(
            anchor,
            "        while True:\n            if remote_altkeeper.enabled():\n"
            "                time.sleep(60)\n                continue\n"
            "            time.sleep(5)",
            1
        )
    watcher_file.write_text(watcher)
    print("Optional remote AltKeeper bridge installed (inactive without environment opt-in).")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("Usage: remote_server_patch.py <sideloop-checkout> <overlay-dir>")
    apply(Path(sys.argv[1]), Path(sys.argv[2]))
