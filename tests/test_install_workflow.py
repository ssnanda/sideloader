import tempfile, pathlib, subprocess, sys, unittest
SCRIPT=pathlib.Path(__file__).resolve().parents[1] / 'overlay' / 'patch-install-workflow.py'
PRE='''const renderSetupStep=(n,title,subtitle,done,body,expanded)=>`<section>${body}</section>`;
function appsView() {
  const apps = S.apps || [], devs = S.registered || [], c = S.config, auto = S.watcher.job;
  const section = d => `<div>old install row</div>`;
  const targets = 1;
  const issues = [];
  const autoCard = '';
  return `${settingsView()}${autoCard}${issues.map(x=>x).join("")}
  ${devs.map(section).join("")}
  <div class="sect">
    <div class="list">
      ${targets > 1 ? `<button id="signall">All</button>` : ""}
      <button class="cell action" id="recheck">Check Everything</button>
      <button data-go="settings">Add App or Device</button>
    </div>
  </div>`;
}
const STEPS = [];
function settingsView() {
  const c=S.config, apps=S.apps||[], canPair = false, devs=S.registered||[];
  const onlineDevice = devs.some(d => d.live && d.live.reachable);
  const installedApp = apps.some(a => (a.targets || []).some(t => t.installation && t.installation.state === "installed"));
  const checkedAt = Number(S.last_checked || 0);
  const recentCheck = true;
  const deviceDone = devs.length > 0 && onlineDevice;
  const appleInfo = S.account_verification || {};
  const appleDone = Boolean(c.apple_id && c.has_password && appleInfo.state === "verified");
  const completed = [deviceDone, appleDone, installedApp, c.auto_check];
  if (setupDoneSnapshot) {
    if (setupDoneSnapshot[0] && !deviceDone) setupChoice = null;
    for (let i = 0; i < completed.length; i++) {
      if (!setupDoneSnapshot[i] && completed[i] && setupChoice === i + 1) setupChoice = null;
    }
  }
  setupDoneSnapshot = completed;
  const preferredStep = !deviceDone ? 1 : !appleDone ? 2 : !installedApp ? 3 : 0;
  const expanded = setupChoice === null ? preferredStep : setupChoice;
  return `
  ${renderSetupStep(1, "Connect your iPhone", "Connected", deviceDone, `<div>device</div>`, expanded)}
  ${renderSetupStep(2, "Apple Account", appleDone ? `Verified by successful install · ${new Date(appleInfo.verified_at * 1000).toLocaleString()}` : c.apple_id && c.has_password ? (appleInfo.state === "failed" ? `Apple authentication failed (${appleInfo.code || "unknown"}) · retry paused` : "Credentials saved · Apple sign-in not yet verified") : "Enter account and password", appleDone, `<div>account</div>`, expanded)}
  ${renderSetupStep(3, "Add and install an app", installedApp ? "Installed on iPhone" : apps.length ? `${apps.length} IPA saved · installation pending` : "Choose a source or IPA", installedApp, `<div>IPA upload</div><div><a href="/sources">Browse AltStore Sources</a></div>`, expanded)}
  ${renderSetupStep(4, "Automatic renewal", c.auto_check ? "Renewal enabled · success not yet verified" : "Automatic renewal disabled", c.auto_check, `    <div class="list">
      <div class="cell ind">${sw("auto2", c.auto_check)}</div>
      <select class="fi" id="rb">${[1,2,3].map(d => `<option value="${d}">${d} days</option>`).join("")}</select>
    </div>
`, expanded)}
  `;
}
function ipaWarnings() {}
'''
class T(unittest.TestCase):
 def test_install_step_and_idempotence(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=pathlib.Path(tmp)/'sideloop';p.mkdir();f=p/'index.html';f.write_text(PRE)
   cmd=[sys.executable,str(SCRIPT),tmp]
   r=subprocess.run(cmd,capture_output=True,text=True);self.assertEqual(r.returncode,0,r.stdout+r.stderr)
   s=f.read_text()
   self.assertIn('renderSetupStep(4, "Install on iPhone"',s)
   self.assertIn('renderSetupStep(3, "Add an IPA"',s)
   self.assertNotIn('renderSetupStep(4, "Automatic renewal"',s)
   self.assertIn('SETTINGS · OPTIONAL',s)
   self.assertIn('sw("auto2", c.auto_check)',s)
   self.assertNotIn('devs.map(section).join("")',s)
   self.assertEqual(s.count('id="recheck"'),1)
   self.assertIn('const ready = [deviceDone, accountReady, appReady, everyAppInstalled]',s)
   self.assertIn('data-sign="${esc(a.id)}"',s)
   r=subprocess.run(cmd,capture_output=True,text=True);self.assertEqual(r.returncode,0,r.stdout+r.stderr)
   self.assertEqual(s,f.read_text())
   js=subprocess.run(['node','--check'],input='"use strict";\n'+s,capture_output=True,text=True)
   self.assertEqual(js.returncode,0,js.stderr)
 def test_fails_closed_on_unknown_dashboard(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=pathlib.Path(tmp)/'sideloop';p.mkdir();(p/'index.html').write_text('unknown')
   r=subprocess.run([sys.executable,str(SCRIPT),tmp],capture_output=True,text=True)
   self.assertNotEqual(r.returncode,0)
if __name__=='__main__':unittest.main()