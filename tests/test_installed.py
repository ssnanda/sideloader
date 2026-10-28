"""Offline installed-inventory tests: stale profile is not an installation."""
import importlib.util
import plistlib
import subprocess
import unittest
from pathlib import Path
from unittest import mock

MOD = Path(__file__).resolve().parents[1] / 'overlay' / 'installed.py'
SPEC = importlib.util.spec_from_file_location('installed', MOD)
installed = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(installed)
DEVICE = '00008160-00052C6E1821400A'
BUNDLE = 'com.example.taptether'


class InventoryTests(unittest.TestCase):
    def setUp(self):
        installed._cache.clear()

    def test_installed(self):
        inventory = plistlib.dumps([{'CFBundleIdentifier': BUNDLE}])
        with mock.patch.object(installed, '_connection_modes', return_value=[True]), mock.patch.object(installed, '_run', return_value=subprocess.CompletedProcess([], 0, inventory, b'')):
            self.assertEqual(installed.probe(DEVICE, BUNDLE)['state'], 'installed')

    def test_missing(self):
        inventory = plistlib.dumps([{'CFBundleIdentifier': 'com.other.app'}])
        with mock.patch.object(installed, '_connection_modes', return_value=[False]), mock.patch.object(installed, '_run', return_value=subprocess.CompletedProcess([], 0, inventory, b'')):
            self.assertEqual(installed.probe(DEVICE, BUNDLE)['state'], 'missing')

    def test_failed_query_is_unknown_not_missing(self):
        with mock.patch.object(installed, '_connection_modes', return_value=[False, True]), mock.patch.object(installed, '_run', side_effect=OSError('offline')):
            self.assertEqual(installed.probe(DEVICE, BUNDLE)['state'], 'unknown')

    def test_offline_not_assumed_installed(self):
        apps = [{'bundle_id': BUNDLE, 'targets': [{'udid': DEVICE}]}]
        self.assertEqual(installed.enrich_apps(apps, {})[0]['targets'][0]['installation']['state'], 'offline')


if __name__ == '__main__':
    unittest.main()
