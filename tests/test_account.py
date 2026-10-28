"""Offline coverage for the SideLoader Remove Apple Account operation."""
import importlib.util
import pathlib
import sys
import tempfile
import types
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
NAME = "sideloader_account_test"
pkg = types.ModuleType(NAME)
pkg.__path__ = []
config = types.ModuleType(NAME + ".config")
sys.modules.update({NAME: pkg, NAME + ".config": config})
spec = importlib.util.spec_from_file_location(NAME + ".account", ROOT / "overlay" / "account.py")
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class AccountRemovalTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        config.DATA = pathlib.Path(temp.name)
        config.STATE = config.DATA / 'state'
        self.saved = {"APPLE_ID": "old@example.com", "APPLE_PASSWORD": "old-secret", "AUTO_CHECK": "1"}
        config.update = self.saved.update
        self.app = types.SimpleNamespace(idle=lambda: None)
        (config.DATA / "apps").mkdir()
        (config.DATA / "apps" / "app.ipa").write_bytes(b"IPA")
        (config.DATA / "devices").mkdir()
        (config.DATA / "devices" / "pairing.env").write_text("paired")

    def test_remove_preserves_ipa_pairing_and_disables_renewal(self):
        cache = config.DATA / "AltServerData"
        cache.mkdir()
        (cache / "certificate").write_text("stale")
        self.assertEqual(module.forget_account(self.app), {"ok": True})
        self.assertEqual(self.saved["APPLE_ID"], "")
        self.assertEqual(self.saved["APPLE_PASSWORD"], "")
        self.assertEqual(self.saved["AUTO_CHECK"], "0")
        self.assertFalse(cache.exists())
        self.assertTrue((config.DATA / "apps" / "app.ipa").exists())
        self.assertTrue((config.DATA / "devices" / "pairing.env").exists())
        self.assertEqual(module.forget_account(self.app), {"ok": True})

    def test_refuses_removal_while_job_is_running(self):
        cache = config.DATA / "AltServerData"
        cache.mkdir()
        self.app.idle = lambda: (_ for _ in ()).throw(RuntimeError("job running"))
        with self.assertRaises(RuntimeError):
            module.forget_account(self.app)
        self.assertEqual(self.saved["APPLE_ID"], "old@example.com")
        self.assertTrue(cache.exists())

    def test_refuses_symlinked_signing_cache(self):
        (config.DATA / "AltServerData").symlink_to(config.DATA / "apps", target_is_directory=True)
        with self.assertRaises(RuntimeError):
            module.forget_account(self.app)
        self.assertEqual(self.saved["APPLE_PASSWORD"], "old-secret")
        self.assertTrue((config.DATA / "apps" / "app.ipa").exists())

if __name__ == "__main__":
    unittest.main()
