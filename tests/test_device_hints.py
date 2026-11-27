"""Offline-iPhone diagnosis: relay status file and specific ERROR/WARNING text."""
from pathlib import Path
import importlib.util
import unittest

ROOT = Path(__file__).resolve().parents[1]
PATCH = (ROOT / "overlay" / "patch-device-hints.py").read_text()
SPEC = importlib.util.spec_from_file_location("relay", ROOT / "bin" / "lib" / "usbmux-relay.py")
RELAY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RELAY)


class DeviceHintTests(unittest.TestCase):
    def test_build_installs_relay_status_and_patch(self):
        build = (ROOT / "bin" / "build-docker.sh").read_text()
        self.assertLess(build.index("patch-background-refresh.py"), build.index("patch-device-hints.py"))
        self.assertIn('"--status-file"', (ROOT / "bin" / "lib" / "macos-relay.sh").read_text())

    def test_wifi_mac_parsed_from_usbmuxd_service_name(self):
        props = {"EscapedFullServiceName": "ee:d0:07:9d:8a:fe@fe80::ecd0:7ff:fe9d:8afe-supportsRP-26._apple-mobdev2._tcp.local."}
        self.assertEqual(RELAY.wifi_mac(props), "ee:d0:07:9d:8a:fe")
        self.assertEqual(RELAY.wifi_mac({}), "")

    def test_messages_are_specific(self):
        for code in ("usbmuxd_dropped", "usbmuxd_dropped_likely", "not_on_network", "host_status_unavailable"):
            self.assertIn(f'"code": "{code}"', PATCH)
        self.assertIn("sudo killall -9 usbmuxd", PATCH)
        self.assertIn('"ERROR" : "WARNING"', PATCH)

    def test_reachable_phone_has_no_problem(self):
        self.assertIn('if device.get("live"):\n        return None', PATCH)


if __name__ == "__main__":
    unittest.main()
