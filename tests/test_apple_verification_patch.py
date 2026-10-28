"""Apple Account status overlay must patch existing builds and remain idempotent."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / "overlay" / "patch-apple-verification.py"
SERVER = '''from .account import forget_account
from . import retry_guard
class App:
    def state(self):
        return {
            "signing_guard": retry_guard.status(),
        }
    def apple_id(self, data):
        apple_id = str(data.get("apple_id", "")).strip()
        if "@" not in apple_id:
            raise ValueError("enter the Apple ID's email address")
        values = {"APPLE_ID": apple_id}
        if data.get("password"):
            values["APPLE_PASSWORD"] = str(data["password"])
        elif not config.read()["APPLE_PASSWORD"]:
            raise ValueError("enter the password")
        config.update(values)

    def settings(self, data):
        return None
'''
WATCHER = '''from . import config, store, retry_guard
class Watcher:
    def loop(self):
            job = self.jobs.claim_auto()
'''
REFRESH = '''if (( rc == 0 )) && [[ "$(app_state)" == installed ]] && stamp_success; then
  msg="refreshed, valid until $(fmt_epoch "$(cat "$EXPIRY")")"
  log "OK $msg"; record ok "$msg"
  prune_profiles
'''
INDEX = '''function settingsView() {
  const appleDone = Boolean(c.apple_id && c.has_password);
  const label = appleDone ? "Credentials saved · not verified with Apple" : "Enter account and password";
}
<form id="aidf"><button class="cell action">Save</button></form>
<div class="foot">Use the regular password, not an app-specific one.</div>
'''


class PatcherTests(unittest.TestCase):
    def test_upgrade_existing_checkout_and_repeat(self):
        with tempfile.TemporaryDirectory() as d:
            package = Path(d) / "sideloop"
            package.mkdir()
            (Path(d) / "scripts").mkdir()
            files = {
                package / "server.py": SERVER,
                package / "watcher.py": WATCHER,
                package / "index.html": INDEX,
                Path(d) / "scripts" / "refresh.sh": REFRESH,
            }
            for p, value in files.items():
                p.write_text(value)
            cmd = [sys.executable, str(PATCH), d]
            subprocess.run(cmd, check=True, capture_output=True)
            patched = {p: p.read_text() for p in files}
            self.assertIn("save_account(self, data)", patched[package / "server.py"])
            self.assertIn('"account_verification": verification()', patched[package / "server.py"])
            self.assertIn("if not is_verified():", patched[package / "watcher.py"])
            self.assertIn("python3 -m sideloop.account verified", patched[Path(d)/"scripts"/"refresh.sh"])
            self.assertIn('appleInfo.state === "verified"', patched[package / "index.html"])
            self.assertIn("Save credentials", patched[package / "index.html"])
            self.assertIn("no independent login-only check", patched[package / "index.html"])
            subprocess.run(cmd, check=True, capture_output=True)
            self.assertEqual(patched, {p: p.read_text() for p in files})

    def test_fail_safe_on_changed_upstream(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "sideloop"
            p.mkdir()
            (p / "server.py").write_text(SERVER.replace(
                "from .account import forget_account", "# removed account import"))
            result = subprocess.run([sys.executable, str(PATCH), d],
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("expected 1 anchor", result.stderr)


if __name__ == "__main__":
    unittest.main()
