"""Device scan refresh and wizard display must be upgrade-safe on existing installs."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / "overlay" / "patch-device-health.py"

DEVICE = """import time
SCAN_INTERVAL = 60
class Health:
    def __init__(self):
        self.scanning = False
        self.on_arrival = lambda udid: None
    def scan(self):
        with self.lock:
            arrived = here - self.here
            self.devices, self.here, self.anisette, self.muxer = devices, here, anisette, muxer
    def snapshot(self):
        with self.lock:
            return {"devices": list(self.devices), "anisette": self.anisette,
                    "muxer": self.muxer, "scanning": self.scanning}
"""
SERVER = '''        return {
            "scanning": h["scanning"],
        }
'''
INDEX = '''function settingsView() {
  const onlineDevice = devs.some(d => d.live && d.live.reachable);
  const appleDone = Boolean(c.apple_id && c.has_password);
  const deviceDone = devs.length > 0 && onlineDevice;
  const subtitle = devs.length ? `${esc(devs[0].name)} · ${onlineDevice ? "Connected" : "Saved · Offline — reconnect to continue"}` : "Connect or scan for a device";
  const step2 = appleDone ? "Account details saved" : "Enter account and password";
}
const devState = d => !d.live ? ["", "Away"] : d.live.reachable ? ["ok", "Connected"] : ["warn", "Locked"];
'''

class RefreshTests(unittest.TestCase):
    def test_fresh_install_and_rebuild_are_idempotent(self):
        with tempfile.TemporaryDirectory() as t:
            package = Path(t) / "sideloop"
            package.mkdir()
            paths = {"devices.py": DEVICE, "server.py": SERVER, "index.html": INDEX}
            for name, content in paths.items():
                (package/name).write_text(content)
            cmd = [sys.executable, str(PATCH), t]
            subprocess.run(cmd, check=True, capture_output=True)
            changed = {name:(package/name).read_text() for name in paths}
            self.assertIn("SCAN_INTERVAL = 30", changed["devices.py"])
            self.assertIn("self.last_checked = int(time.time())", changed["devices.py"])
            self.assertIn('"last_checked": self.last_checked', changed["devices.py"])
            self.assertIn('"last_checked": h["last_checked"]', changed["server.py"])
            self.assertIn("Last checked ${checkedTime}", changed["index.html"])
            self.assertIn("Status unverified", changed["index.html"])
            self.assertIn("recentCheck && devs.some", changed["index.html"])
            self.assertIn("Credentials saved · not verified with Apple", changed["index.html"])
            self.assertIn("const deviceDone = devs.length > 0 && onlineDevice", changed["index.html"])
            subprocess.run(cmd, check=True, capture_output=True)
            self.assertEqual(changed, {name:(package/name).read_text() for name in paths})
    def test_refuses_unknown_upstream(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "sideloop"
            p.mkdir()
            for name, content in {"devices.py": DEVICE.replace("SCAN_INTERVAL = 60", "SCAN_INTERVAL = 999"), "server.py": SERVER, "index.html": INDEX}.items():
                (p/name).write_text(content)
            result = subprocess.run([sys.executable, str(PATCH),t], capture_output=True)
            self.assertNotEqual(result.returncode,0)
            self.assertIn(b"expected one anchor",result.stderr)

if __name__ == "__main__":
    unittest.main()
