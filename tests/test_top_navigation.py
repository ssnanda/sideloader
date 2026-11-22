"""Static coverage for Settings navigation and Roadmap delivery."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class TopNavigationTests(unittest.TestCase):
    def test_main_navigation_order_and_links(self):
        patch = (ROOT / "overlay" / "patch-top-navigation.py").read_text()
        self.assertIn('sl-nav-version', patch)
        self.assertIn('<summary>Settings</summary>', patch)
        self.assertIn('<a href="/sources">Sources</a><a href="/roadmap">Roadmap</a>', patch)
        self.assertLess(patch.index('sl-nav-version'), patch.index('sl-settings-menu'))
        self.assertLess(patch.index('sl-settings-menu'), patch.index('id="signout"'))

    def test_roadmap_is_authenticated(self):
        patch = (ROOT / "overlay" / "patch-top-navigation.py").read_text()
        self.assertIn('if path == "/roadmap":', patch)
        self.assertIn('if not self.authed():', patch)
        self.assertTrue((ROOT / "overlay" / "roadmap.html").is_file())
        self.assertTrue((ROOT / "docs" / "roadmap" / "remote-access-resigning-auto-update.md").is_file())

    def test_sources_is_only_in_settings_navigation(self):
        sources = (ROOT / "overlay" / "sources.html").read_text()
        self.assertIn('class="top-settings"', sources)
        self.assertNotIn('<nav class="sources-tabs"', sources)


if __name__ == "__main__":
    unittest.main()
