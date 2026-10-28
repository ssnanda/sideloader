#!/usr/bin/env python3
"""Keep SideLoader connection status current and timestamp device checks.

This overlay runs AFTER patch-navigation.py, on both new and existing builds.
It never changes stored pairing, apps, accounts or signing state.
"""
from pathlib import Path
import sys

if len(sys.argv) != 2:
    sys.exit("Usage: patch-device-health.py <sideloop-checkout>")
root = Path(sys.argv[1])


def replace(path, before, after, label):
    data = path.read_text()
    if after in data:
        return
    count = data.count(before)
    if count != 1:
        sys.exit(f"Device health patch {label}: expected one anchor, found {count}")
    path.write_text(data.replace(before, after, 1))


devices = root / "sideloop" / "devices.py"
replace(devices, "SCAN_INTERVAL = 60", "SCAN_INTERVAL = 30",
        "30-second scan interval")
replace(devices,
        "        self.scanning = False\n        self.on_arrival = lambda udid: None",
        "        self.scanning = False\n        self.last_checked = 0\n        self.on_arrival = lambda udid: None",
        "scan timestamp initialization")
replace(devices,
        "                self.devices, self.here, self.anisette, self.muxer = devices, here, anisette, muxer",
        "                self.devices, self.here, self.anisette, self.muxer = devices, here, anisette, muxer\n                self.last_checked = int(time.time())",
        "record scan timestamp")
replace(devices,
        '                    "muxer": self.muxer, "scanning": self.scanning}',
        '                    "muxer": self.muxer, "scanning": self.scanning,\n                    "last_checked": self.last_checked}',
        "expose timestamp")

server = root / "sideloop" / "server.py"
replace(server,
        '            "scanning": h["scanning"],',
        '            "scanning": h["scanning"],\n            "last_checked": h["last_checked"],',
        "serve last checked")

index = root / "sideloop" / "index.html"
replace(index,
        "  const onlineDevice = devs.some(d => d.live && d.live.reachable);",
        """  /* SideLoader live device status v1 */
  const checkedAt = Number(S.last_checked || 0);
  const checkedAgo = checkedAt ? Math.max(0, S.now - checkedAt) : Infinity;
  const recentCheck = checkedAgo <= 120;
  const onlineDevice = recentCheck && devs.some(d => d.live && d.live.reachable);
  const checkedTime = checkedAt ? new Date(checkedAt * 1000).toLocaleTimeString([], {hour:"numeric", minute:"2-digit", second:"2-digit"}) : "never";
  const connectionLabel = !recentCheck ? "Status unverified" : onlineDevice ? "Connected" : "Offline — reconnect to continue";""",
        "fresh connection state")
replace(index,
        'devs.length ? `${esc(devs[0].name)} · ${onlineDevice ? "Connected" : "Saved · Offline — reconnect to continue"}` : "Connect or scan for a device"',
        'devs.length ? `${esc(devs[0].name)} · ${connectionLabel} · Last checked ${checkedTime}` : `Connect or scan for a device · Last checked ${checkedTime}`',
        "wizard last checked label")
replace(index,
        'const devState = d => !d.live ? ["", "Away"] : d.live.reachable ? ["ok", "Connected"] : ["warn", "Locked"];',
        'const devState = d => !S.last_checked || S.now - S.last_checked > 120 ? ["", "Status unverified"] : !d.live ? ["", "Away"] : d.live.reachable ? ["ok", "Connected"] : ["warn", "Locked"];',
        "app card freshness")
replace(index,
        'appleDone ? "Account details saved" : "Enter account and password"',
        'appleDone ? "Credentials saved · not verified with Apple" : "Enter account and password"',
        "explain saved credentials")
replace(index,
        'c.auto_check ? "Automatic renewal enabled" : "Automatic renewal disabled"',
        'c.auto_check ? "Renewal enabled · success not yet verified" : "Automatic renewal disabled"',
        "explain enabled does not mean successfully renewed")
print("SideLoader device health refresh: every 30s, last-checked display and stale-state protection.")
