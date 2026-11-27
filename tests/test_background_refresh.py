"""Six-day renewal, automatic source updates and client-initiated checks."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
WATCHER = (ROOT / "overlay" / "auto_resign_watcher.py").read_text()
PATCH = (ROOT / "overlay" / "patch-background-refresh.py").read_text()


class BackgroundRefreshTests(unittest.TestCase):
    def test_build_order(self):
        build = (ROOT / "bin" / "build-docker.sh").read_text()
        self.assertLess(build.index("patch-account-debug.py"), build.index("patch-background-refresh.py"))

    def test_updates_never_reinstall_removed_apps(self):
        # Download path refuses apps no longer on the phone; signing keeps --auto.
        self.assertIn('"reinstall_latest": True', WATCHER)
        self.assertIn('"install_now": False', WATCHER)
        self.assertIn('["refresh.sh", "--auto", "--force", "--app", update["app_id"],', WATCHER)

    def test_updates_require_a_strictly_newer_version_and_back_off(self):
        self.assertIn("version_is_newer(", WATCHER)
        self.assertIn("UPDATE_RETRY", WATCHER)
        self.assertIn("self.failed_updates[update[\"key\"]] = time.time()", WATCHER)

    def test_safety_gates_still_apply(self):
        for gate in ('cfg["AUTO_CHECK"] != "1"', "is_verified()", 'retry_guard.status().get("blocked")'):
            self.assertIn(gate, WATCHER)

    def test_routes_are_authenticated(self):
        self.assertIn('if path == "/api/auto/run":\\n', PATCH)
        self.assertIn('if not self.authed():', PATCH)
        self.assertIn("watcher.kick(udid)", PATCH)


if __name__ == "__main__":
    unittest.main()
