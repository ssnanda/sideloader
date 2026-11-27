#!/usr/bin/env python3
"""Expose automatic renewal/update status and a client-initiated check.

GET  /api/auto      (signed in) watcher status: paused reason, last run/result,
                    updates installed or failed, apps due, next check times.
POST /api/auto/run  (signed in) {"device": udid?}: the client (TapTether)
                    reports the phone is on this network; renew what is due
                    and check sources for newer versions now.

The watcher (overlay/auto_resign_watcher.py) does the work; this only wires it
to the HTTP server and adds its status to Settings → Timing & debug.
Must run after patch-account-debug.py.
"""

import sys
from pathlib import Path

if len(sys.argv) != 2:
    raise SystemExit("Usage: patch-background-refresh.py <sideloop-checkout>")

package = Path(sys.argv[1]) / "sideloop"
MARK = "SideLoader background refresh v1"


def replace_once(path, old, new, label):
    text = path.read_text()
    if new in text:
        return
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"Background refresh patch {label}: expected one anchor, found {count}")
    path.write_text(text.replace(old, new, 1))


replace_once(
    package / "__main__.py",
    '    Server(("0.0.0.0", PORT), handler(App(jobs, health, muxers))).serve_forever()\n',
    '    app = App(jobs, health, muxers)\n'
    '    app.watcher = watcher  # SideLoader: /api/auto status and client-initiated checks\n'
    '    Server(("0.0.0.0", PORT), handler(app)).serve_forever()\n',
    "watcher handle",
)

server = package / "server.py"
replace_once(
    server,
    '            if path == "/api/debug":\n',
    f'            # {MARK}\n'
    '            if path == "/api/auto":\n'
    '                watcher = getattr(app, "watcher", None)\n'
    '                return self.send(200, watcher.status_view() if watcher else {"error": "watcher unavailable"})\n'
    '            if path == "/api/debug":\n',
    "status route",
)
replace_once(
    server,
    '            if path == "/api/auth/password":\n',
    '            if path == "/api/auto/run":\n'
    '                if not self.authed():\n'
    '                    return self.error(401, "sign in first")\n'
    '                watcher = getattr(app, "watcher", None)\n'
    '                if not watcher:\n'
    '                    return self.error(409, "watcher unavailable")\n'
    '                try:\n'
    '                    udid = app.device({"device": str(data.get("device", ""))})\n'
    '                except ValueError as e:\n'
    '                    return self.error(400, str(e))\n'
    '                watcher.kick(udid)\n'
    '                return self.send(200, watcher.status_view())\n'
    '            if path == "/api/auth/password":\n',
    "client check route",
)
replace_once(
    server,
    '"state_timing": dict(_SL_STATE_TIMING)})\n',
    '"state_timing": dict(_SL_STATE_TIMING),\n'
    '                                       "auto": app.watcher.status_view() if getattr(app, "watcher", None) else None})\n',
    "debug status",
)

index = package / "index.html"
replace_once(
    index,
    '      ["Sign-in attempts (server, newest first)",',
    '      ["Automatic renewal & updates (server)", ["Field", "Value"],\n'
    '        Object.entries(server.auto || {}).map(([k, v]) => [k, typeof v === "object" && v !== null ? JSON.stringify(v) : v])],\n'
    '      ["Sign-in attempts (server, newest first)",',
    "debug section",
)

print("Automatic renewal status and client-initiated checks installed.")
