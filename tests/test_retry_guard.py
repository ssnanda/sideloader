"""Safety regression tests: Apple failures block signing until manual reset."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest

PKG = "sideloader_guard_under_test"
pkg = types.ModuleType(PKG)
pkg.__path__ = []
cfg = types.ModuleType(PKG + ".config")
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

    def test_locked_account_is_blocked_immediately_and_survives_reads(self):
        outcome = guard.failed("This Apple Account has been locked for security reasons. (-20209)")
        self.assertEqual(outcome["code"], "-20209")
        self.assertEqual(outcome["reason"], "account_locked")
        self.assertTrue(outcome["blocked"])
        with self.assertRaises(RuntimeError):
            guard.assert_allowed()
        self.assertEqual(guard.status()["code"], "-20209")
        contents = guard.FILE.read_text()
        self.assertNotIn("never-store", contents)
        self.assertNotIn("one@example.com", contents)

    def test_second_failed_attempt_is_not_recorded_as_a_new_retry(self):
        first = guard.failed("(-80046)")
        other = guard.failed("Another failure", 1)
        self.assertEqual(other["code"], "-80046")
        self.assertEqual(other["since"], first["since"])

    def test_unknown_error_refines_to_specific_pty_code(self):
        guard.failed("", 1)
        self.assertEqual(guard.status()["code"], "install_failed")
        guard.failed("Alert: Could not install app.ipa. (-80046)", 1)
        self.assertEqual(guard.status()["code"], "-80046")

    def test_manual_resume_allows_one_new_attempt(self):
        guard.failed("verification failed", 1)
        guard.resume()
        self.assertFalse(guard.status()["blocked"])
        guard.assert_allowed()
        guard.failed("timed out", 124)
        self.assertTrue(guard.status()["blocked"])
        self.assertEqual(guard.status()["code"], "timeout")

    def test_different_account_does_not_inherit_old_lock(self):
        guard.failed("(-20209)")
        self.state["APPLE_ID"] = "two@example.com"
        self.assertFalse(guard.status()["blocked"])
        guard.assert_allowed()
        guard.failed("(-80046)")
        self.assertEqual(guard.status()["code"], "-80046")
        self.state["APPLE_ID"] = "one@example.com"
        # The state file belongs to the second account, so no blocked retry
        # is attributed to this other Apple Account.
        self.assertFalse(guard.status()["blocked"])

    def test_corrupted_safety_state_is_fail_closed(self):
        guard.FILE.parent.mkdir(parents=True)
        guard.FILE.write_text("{corrupted")
        self.assertTrue(guard.status()["blocked"])
        self.assertEqual(guard.status()["code"], "guard_state_unreadable")
        with self.assertRaises(RuntimeError):
            guard.assert_allowed()
        guard.resume()
        self.assertFalse(guard.status()["blocked"])

    def test_36607_blocks_with_explanation_without_claiming_account_lock(self):
        result = guard.failed(
            "Unable to sign you in to your Apple Account. Try again later. (-36607)", 1)
        self.assertTrue(result["blocked"])
        self.assertEqual(result["code"], "-36607")
        self.assertEqual(result["reason"], "apple_authentication_unavailable")
        self.assertIn("anisette", result["message"])
        self.assertIn("Do not retry", result["action"])
        self.assertNotIn("locked", result["message"])
        with self.assertRaises(RuntimeError):
            guard.assert_allowed()

    def test_pty_36607_refines_generic_error_without_retry(self):
        guard.failed("", 1)
        updated = guard.failed("AltServer: Unable to sign you in to your Apple Account. Try again later. (-36607)", 1)
        self.assertEqual(updated["code"], "-36607")
        self.assertTrue(updated["blocked"])

    def test_explicit_code_action_for_80046(self):
        state = guard.failed("AltServer finished: (-80046)")
        self.assertIn("not established", state["message"])
        self.assertIn("Diagnostics", state["action"])

if __name__ == "__main__":
    unittest.main()
