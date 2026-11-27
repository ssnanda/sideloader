#!/usr/bin/env python3
"""Explain why a registered iPhone is offline, with specific fix steps.

The Mac-side relay (bin/lib/usbmux-relay.py --status-file) writes
/data/host-devices.json every 30 s: which iPhones macOS usbmuxd lists, and
which iPhones announce Wi-Fi sync on the network but are not listed.
/api/state adds `problem` ({level, title, steps}) to each registered iPhone
that SideLoader cannot reach; the web UI and TapTether show it verbatim.
Must run after patch-background-refresh.py.
"""

import sys
from pathlib import Path

if len(sys.argv) != 2:
    raise SystemExit("Usage: patch-device-hints.py <sideloop-checkout>")

package = Path(sys.argv[1]) / "sideloop"
MARK = "SideLoader device problems v1"

server = package / "server.py"
s = server.read_text()
if MARK not in s:
    s = s.rstrip("\n") + f'''


# {MARK} start
import json as _sl_json

_SL_HOST_STATUS = config.DATA / "host-devices.json"
_SL_FIX_STEPS = [
    "Unlock {{name}} and keep it awake for 30 seconds.",
    "On the Mac, click {{name}} in Finder's sidebar.",
    "Still offline: plug {{name}} into the Mac by cable once, then unplug.",
    "Still offline: on the Mac run  sudo killall -9 usbmuxd  (macOS restarts it).",
]


def _sl_host_status():
    try:
        status = _sl_json.loads(_SL_HOST_STATUS.read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(status, dict) or time.time() - int(status.get("updated") or 0) > 180:
        return None
    return status


def _sl_device_problem(device, status, candidates=1):
    name = device.get("name") or "iPhone"
    udid = str(device.get("udid") or "").lower()
    if device.get("live"):
        return None  # listed by usbmuxd (reachable, or locked and reported as such)
    if status is None:
        return {{"level": "warning", "code": "host_status_unavailable",
                 "title": f"{{name}} is offline to SideLoader, and the Mac relay is not reporting why.",
                 "steps": ["Run ./bin/build-docker.sh on the Mac to reinstall the relay, then check again."]}}
    steps = [step.format(name=name) for step in _SL_FIX_STEPS]
    if udid in {{u.lower() for u in status.get("dropped") or []}}:
        return {{"level": "error", "code": "usbmuxd_dropped",
                 "title": f"{{name}} is on the Mac's Wi-Fi, but macOS stopped listing it to SideLoader. "
                          "No renewals or installs can run.",
                 "steps": steps}}
    mapped = {{u.lower() for u in status.get("mapped") or []}}
    if int(status.get("unmatched_announced") or 0) and udid not in mapped:
        return {{"level": "warning", "code": "usbmuxd_dropped_likely",
                 "title": f"{{name}} is offline to SideLoader, but an iPhone macOS isn't listing is on this "
                          f"Wi-Fi ({{'probably' if candidates <= 1 else 'possibly'}} {{name}}). "
                          "Renewals wait until it is listed again.",
                 "steps": steps}}
    return {{"level": "warning", "code": "not_on_network",
             "title": f"{{name}} is not on the Mac's Wi-Fi (or Wi-Fi sync is off). Renewals wait until it is back.",
             "steps": [f"Join {{name}} to the same Wi-Fi as the Mac and unlock it.",
                       f"In Finder (with {{name}} plugged in once), turn on 'Show this iPhone when on Wi-Fi'."]}}


_sl_state_problems = App.state


def _sl_state_with_problems(self):
    result = _sl_state_problems(self)
    status = _sl_host_status()
    devices = result.get("registered") or []
    mapped = {{u.lower() for u in (status or {{}}).get("mapped") or []}}
    candidates = sum(1 for d in devices
                     if not d.get("live") and str(d.get("udid") or "").lower() not in mapped)
    for device in devices:
        device["problem"] = _sl_device_problem(device, status, candidates)
    result["host_check"] = {{"updated": status.get("updated") if status else None}}
    return result


App.state = _sl_state_with_problems
# {MARK} end
'''
    server.write_text(s)

index = package / "index.html"
h = index.read_text()
anchor = '  if (!c.auto_check) issues.push(["", "Automatic re-signing is off."]);\n'
added = (
    '  /* ' + MARK + ' */\n'
    '  for (const d of devs) if (d.problem) issues.push([d.problem.level === "error" ? "bad" : "",\n'
    '    `${d.problem.level === "error" ? "ERROR" : "WARNING"}: ${d.problem.title} Fix: ` +\n'
    '    d.problem.steps.map((step, i) => `${i + 1}) ${step}`).join(" ")]);\n'
)
if MARK not in h:
    if h.count(anchor) != 1:
        raise SystemExit(f"Device problems patch: expected one issues anchor, found {h.count(anchor)}")
    h = h.replace(anchor, added + anchor, 1)
    index.write_text(h)

print("Specific offline-iPhone errors and fix steps installed.")
