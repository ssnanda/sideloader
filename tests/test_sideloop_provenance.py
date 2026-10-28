import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / 'overlay' / 'sideloop_info.py'
PATCH = ROOT / 'overlay' / 'patch-sideloop-version.py'
spec = importlib.util.spec_from_file_location('sideloop_provenance_test', MODULE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class SideloopVersionTests(unittest.TestCase):
    def test_invalid_manifest_fails_closed(self):
        with tempfile.TemporaryDirectory() as t:
            m=Path(t)/'sideloop-build.json'
            self.assertEqual(module.status(m)['status'], 'unknown')
            m.write_text('{broken')
            self.assertEqual(module.status(m)['status'], 'unknown')
            m.write_text(json.dumps({'repository':'filippofinke/sideloop','upstream_revision':'x'*40,'sideloader_version':'0.1.0'}))
            self.assertEqual(module.status(m)['status'],'unknown')

    def test_valid_manifest_identified_and_overlaid(self):
        with tempfile.TemporaryDirectory() as t:
            m=Path(t)/'sideloop-build.json'
            m.write_text(json.dumps({'repository':'filippofinke/sideloop','upstream_revision':'a'*40,'sideloader_version':'0.2.0+16','prepared_at':'2026-10-28T11:20:00Z'}))
            info=module.status(m)
            self.assertEqual(info['status'],'identified')
            self.assertTrue(info['modified'])
            self.assertEqual(info['revision'],'a'*40)
            self.assertEqual(info['side_loader_version'],'0.2.0+16')

    def test_patcher_succeeds_on_existing_checkout_and_repeated_runs(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)
            pkg=root/'sideloop';pkg.mkdir()
            (pkg/'server.py').write_text('''from .backend_info import status as altserver_status, check_updates as altserver_updates
class App:
    def state(self):
        return {
            "altserver_build": altserver_status(),
        }
''')
            (pkg/'index.html').write_text('''<script>
function altserverBackendCard() { return 'altserver'; }
function settingsView() { return `
  ${altserverBackendCard()}
  <div class="setup-heading">SETTINGS · OPTIONAL</div>`; }
</script>''')
            ver=root/'VERSION';ver.write_text('0.2.0+16\n')
            subprocess.run(['git','init','-q',t],check=True)
            subprocess.run(['git','-C',t,'-c','user.name=Tester','-c','user.email=dev@example.com','commit','--allow-empty','-qm','baseline'],check=True)
            cmd=[sys.executable,str(PATCH),t,str(ROOT/'overlay'),str(ver)]
            subprocess.run(cmd,check=True,capture_output=True,text=True)
            s=(pkg/'server.py').read_text(); h=(pkg/'index.html').read_text()
            self.assertIn('"sideloop_build": sideloop_status()',s)
            self.assertIn('sideloopCoreCard()',h)
            self.assertIn('filippofinke/sideloop',h)
            self.assertIn('SideLoader overlay version',h)
            result=module.status(pkg/'sideloop-build.json')
            self.assertEqual(result['side_loader_version'],'0.2.0+16')
            self.assertEqual(result['status'],'identified')
            subprocess.run(cmd,check=True,capture_output=True,text=True)
            self.assertEqual((pkg/'server.py').read_text(),s)
            self.assertEqual((pkg/'index.html').read_text(),h)
            self.assertEqual((pkg/'sideloop-build.json').read_text().count('upstream_revision'),1)

if __name__ == '__main__': unittest.main()