"""Offline regression coverage for source-driven iPhone IPA reinstallation."""
import hashlib
import importlib.util
import io
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PKG = "sideloader_reinstall_test"
pkg = types.ModuleType(PKG)
pkg.__path__ = []
config = types.ModuleType(PKG + ".config")
ipa = types.ModuleType(PKG + ".ipa")
store = types.ModuleType(PKG + ".store")
github_sources = types.ModuleType(PKG + ".github_sources")
github_scan = types.ModuleType(PKG + ".github_scan")
inventory = types.ModuleType(PKG + ".device_app_inventory")
sys.modules.update({
    PKG: pkg, PKG + ".config": config, PKG + ".ipa": ipa,
    PKG + ".store": store, PKG + ".github_sources": github_sources,
    PKG + ".github_scan": github_scan,
    PKG + ".device_app_inventory": inventory,
})
spec = importlib.util.spec_from_file_location(PKG + ".sources", ROOT / "overlay" / "sources.py")
sources = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = sources
spec.loader.exec_module(sources)

UDID = "123456789012345678901234"
SOURCE_URL = "https://example.com/altstore.json"
SOURCE_ID = hashlib.sha256(SOURCE_URL.encode()).hexdigest()[:16]
BUNDLE = "com.example.iphoneapp"


class IPAResponse(io.BytesIO):
    def __init__(self, content):
        super().__init__(content)
        self.headers = {"Content-Length": str(len(content))}


class ReinstallLatestTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        config.DATA = Path(directory.name)
        config.APPS = config.DATA / "apps"
        self.saved = config.APPS / BUNDLE
        self.saved.mkdir(parents=True)
        (self.saved / "app.ipa").write_bytes(b"original-ipa")
        item = {
            "bundleIdentifier": BUNDLE, "name": "Test App",
            "version": "1.0", "buildVersion": "1",
            "downloadURL": "https://example.com/releases/latest/app.ipa",
        }
        patches = [
            patch.object(sources.Sources, "_urls", return_value=[SOURCE_URL]),
            patch.object(sources, "_catalog", return_value={"apps": [item]}),
            patch.object(sources, "_open", side_effect=lambda url: IPAResponse(b"fresh-ipa")),
            patch.object(store, "app_ids", create=True, return_value=[BUNDLE]),
            patch.object(store, "resolve_device", create=True,
                         side_effect=lambda val: UDID if val == UDID else None),
            patch.object(store, "app_view", create=True,
                         return_value={"bundle_id": BUNDLE, "version": "1.0"}),
            patch.object(inventory, "inventory", create=True,
                         return_value=[{"bundle_id": BUNDLE + ".AB12CD34EF",
                                        "version": "1.0", "build": "1"}]),
            patch.object(ipa, "inspect", create=True,
                         return_value={"bundle_id": BUNDLE, "name": "Test App",
                                       "version": "1.0", "build": "1"}),
        ]
        for mocked in patches:
            mocked.start()
            self.addCleanup(mocked.stop)

        def import_app(path, inspected, filename):
            self.assertEqual(inspected["bundle_id"], BUNDLE)
            os.replace(path, self.saved / "app.ipa")
            return BUNDLE

        add = patch.object(store, "add_app", create=True, side_effect=import_app)
        add.start()
        self.addCleanup(add.stop)
        self.app = types.SimpleNamespace(
            idle=lambda: None,
            state=lambda: {"configured": True},
            refresh=lambda data: self.fail("Import must not start an Apple sign-in"),
        )
        self.request = {
            "source": SOURCE_ID, "bundleIdentifier": BUNDLE, "device": UDID,
            "reinstall_latest": True, "install_now": False,
        }

    def test_same_version_reinstalls_latest_source_and_backs_up_saved_ipa(self):
        result = sources.Sources().install(self.request, self.app)
        self.assertEqual(result["app_id"], BUNDLE)
        self.assertEqual(result["version"], "1.0")
        self.assertEqual((self.saved / "app.ipa").read_bytes(), b"fresh-ipa")
        self.assertEqual((self.saved / "previous.ipa").read_bytes(), b"original-ipa")
        self.assertEqual(result["refresh"], "not started")

    def test_removed_iphone_app_must_not_be_reinstalled(self):
        with patch.object(inventory, "inventory", return_value=[]):
            with self.assertRaisesRegex(ValueError, "no longer installed"):
                sources.Sources().install(self.request, self.app)
        self.assertEqual((self.saved / "app.ipa").read_bytes(), b"original-ipa")

    def test_mismatched_download_bundle_must_never_replace_saved_ipa(self):
        with patch.object(ipa, "inspect", return_value={
            "bundle_id": "com.example.unknown", "version": "2.0", "build": "3",
        }):
            with self.assertRaisesRegex(ValueError, "differs from source listing"):
                sources.Sources().install(self.request, self.app)
        self.assertEqual((self.saved / "app.ipa").read_bytes(), b"original-ipa")

    def test_latest_feed_selects_newest_when_versions_are_unsorted(self):
        app = {"bundleIdentifier": BUNDLE, "versions": [
            {"version": "1.2", "buildVersion": "2", "downloadURL": "v12.ipa"},
            {"version": "1.11", "buildVersion": "1", "downloadURL": "v111.ipa"},
            {"version": "1.11", "buildVersion": "3", "downloadURL": "v111-3.ipa"},
        ]}
        latest = sources._latest(app, SOURCE_URL)
        self.assertEqual(latest["version"], "1.11")
        self.assertEqual(latest["buildVersion"], "3")
        self.assertTrue(latest["downloadURL"].endswith("v111-3.ipa"))


if __name__ == "__main__":
    unittest.main()
