import subprocess, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / 'overlay' / 'patch-navigation.py'
OVERLAY = ROOT / 'overlay'
# A tightly focused fixture preserving the exact upstream patch anchors and
# the four settings sections. It exercises first patch + repeat patch behavior.
INDEX = r'''<!doctype html><html><head><style>body{margin:0}</style></head><body>
<div id="root"></div>
<script>
"use strict";
const VIEWS = ["apps", "settings", "activity"];
let S = {configured:false}, view = "apps";
if (!S.configured) view = "settings";
const TITLES = {apps:"Apps", settings:"Settings", activity:"Activity"};
const TABS = [["apps", "Apps", "apps"], ["settings", "Settings", "settings"], ["activity", "Activity", "list"]];
const ic=(x,y)=>"icon";
const esc=x=>x;
const tile=(a,b)=>"";
const sw=(a,b)=>"";
function render(){let html = `<div>${view === "apps" ? appsView() : view === "settings" ? settingsView() : activityView()}</div><nav>${TABS.map(([k, l, icon]) =>
    `<button data-view="${k}" aria-current="${view===k}">${ic(view === k ? icon : icon + "-outline", 26)}<span>${l}</span></button>`).join("")}</nav>`;}
function appsView(){
  const apps=[],devs=[],c={},auto={};
  if (!S.configured) return `<div class="list"><div class="empty">${ic("phone-portrait-outline", 44)}<b>Not Set Up Yet</b>
    Add a device, an app and your Apple ID.<div style="margin-top:18px"><button class="cap solid" data-go="settings">Open Settings</button></div></div></div>`;
  let issues=[];
  if (!S.services.anisette || !S.services.muxer) issues.push(["bad", "Service down"]);
  const autoCard='';
  return `${autoCard}${issues.map(x=>x).join(',')}
  <button data-go="settings">Add App or Device</button>
  <div class="sect">
    <div class="list"><div class="cell">${tile("var(--green)", "flash")}<span class="k">Re-sign Automatically</span>${sw("auto", c.auto_check)}</div></div>
    <div class="foot">Checks each device when it connects and re-signs ${c.renew_before_days} day${c.renew_before_days > 1 ? "s" : ""} before an app expires.</div>
  </div>`;
}
function settingsView() {
  const c = S.config, apps = S.apps || [], canPair = S.mode === "builtin", devs = S.registered || [];
  const known = new Set(devs.map(d => d.udid.toLowerCase()));
  const visible = (S.devices || []).filter(d => !known.has(d.udid.toLowerCase()));
  const replacing = null;
  const appIds = apps.reduce((n, a) => n + 1, 0);
  const trash = () => '';
  return `
  <div class="sect">
    <div class="shead"><h3>Devices</h3></div>
    <div class="list">
       <div class="cell">Device actions</div>
    </div>
  </div>

  <div class="sect">
    <div class="shead"><h3>Apps</h3></div>
    <div class="list">
       <div class="cell">App actions</div>
    </div>
  </div>

  <div class="sect">
    <div class="shead"><h3>Apple ID</h3></div>
    <form id="aidf"><div class="list">Sign in</div></form>
  </div>

  <div class="sect">
    <div class="shead"><h3>Re-signing</h3></div>
    <div class="list">Automatic</div>
  </div>`;
}
function ipaWarnings() {}
function activityView() {
  return `<div class="sect">
    <div class="shead"><h3>History</h3><button class="linkbtn" id="reload">${ic("refresh", 15)}Reload</button></div>
    <div class="list"><pre class="logs" id="logs">Loading…</pre></div></div>`;
}
function go(v){}
function wire() {
  root.querySelectorAll("[data-go]").forEach(b => b.onclick = () => go(b.dataset.go));
}
</script>
<a id="minisideload-link" href="/sources" style="position:fixed">Sources</a>
<!-- SideLoader: optional diagnostics; no dependencies -->
<div id="sideloader-diagnostics-controls">Old button</div><script>var oldControls=1;</script>
</body></html>'''

class NavigationTests(unittest.TestCase):
  def test_patch_is_repeatable_and_mobile_responsive(self):
    with tempfile.TemporaryDirectory() as temp:
      package=Path(temp)/'sideloop'
      package.mkdir()
      page=package/'index.html'
      page.write_text(INDEX)
      args=[sys.executable,str(PATCH),temp,str(OVERLAY)]
      subprocess.run(args,check=True,capture_output=True,text=True)
      out=page.read_text()
      self.assertIn('Step ${n}',out)
      self.assertIn('class="tab-link"',out)
      self.assertIn('data-step="${n}"',out)
      self.assertIn('max-width:540px',out)
      self.assertIn('env(safe-area-inset-bottom)',out)
      self.assertIn('id="sideloader-copy-diagnostics"',out)
      self.assertNotIn('minisideload-link',out)
      self.assertNotIn('sideloader-diagnostics-controls',out)
      self.assertIn('copy.isConnected',out)
      self.assertIn('const deviceDone = devs.length > 0 && onlineDevice;', out)
      self.assertIn('setupDoneSnapshot[0] && !deviceDone', out)
      self.assertIn('Saved · Offline — reconnect to continue', out)
      # Check the injected browser-side JavaScript parses.
      from html.parser import HTMLParser
      class Scripts(HTMLParser):
        def __init__(self):
          super().__init__(); self.active=False; self.code=[]; self.scripts=[]
        def handle_starttag(self,t,a):
          if t=='script':self.active=True;self.code=[]
        def handle_data(self,d):
          if self.active:self.code.append(d)
        def handle_endtag(self,t):
          if t=='script': self.scripts.append(''.join(self.code)); self.active=False
      parsed=Scripts(); parsed.feed(out)
      for script in parsed.scripts:
        result=subprocess.run(['node','--check'],input=script,text=True,capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr)
      subprocess.run(args,check=True,capture_output=True,text=True)
      self.assertEqual(out,page.read_text(),'Second patch must be idempotent')

  def test_existing_dashboard_upgrades_offline_status_without_replacing_wizard(self):
    # Simulate an already-patched installation from the previous release.
    with tempfile.TemporaryDirectory() as temp:
      package=Path(temp)/'sideloop'
      package.mkdir()
      page=package/'index.html'
      page.write_text(INDEX)
      args=[sys.executable,str(PATCH),temp,str(OVERLAY)]
      subprocess.run(args,check=True,capture_output=True,text=True)
      expected=page.read_text()
      previous=expected.replace(
        '  const deviceDone = devs.length > 0 && onlineDevice;',
        '  const deviceDone = devs.length > 0;',1).replace(
        '    // A connected phone going offline returns the wizard to Step 1.\n'
        '    if (setupDoneSnapshot[0] && !deviceDone) setupChoice = null;\n',
        '',1).replace(
        'Saved · Offline — reconnect to continue', 'Saved · Offline',1)
      self.assertNotEqual(previous,expected)
      page.write_text(previous)
      subprocess.run(args,check=True,capture_output=True,text=True)
      self.assertEqual(page.read_text(), expected)
      subprocess.run(args,check=True,capture_output=True,text=True)
      self.assertEqual(page.read_text(), expected)

if __name__=='__main__':unittest.main()