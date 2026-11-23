"""Offline regression checks for the optional VPN remote-pairing adapter."""
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PKG = "sideloader_remote_testing"
pkg = types.ModuleType(PKG)
pkg.__path__ = []
sys.modules[PKG] = pkg
spec = importlib.util.spec_from_file_location(PKG + ".remote_altkeeper", ROOT / "overlay" / "remote_altkeeper.py")
remote = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = remote
spec.loader.exec_module(remote)
loader = importlib.util.spec_from_file_location("remote_server_patch_testing", ROOT / "overlay" / "remote_server_patch.py")
installer = importlib.util.module_from_spec(loader)
loader.loader.exec_module(installer)


class RemoteTests(unittest.TestCase):
    def test_opt_in_is_disabled_by_default(self):
        with patch.dict(os.environ, {"SIDELOADER_REMOTE_ALTKEEPER_URL": ""}):
            self.assertFalse(remote.enabled())
            self.assertEqual(remote.summary(), {"enabled": False})

    def test_loopback_only(self):
        for url in ("http://example.com:8787", "https://127.0.0.1:8787",
                    "http://127.0.0.1:8787/unexpected"):
            with self.subTest(url=url):
                with patch.dict(os.environ, {"SIDELOADER_REMOTE_ALTKEEPER_URL": url}):
                    with self.assertRaises(ValueError):
                        remote._endpoint()

    def test_remote_profiles_do_not_claim_installed_apps(self):
        info = {"pairing": True, "phone": {"reachable": True, "checked_at": 1},
                "account": {"present": True, "password_saved": True, "team": True},
                "apps": [{"bundle": "com.example.app.AB12CD34EF"}]}
        with patch.dict(os.environ, {"SIDELOADER_REMOTE_ALTKEEPER_URL": "http://127.0.0.1:8787"}):
            with patch.object(remote, "state", return_value=info):
                result = remote.summary()
                self.assertFalse(result["reachable"])
                self.assertFalse(result["installation_verified"])
                self.assertEqual(result["profiles"][0]["bundle"], "com.example.app.AB12CD34EF")
        self.assertTrue(remote._profile_match("com.example.app.AB12CD34EF", "com.example.app"))
        self.assertFalse(remote._profile_match("com.other.app.AB12CD34EF", "com.example.app"))

    def test_source_contains_explicit_per_app_remote_controls(self):
        ui = (ROOT / "overlay" / "apps-dashboard-ui.js").read_text()
        wire = (ROOT / "overlay" / "apps-dashboard-wire.js").read_text()
        self.assertIn("data-remote-resign", ui)
        self.assertIn("data-remote-latest", ui)
        self.assertIn("data-remote-reinstall", ui)
        self.assertIn("/api/remote/status", wire)
        self.assertIn("installation not independently confirmed", ui)

    def test_remote_patch_attached_after_existing_2fa_patch(self):
        build = (ROOT / "overlay" / "patch-top-navigation.py").read_text()
        remote_patch = (ROOT / "overlay" / "remote_server_patch.py").read_text()
        self.assertIn("apply_remote_server(root, overlay)", build)
        self.assertIn("remote_altkeeper.renew_job", remote_patch)
        self.assertIn("remote_altkeeper.latest_job", remote_patch)
        self.assertIn("remote_altkeeper.install_job", remote_patch)
        self.assertIn("remote_altkeeper.verification_code", remote_patch)


if __name__ == "__main__":
    unittest.main()
