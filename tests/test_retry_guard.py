"""Compatibility regression tests for persistent one-AltServer-call signing guard."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import types
import unittest

PKG = "sideloader_guard_under_test"
pkg = types.ModuleType(PKG)
pkg.__path__ = []
cfg = types.ModuleType(PKG + ".config")
cfg.STATE = Path('/tmp/sideloader-guard-test-placeholder')
sys.modules[PKG] = pkg
sys.modules[PKG + ".config"] = cfg
path = Path(__file__).resolve().parents[1] / "overlay" / "retry_guard.py"
spec = importlib.util.spec_from_file_location(PKG + ".retry_guard", path)
guard = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = guard
spec.loader.exec_module(guard)


class RetryGuardTests(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        cfg.STATE = Path(td.name) / "state"
        self.state = {"APPLE_ID": "one@example.com", "APPLE_PASSWORD": "never-store"}
        cfg.read = lambda: self.state
        guard.FILE = cfg.STATE / "sideloader-signing-block.json"
        guard.LOCK = cfg.STATE / ".sideloader-signing-block.lock"

    def test_repeat_build_recognizes_existing_signing_banner(self):
        patcher = (Path(__file__).resolve().parents[1] / "overlay" / "patch-retry-guard.py").read_text()
        self.assertIn("if not already_has_banner:", patcher)
        self.assertIn("'sideloader-resume' in page", patcher)
        self.assertIn("'S.signing_guard.message' in page", patcher)

    def test_locked_account_blocks_new_invocation(self):
        token = guard.begin()
        outcome = guard.failed("This Apple Account has been locked for security reasons. (-20209)", 1, token)
        self.assertEqual(outcome["code"], "-20209")
        self.assertTrue(outcome["blocked"])
        with self.assertRaises(RuntimeError):
            guard.begin()
        raw = guard.FILE.read_text()
        self.assertNotIn("never-store", raw)
        self.assertNotIn("one@example.com", raw)

    def test_repeated_failure_does_not_increment_or_reset(self):
        token = guard.begin()
        initial = guard.failed("(-80046)", 1, token)
        after = guard.failed("Another failure", 1)
        self.assertEqual(after["code"], "-80046")
        self.assertEqual(initial["since"], after["since"])

    def test_pty_refines_generic_shell_error(self):
        token = guard.begin()
        guard.failed("", 1, token)
        self.assertEqual(guard.status()["code"], "install_failed")
        guard.failed("Alert: Could not install app.ipa. (-80046)", 1)
        self.assertEqual(guard.status()["code"], "-80046")

    def test_pty_refines_generic_install_failure_to_actual_apple_signin_error(self):
        token = guard.begin()
        guard.failed("", 1, token)
        self.assertEqual(guard.status()["code"], "install_failed")
        guard.failed("Alert: Could not install app.ipa\\nUnable to sign you in to your Apple Account. Try again later. (-36607)", 1)
        self.assertEqual(guard.status()["code"], "-36607")
        self.assertEqual(guard.status()["reason"], "apple_authentication_unavailable")

    def test_manual_resume_allows_one_new_launch(self):
        token = guard.begin()
        guard.failed("verification failed", 1, token)
        guard.resume()
        self.assertFalse(guard.status()["blocked"])
        token = guard.begin()
        guard.failed("timed out", 124, token)
        self.assertTrue(guard.status()["blocked"])
        self.assertEqual(guard.status()["code"], "timeout")

    def test_changing_apple_account_requires_explicit_resume(self):
        token = guard.begin()
        guard.failed("(-20209)", 1, token)
        self.state["APPLE_ID"] = "two@example.com"
        self.assertTrue(guard.status()["blocked"])
        self.assertEqual(guard.status()["code"], "previous_account_attempt")
        with self.assertRaises(RuntimeError):
            guard.begin()
        guard.resume()
        self.assertTrue(guard.begin())

    def test_corrupted_state_is_fail_closed(self):
        guard.FILE.parent.mkdir(parents=True)
        guard.FILE.write_text("{corrupted")
        self.assertTrue(guard.status()["blocked"])
        self.assertEqual(guard.status()["code"], "guard_state_unreadable")
        with self.assertRaises(RuntimeError):
            guard.begin()
        guard.resume()
        self.assertFalse(guard.status()["blocked"])

    def test_app_specific_password_rejected_22406_and_blocks_retries(self):
        token = guard.begin()
        status = guard.failed("Enter the correct password for this Apple Account. (-22406)", 1, token)
        self.assertTrue(status["blocked"])
        self.assertEqual(status["code"], "-22406")
        self.assertEqual(status["reason"], "password_rejected")
        self.assertIn("app-specific password", status["message"])
        with self.assertRaises(RuntimeError):
            guard.begin()

    def test_36607_no_lock_inference(self):
        token = guard.begin()
        state = guard.failed("Unable to sign you in to your Apple Account. Try again later. (-36607)", 1, token)
        self.assertEqual(state["code"], "-36607")
        self.assertEqual(state["reason"], "apple_authentication_unavailable")
        self.assertIn("anisette", state["message"])
        self.assertNotIn("locked", state["message"])

    def test_unanswered_verification_is_cancelled_not_failed(self):
        token = guard.begin()
        state = guard.cancelled_2fa_timeout()
        self.assertEqual(state["code"], "2fa_timeout")
        self.assertEqual(state["reason"], "user_cancelled")
        self.assertTrue(state["blocked"])
        self.assertIn("60 seconds", state["message"])
        # Late shell errors must not replace a deliberate cancellation.
        guard.failed("AltServer terminated", 143, token)
        self.assertEqual(guard.status()["code"], "2fa_timeout")
        with self.assertRaises(RuntimeError):
            guard.begin()
        guard.resume()
        self.assertFalse(guard.status()["blocked"])

    def test_interrupt_requires_manual_resume(self):
        token = guard.begin()
        state = guard.failed("Terminated", 143, token)
        self.assertEqual(state["code"], "interrupted")
        self.assertTrue(state["blocked"])


if __name__ == "__main__":
    unittest.main()