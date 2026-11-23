"""Offline tests for AltStore feed handling and URL restrictions."""
import importlib.util
import pathlib
import sys
import types
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
pkg = types.ModuleType("mini_testing")
pkg.__path__ = []
config = types.ModuleType("mini_testing.config")
config.DATA = ROOT / "tests" / "_unused"
ipa = types.ModuleType("mini_testing.ipa")
store = types.ModuleType("mini_testing.store")
sys.modules.update({"mini_testing": pkg, "mini_testing.config": config, "mini_testing.ipa": ipa, "mini_testing.store": store})
mod_spec = importlib.util.spec_from_file_location("mini_testing.sources", ROOT / "overlay" / "sources.py")
mod = importlib.util.module_from_spec(mod_spec)
mod_spec.loader.exec_module(mod)


class SourceTests(unittest.TestCase):
    def test_sources_page_lists_saved_sources_before_collapsed_add_actions(self):
        page = (ROOT / 'overlay' / 'sources.html').read_text()
        self.assertLess(page.index('id="sources"'), page.index('id="show-add-source"'))
        self.assertIn('id="add-source-panel" class="source-panel" hidden', page)
        self.assertIn('id="github-discovery" class="source-panel" hidden', page)
        self.assertIn("togglePanel('add-source-panel')", page)
        self.assertIn("togglePanel('github-discovery')", page)
        self.assertIn("view.href='/#apps-add'", page)

    def test_imported_ipa_storage_is_not_limited_to_three(self):
        source = (ROOT / 'overlay' / 'sources.py').read_text()
        self.assertNotIn('three-app limit reached', source)
        self.assertNotIn('len(current_ids) >= 3', source)

    def test_classic_altstore(self):
        a = {"name": "Test", "bundleIdentifier": "com.example.app", "version": "1.0", "downloadURL": "../../my.ipa"}
        result = mod._latest(a, "https://example.com/feeds/catalog.json")
        self.assertEqual(result["downloadURL"], "https://example.com/my.ipa")
        self.assertEqual(result["version"], "1.0")

    def test_versioned_altstore(self):
        a = {"name": "Test", "bundleIdentifier": "com.example.app", "versions": [{"version": "2.0", "date": "2026-11-23", "downloadURL": "https://example.com/two.ipa"}]}
        latest = mod._latest(a, "https://example.com/list.json")
        self.assertEqual(latest["version"], "2.0")
        self.assertEqual(latest["date"], "2026-11-23")

    def test_invalid_scheme_rejected(self):
        for url in ["file:///etc/passwd", "ftp://example.com/file.json", "http://127.0.0.1/private", "https://user:pass@example.com/a.json"]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                mod._allowed(url)

    def test_bundle_required(self):
        self.assertIsNone(mod._latest({"name": "No ID", "downloadURL": "app.ipa"}, "https://example.com/source.json"))


if __name__ == "__main__":
    unittest.main()
