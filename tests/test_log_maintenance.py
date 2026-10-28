"""Safety and repeat-build tests for the Clear old logs action."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
PKG = "test_sideloader_clear_logs"
package = types.ModuleType(PKG)
package.__path__ = []
config = types.ModuleType(PKG + ".config")
sys.modules[PKG] = package
sys.modules[PKG + ".config"] = config
spec = importlib.util.spec_from_file_location(PKG + '.log_maintenance', ROOT / 'overlay' / 'log_maintenance.py')
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class Job:
    def __init__(self, lines, running=False):
        self.lock = threading.Lock()
        self.lines = list(lines)
        self.partial = 'old pending text'
        self.running = running
        self.rc = 1


class Jobs:
    def __init__(self):
        self.lock = threading.Lock()
        self.current = Job(['-36607', 'old sign-in log'])
        self.auto = Job(['old automatic sign-in log'])

    def busy(self):
        return self.current.running or self.auto.running


class App:
    def __init__(self):
        self.jobs = Jobs()

    def idle(self):
        if self.jobs.busy():
            raise RuntimeError('wait for the current run to finish')


class LogMaintenanceTest(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.data = Path(td.name)
        config.STATE = self.data / 'state'
        config.STATE.mkdir()
        self.app = App()
        self.log = config.STATE / 'refresh.log'
        self.log.write_text('older -20209\nrecent -36607\n')
        (config.STATE / 'sideloader-signing-block.json').write_text('{"blocked":true,"code":"-36607"}')
        (self.data / 'apps').mkdir()
        (self.data / 'apps' / 'app.ipa').write_bytes(b'IPA data')
        (self.data / 'devices').mkdir()
        (self.data / 'devices' / 'pairing.plist').write_text('pairing preserved')
        (self.data / 'config.env').write_text('APPLE_ID=account@example.com')

    def test_clear_saved_log_and_completed_job_history_only(self):
        result = module.clear_history(self.app)
        self.assertGreater(result['cleared_bytes'], 0)
        self.assertEqual(self.log.read_text(), '')
        self.assertEqual(self.app.jobs.current.lines, [])
        self.assertEqual(self.app.jobs.auto.lines, [])
        self.assertEqual(self.app.jobs.current.rc, 1)
        self.assertEqual((config.STATE/'sideloader-signing-block.json').read_text(),'{"blocked":true,"code":"-36607"}')
        self.assertEqual((self.data/'apps'/'app.ipa').read_bytes(), b'IPA data')
        self.assertEqual((self.data/'devices'/'pairing.plist').read_text(), 'pairing preserved')
        self.assertEqual((self.data/'config.env').read_text(), 'APPLE_ID=account@example.com')
        self.assertEqual(module.clear_history(self.app)['cleared_bytes'],0)

    def test_cannot_clear_a_running_manual_job(self):
        self.app.jobs.current.running = True
        with self.assertRaises(RuntimeError): module.clear_history(self.app)
        self.assertIn('-36607', self.log.read_text())
        self.assertEqual(self.app.jobs.current.lines[0], '-36607')

    def test_cannot_clear_a_running_automatic_job(self):
        self.app.jobs.auto.running = True
        with self.assertRaises(RuntimeError): module.clear_history(self.app)
        self.assertIn('-36607', self.log.read_text())

    def test_symlink_log_is_refused(self):
        self.log.unlink()
        target = self.data/'do-not-delete'
        target.write_text('important text')
        self.log.symlink_to(target)
        with self.assertRaises(ValueError): module.clear_history(self.app)
        self.assertEqual(target.read_text(), 'important text')
        self.assertTrue(self.log.is_symlink())

    def test_missing_log_file_is_safe(self):
        self.log.unlink()
        self.assertEqual(module.clear_history(self.app)['cleared_bytes'],0)
        self.assertTrue(self.log.exists())


class PatcherTest(unittest.TestCase):
    SERVER = '''from . import retry_guard
from .account import verification, save_account
class App:
    def signing_resume(self, data):
        pass
    def routes(self):
        return {
            "/api/signing/resume": self.signing_resume,
        }
'''
    HTML = '''<html><script>
function activityView(){ return `<div class="list"><button class="cell action" type="button" id="sideloader-copy-diagnostics">Copy Diagnostics</button><pre class="logs" id="logs">Loading…</pre></div>`; }
function wire() {
  on("reload", "onclick", loadLogs);
}
</script></html>'''

    def make_files(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        root = Path(td.name)
        pkg = root/'sideloop'
        pkg.mkdir()
        (pkg/'server.py').write_text(self.SERVER)
        (pkg/'index.html').write_text(self.HTML)
        return root, pkg

    def run_patch(self, root):
        return subprocess.run([sys.executable,str(ROOT/'overlay'/'patch-log-maintenance.py'),str(root),str(ROOT/'overlay')],capture_output=True,text=True)

    def test_install_idempotent_on_existing_checkout(self):
        root,pkg = self.make_files()
        r = self.run_patch(root)
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)
        s=(pkg/'server.py').read_text();h=(pkg/'index.html').read_text()
        self.assertIn('log_maintenance.clear_history(self)',s)
        self.assertEqual(s.count('"/api/logs/clear"'),1)
        self.assertEqual(h.count('id="sideloader-clear-logs"'),1)
        self.assertIn('acknowledge:true',h)
        self.assertIn('signing safety lock will NOT be deleted',h)
        again=self.run_patch(root)
        self.assertEqual(again.returncode,0,again.stdout+again.stderr)
        self.assertEqual((pkg/'server.py').read_text(),s)
        self.assertEqual((pkg/'index.html').read_text(),h)
        self.assertEqual((pkg/'log_maintenance.py').read_bytes(),(ROOT/'overlay'/'log_maintenance.py').read_bytes())
        js=h.split('<script>')[1].split('</script>')[0]
        result=subprocess.run(['node','--check'],input=js,text=True,capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_unknown_markup_fails_without_modifying_server(self):
        root,pkg=self.make_files()
        h=(pkg/'index.html')
        h.write_text(self.HTML.replace('id="sideloader-copy-diagnostics"','id="missing"'))
        before=(pkg/'server.py').read_text()
        result=self.run_patch(root)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('Activity delete button',result.stderr)
        self.assertEqual((pkg/'server.py').read_text(),before)
        self.assertFalse((pkg/'log_maintenance.py').exists())


if __name__=='__main__': unittest.main()