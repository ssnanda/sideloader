"""Static regression coverage for six-hour, installed-only auto re-signing."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class AutoResignTests(unittest.TestCase):
    def test_scheduler_queues_every_due_pair_sequentially(self):
        source = (ROOT / "overlay" / "auto_resign_watcher.py").read_text()
        self.assertIn("RENEW_BEFORE_SECONDS = 6 * 60 * 60", source)
        self.assertIn("for app_id in store.app_ids()", source)
        self.assertIn("for udid in store.app_devices(app_id)", source)
        self.assertIn("for _expiry, app_id, udid in targets", source)
        self.assertIn('["refresh.sh", "--auto", "--app", app_id, "--device", udid]', source)
        self.assertIn('retry_guard.status().get("blocked")', source)

    def test_auto_mode_skips_removed_apps(self):
        patch = (ROOT / "overlay" / "patch-auto-resign.py").read_text()
        self.assertIn('--auto) AUTO=1', patch)
        self.assertIn('automatic renewal skipped', patch)
        self.assertIn('automatic renewal never reinstalls a removed app', patch)
        self.assertIn("S.config.renew_before_days * 86400", patch)
        self.assertIn("6 * 60 * 60", patch)

    def test_bulk_resign_preserves_removed_app_policy(self):
        patch = (ROOT / "overlay" / "patch-auto-resign.py").read_text()
        self.assertIn("--bulk) BULK=1", patch)
        self.assertIn("bulk_forward", patch)
        self.assertIn("bulk re-sign never reinstalls a removed app", patch)
        self.assertIn("bulk re-sign skipped", patch)
        self.assertIn("AUTO || BULK", patch)
        self.assertIn('FORCE=1', patch)  # Explicit single-app installation remains supported.

    def test_build_installs_canonical_scheduler_after_safety_patches(self):
        build = (ROOT / "bin" / "build-docker.sh").read_text()
        self.assertLess(build.index("patch-apple-2fa-safety.py"),
                        build.index("patch-auto-resign.py"))
        self.assertLess(build.index("patch-auto-resign.py"),
                        build.index("patch-screen-flow.py"))

    def test_legacy_watcher_patches_accept_canonical_repeat_build(self):
        for name in ("patch-retry-guard.py", "patch-apple-verification.py"):
            source = (ROOT / "overlay" / name).read_text()
            self.assertIn('canonical_watcher = "RENEW_BEFORE_SECONDS = 6 * 60 * 60"', source)


if __name__ == "__main__":
    unittest.main()
