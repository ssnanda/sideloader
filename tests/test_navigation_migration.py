"""Regression: rebuilding v0.2.0+13+ never re-applies old Step 1 labels."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / 'overlay' / 'patch-navigation.py'
OVERLAY = ROOT / 'overlay'
from test_navigation_patch import INDEX


class MigrationTests(unittest.TestCase):
    def patch(self, temp):
        result = subprocess.run([sys.executable, str(PATCH), temp, str(OVERLAY)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_patched_four_stage_dashboard_is_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            package = Path(temp) / 'sideloop'
            package.mkdir()
            page = package / 'index.html'
            page.write_text(INDEX)
            self.patch(temp)
            original = page.read_text()
            self.assertIn('setupDoneSnapshot[0] && !deviceDone', original)
            # Simulate installed workflow v0.2.0+13 and the device-health
            # overlay that replaced the static "Saved · Offline" subtitle.
            modern = original.replace(
                '  const completed = [deviceDone, appleDone, installedApp, c.auto_check];',
                '  /* SideLoader four-stage installation workflow v1 */\n'
                '  const completed = [deviceDone, appleDone, installedApp, c.auto_check];')
            modern = modern.replace(
                '  const deviceDone = devs.length > 0 && onlineDevice;',
                '  const connectionLabel = "Connected";\n'
                '  const deviceDone = devs.length > 0 && onlineDevice;')
            modern = modern.replace('"Saved · Offline — reconnect to continue"', 'connectionLabel')
            page.write_text(modern)
            for _ in range(2):
                self.patch(temp)
                self.assertEqual(page.read_text(), modern)
                self.assertEqual(modern.count('id="sideloader-diag-panel"'), 1)

    def test_old_static_layout_migrates_without_deleting_pairing(self):
        with tempfile.TemporaryDirectory() as temp:
            package = Path(temp) / 'sideloop'
            package.mkdir()
            page = package / 'index.html'
            page.write_text(INDEX)
            self.patch(temp)
            expected = page.read_text()
            previous = expected.replace(
                '  const deviceDone = devs.length > 0 && onlineDevice;',
                '  const deviceDone = devs.length > 0;', 1).replace(
                '    // A connected phone going offline returns the wizard to Step 1.\n'
                '    if (setupDoneSnapshot[0] && !deviceDone) setupChoice = null;\n',
                '', 1).replace(
                'Saved · Offline — reconnect to continue', 'Saved · Offline', 1)
            self.assertNotEqual(previous, expected)
            page.write_text(previous)
            self.patch(temp)
            self.assertEqual(page.read_text(), expected)
            self.patch(temp)
            self.assertEqual(page.read_text(), expected)

if __name__ == '__main__':
    unittest.main()