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
    send_anchor = '''    def send(self, text):
        if self.fd is None:'''
    send_remote = '''    def send(self, text):
        if getattr(self, "remote_input", False):
            from . import remote_altkeeper
            remote_altkeeper.verification_code({"code": text})
            with self.lock:
                self.needs_input = False
                self.lines.append("Remote verification code submitted.")
            return
        if self.fd is None:'''
    jobs = _insert_once(jobs, send_anchor, send_remote, "remote code forwarding")
    jobs_file.write_text(jobs)
    print("Optional remote AltKeeper bridge installed (inactive without environment opt-in).")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("Usage: remote_server_patch.py <sideloop-checkout> <overlay-dir>")
    apply(Path(sys.argv[1]), Path(sys.argv[2]))
