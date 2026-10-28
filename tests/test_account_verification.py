"""Apple Account must be verified by successful signing, not password storage."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
PKG = "sideloader_account_verification_test"
package = types.ModuleType(PKG)
package.__path__ = []
config = types.ModuleType(PKG + ".config")
guard = types.ModuleType(PKG + ".retry_guard")
guard.status = lambda: {"blocked": False}
sys.modules.update({PKG: package, PKG + ".config": config,
                    PKG + ".retry_guard": guard})
spec = importlib.util.spec_from_file_location(
    PKG + ".account", ROOT / "overlay" / "account.py")
account = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = account
spec.loader.exec_module(account)


class VerificationTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        config.DATA = Path(tmp.name)
        config.STATE = config.DATA / "state"
        self.settings = {"APPLE_ID": "first@example.com",
                         "APPLE_PASSWORD": "first-secret", "AUTO_CHECK": "1"}
        config.read = lambda: dict(self.settings)
        config.update = self.settings.update
        guard.status = lambda: {"blocked": False}
        self.app = types.SimpleNamespace(idle=lambda: None)
        (config.DATA / "apps").mkdir()
        (config.DATA / "apps" / "saved.ipa").write_bytes(b"saved")
        (config.DATA / "devices").mkdir()
        (config.DATA / "devices" / "pairing").write_text("paired")

    def test_saved_password_is_not_verified(self):
        self.assertEqual(account.verification()["state"], "unverified")
        self.assertFalse(account.is_verified())
        self.assertFalse(account.verified_file().exists())

    def test_successful_sign_and_install_marks_account_verified(self):
        account.mark_verified()
        state = account.verification()
        self.assertEqual(state["state"], "verified")
        self.assertGreater(state["verified_at"], 0)
        self.assertTrue(account.is_verified())

    def test_switch_account_invalidates_verification_cache_and_renewal(self):
        account.mark_verified()
        cache = config.DATA / "AltServerData"
        cache.mkdir()
        (cache / "certificate").write_text("previous account")
        result = account.save_account(
            self.app, {"apple_id": "second@example.com", "password": "new-secret"})
        self.assertTrue(result["ok"])
        self.assertEqual(account.verification()["state"], "unverified")
        self.assertFalse(cache.exists())
        self.assertEqual(self.settings["APPLE_ID"], "second@example.com")
        self.assertEqual(self.settings["APPLE_PASSWORD"], "new-secret")
        self.assertEqual(self.settings["AUTO_CHECK"], "0")
        self.assertTrue((config.DATA / "apps" / "saved.ipa").exists())
        self.assertTrue((config.DATA / "devices" / "pairing").exists())

    def test_same_account_new_password_resets_prior_success(self):
        account.mark_verified()
        account.save_account(
            self.app, {"apple_id": "first@example.com", "password": "changed"})
        self.assertEqual(account.verification()["state"], "unverified")
        self.assertEqual(self.settings["AUTO_CHECK"], "0")

    def test_unchanged_account_save_does_not_reset_approval(self):
        account.mark_verified()
        account.save_account(self.app, {"apple_id": "first@example.com"})
        self.assertEqual(account.verification()["state"], "verified")
        self.assertEqual(self.settings["AUTO_CHECK"], "1")

    def test_cannot_reuse_another_accounts_password(self):
        with self.assertRaises(ValueError):
            account.save_account(self.app, {"apple_id": "other@example.com"})
        self.assertEqual(self.settings["APPLE_ID"], "first@example.com")

    def test_busy_server_cannot_change_account(self):
        self.app.idle = lambda: (_ for _ in ()).throw(RuntimeError("busy"))
        with self.assertRaises(RuntimeError):
            account.save_account(
                self.app, {"apple_id": "other@example.com", "password": "new"})
        self.assertEqual(self.settings["APPLE_ID"], "first@example.com")

    def test_lock_is_not_reported_as_verified(self):
        account.mark_verified()
        guard.status = lambda: {"blocked": True, "code": "-20209",
                                "message": "Apple reports account locked.",
                                "action": "Unlock before retrying."}
        state = account.verification()
        self.assertEqual(state["state"], "failed")
        self.assertEqual(state["code"], "-20209")
        self.assertFalse(account.is_verified())

    def test_previous_account_attempt_is_not_falsely_blamed_on_new_account(self):
        guard.status = lambda: {"blocked": True, "code": "previous_account_attempt",
                                "reason": "account_changed",
                                "message": "Earlier account attempt is paused.",
                                "action": "Explicitly resume."}
        state = account.verification()
        self.assertEqual(state["state"], "paused")
        self.assertFalse(account.is_verified())
        self.assertNotEqual(state["state"], "failed")

    def test_in_flight_attempt_is_not_called_an_authentication_failure(self):
        guard.status = lambda: {"blocked": True, "code": "attempt_in_progress",
                                "message": "One attempt underway."}
        self.assertEqual(account.verification()["state"], "signing")

    def test_symlinked_signing_cache_rejected_without_account_change(self):
        (config.DATA / "AltServerData").symlink_to(config.DATA / "apps", target_is_directory=True)
        with self.assertRaises(RuntimeError):
            account.save_account(
                self.app, {"apple_id": "other@example.com", "password": "new"})
        self.assertEqual(self.settings["APPLE_ID"], "first@example.com")
        self.assertTrue((config.DATA / "apps" / "saved.ipa").exists())


if __name__ == "__main__":
    unittest.main()
