import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PATCH = ROOT/'overlay'/'patch-apps-dashboard.py'
SERVER = '''from . import log_maintenance
class App:
    def signing_resume(self, data):
        return {}
    def routes(self):
        return {
            "/api/logs/clear": self.clear_activity_logs,
        }
class Handler:
    def do_GET(self):
        if not self.authed():
            return self.error(401, "sign in first")
            if path == "/api/logs":
                return self.send(200, app.logs())
'''
PAGE = '''<html><head><style>body{color:blue}</style></head><body><script>
const setupChoice = null;
function sideloopCoreCard(){return 'core';}
function altserverBackendCard(){return 'backend';}
function settingsView() {
  const completed = [deviceDone, appleDone, appReady, everyAppInstalled];
  const ready = [deviceDone, accountReady, appReady, everyAppInstalled];
  const preferredStep = !deviceDone ? 1 : !accountReady ? 2 : !appReady ? 3 : !everyAppInstalled ? 4 : 0;
  const expanded = setupChoice === null ? preferredStep : setupChoice;
  return `
    ${renderSetupStep(1, "Connect your iPhone", devs.length ? `${esc(devs[0].name)} · ${connectionLabel} · Last checked ${checkedTime}` : `Connect or scan for a device · Last checked ${checkedTime}`, deviceDone, `<p>device</p>`, expanded)}
    ${renderSetupStep(2, "Apple Account", appleDone ? `Verified by successful install · ${new Date(appleInfo.verified_at * 1000).toLocaleString()}` : c.apple_id && c.has_password ? (appleInfo.state === "failed" ? `Apple authentication failed (${appleInfo.code || "unknown"}) · retry paused` : "Credentials saved · Apple sign-in not yet verified") : "Enter account and password", appleDone, `<p>credentials</p>`, expanded)}
    ${renderSetupStep(3, "Add an IPA", appReady ? `${apps.length} IPA${apps.length === 1 ? "" : "s"} saved · continue to Step 4 to install` : "Import an IPA or browse Sources; no installation yet", appReady, `<div class="drop">Import IPA</div><div class="step-source">Browse sources</div>`, expanded)}
    ${renderSetupStep(4, "Install on iPhone",
      !appReady ? "Add an IPA in Step 3 first" : "Ready for manual installation",
      everyAppInstalled,
      `<div class="list"><button data-sign="${esc(a.id)}">Install</button>
      <button type="button" id="recheck">Check</button></div>`, expanded)}
  ${sideloopCoreCard()}
  ${altserverBackendCard()}
  `;
}
function wire() {
  const on = (name,event,fun)=>{};
  on("reload", "onclick", loadLogs);
}
</script></body></html>
'''

class DashboardPatchTests(unittest.TestCase):
    def setup(self, tmp):
        p = pathlib.Path(tmp)/'sideloop'
        p.mkdir()
        (p/'server.py').write_text(SERVER)
        (p/'index.html').write_text(PAGE)
        return p

    def run_patch(self, tmp):
        return subprocess.run([sys.executable,str(PATCH),tmp,str(ROOT/'overlay')], capture_output=True,text=True)

    def test_merges_ipa_and_install_into_one_apps_step(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=self.setup(tmp)
            a=self.run_patch(tmp)
            self.assertEqual(a.returncode,0,a.stderr+a.stdout)
            ui=(p/'index.html').read_text()
            self.assertIn('renderSetupStep(3, "Apps"',ui)
            self.assertNotIn('renderSetupStep(4, "Install on iPhone"',ui)
            self.assertIn('deviceAppsManager()',ui)
            self.assertIn('Import IPA',ui)
            self.assertIn('sideLoaderVersionStrip()',ui)
            self.assertNotIn('${sideloopCoreCard()}',ui)
            self.assertNotIn('${altserverBackendCard()}',ui)
            self.assertIn('sideloader-device-app-sync',ui)
            self.assertIn('id="sideloader-compact-altserver-check"',ui)
            self.assertNotIn('id="sideloader-altserver-updates"',ui)
            self.assertIn('const preferredStep = 3;',ui)
            self.assertIn('not([open])',ui)
            server=(p/'server.py').read_text()
            self.assertIn('"/api/device/apps/remove": self.remove_phone_apps',server)
            self.assertIn('"/api/device/apps":',server)
            self.assertIn('app.device({"device":',server)
            self.assertTrue((p/'device_app_inventory.py').exists())
            b=self.run_patch(tmp)
            self.assertEqual(b.returncode,0,b.stderr+b.stdout)
            self.assertEqual(ui,(p/'index.html').read_text())
            self.assertEqual(server,(p/'server.py').read_text())

    def test_fail_closed_on_unrecognized_step(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=self.setup(tmp)
            (p/'index.html').write_text(PAGE.replace('renderSetupStep(4, "Install on iPhone"', 'renderSetupStep(4, "Unknown"'))
            a=self.run_patch(tmp)
            self.assertNotEqual(a.returncode,0)
            self.assertEqual((p/'server.py').read_text(),SERVER)

    def test_frontend_helper_javascript_syntax(self):
        if subprocess.run(['which','node'],capture_output=True).returncode: self.skipTest('node missing')
        src=(ROOT/'overlay'/'apps-dashboard-ui.js').read_text()
        wire=(ROOT/'overlay'/'apps-dashboard-wire.js').read_text()
        full=src+'\nfunction wire(){const on=()=>{};\n'+wire+'\n}\n'
        out=subprocess.run(['node','--check'],input=full,text=True,capture_output=True)
        self.assertEqual(out.returncode,0,out.stderr)

if __name__=='__main__': unittest.main()