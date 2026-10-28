import importlib.util
import pathlib
import sys
import types
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
pkg = types.ModuleType('diag_test')
pkg.__path__ = []
config = types.ModuleType('diag_test.config')
store = types.ModuleType('diag_test.store')
installed = types.ModuleType('diag_test.installed')
installed.enrich_apps = lambda apps, live: apps
sys.modules.update({'diag_test': pkg, 'diag_test.config': config, 'diag_test.store': store, 'diag_test.installed': installed})
path = ROOT / 'overlay' / 'diagnostics.py'
spec = importlib.util.spec_from_file_location('diag_test.diagnostics', path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class DiagnosticTests(unittest.TestCase):
    def test_sensitive_output_filtered(self):
        self.assertEqual(mod.scrub('879689'), '[sensitive signing output omitted]')
        self.assertEqual(mod.scrub('Authorization: Bearer abc'), '[sensitive signing output omitted]')
        out = mod.scrub('user@example.org device 00008160-00052C6E1821400A at 192.168.1.4', ('secret-password',))
        self.assertNotIn('user@example.org', out)
        self.assertNotIn('00008160-00052C6E1821400A', out)
        self.assertNotIn('192.168.1.4', out)
        self.assertIn('[DEVICE_ID]', out)

    def test_error_preserved(self):
        self.assertIn('-80046', mod.scrub('Alert: This action cannot be completed (-80046)'))


if __name__ == '__main__':
    unittest.main()
