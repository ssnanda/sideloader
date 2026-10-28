#!/usr/bin/env python3
"""Make the dashboard a three-tab UI with an auto-collapsing setup wizard.

This applies *after* patch-upstream.py and patch-v2.py, and intentionally
removes any legacy floating Sources shortcut on every subsequent build.
"""
from pathlib import Path
import re
import sys

if len(sys.argv) != 3:
    sys.exit('Usage: patch-navigation.py <sideloop-checkout> <overlay-dir>')
index = Path(sys.argv[1]) / 'sideloop' / 'index.html'
overlays = Path(sys.argv[2])
source = index.read_text()

# Retire both earlier floating controls. The diagnostics action is embedded in
# Activity and its event is delegated (Activity is rerendered on polling).
source = re.sub(r'<a id="minisideload-link"[^>]*>Sources</a>\s*', '', source)
old_diag = source.find('<!-- SideLoader: optional diagnostics; no dependencies -->')
if old_diag != -1:
    diag_end = source.find('</script>', old_diag)
    if diag_end == -1:
        sys.exit('Cannot safely replace old diagnostic controls')
    source = source[:old_diag].rstrip() + '\n' + source[diag_end + len('</script>'):].lstrip()


def save():
    if source.count('</body>') != 1:
        sys.exit('Cannot safely insert diagnostics')
    widget = (overlays / 'diagnostics-ui.html').read_text()
    index.write_text(source.replace('</body>', widget + '\n</body>', 1))


MARKER = '/* SideLoader streamlined navigation and setup steps */'


def upgrade_offline_step():
    """Update existing patched dashboards too; never clear saved device pairing."""
    global source
    changes = (
        ('  const deviceDone = devs.length > 0;',
         '  const deviceDone = devs.length > 0 && onlineDevice;'),
        ('  if (setupDoneSnapshot) {\\n    for (let i = 0;',
         '  if (setupDoneSnapshot) {\\n'
         '    // A connected phone going offline returns the wizard to Step 1.\\n'
         '    if (setupDoneSnapshot[0] && !deviceDone) setupChoice = null;\\n'
         '    for (let i = 0;'),
        ('"Saved · Offline"', '"Saved · Offline — reconnect to continue"'),
    )
    for before, after in changes:
        if after in source:
            continue
        if source.count(before) != 1:
            sys.exit('Cannot safely upgrade offline Step 1: missing or ambiguous wizard anchor')
        source = source.replace(before, after, 1)


if MARKER in source:
    upgrade_offline_step()
    save()
    print('SideLoader navigation already installed; offline Step 1 updated.')
    sys.exit(0)


def replace(old, new, label):
    global source
    count = source.count(old)
    if count != 1:
        sys.exit(f'Cannot safely patch SideLoader {label}: expected 1 match, found {count}')
    source = source.replace(old, new, 1)


# Keep the existing three-slot navigation, replacing Settings with Sources.
replace('const VIEWS = ["apps", "settings", "activity"];',
        'const VIEWS = ["apps", "activity"];', 'view names')
replace('if (!S.configured) view = "settings";',
        'if (!S.configured) view = "apps";', 'first-launch view')
replace('const TITLES = {apps:"Apps", settings:"Settings", activity:"Activity"};',
        'const TITLES = {apps:"Apps", activity:"Activity"};', 'titles')
replace('const TABS = [["apps", "Apps", "apps"], ["settings", "Settings", "settings"], ["activity", "Activity", "list"]];',
        '''const TABS = [["apps", "Apps", "apps"], ["sources", "Sources", "list"], ["activity", "Activity", "time-outline"]];
let setupChoice = null, setupDoneSnapshot = null;
function renderSetupStep(n, title, subtitle, done, body, active) {
  return `<details class="setup-step" data-step="${n}" ${active === n ? "open" : ""}>
    <summary><span class="step-number">${n}</span><span class="step-caption"><span class="step-label">Step ${n}</span><b>${title}</b><small>${subtitle}</small></span>
    <span class="step-state ${done ? "done" : ""}" aria-hidden="true">${done ? "✓" : active === n ? "−" : "+"}</span></summary>
    <div class="step-body">${body}</div></details>`;
}''', 'navigation and step helper')
replace('view === "apps" ? appsView() : view === "settings" ? settingsView() : activityView()',
        'view === "apps" ? appsView() : activityView()', 'render routing')
replace('''${TABS.map(([k, l, icon]) =>
    `<button data-view="${k}" aria-current="${view===k}">${ic(view === k ? icon : icon + "-outline", 26)}<span>${l}</span></button>`).join("")}''',
        '''${TABS.map(([k, l, icon]) => k === "sources"
     ? `<a href="/sources" class="tab-link" aria-label="Sources">${ic("list-outline", 26)}<span>${l}</span></a>`
     : `<button data-view="${k}" aria-current="${view===k}">${ic(k === "activity" ? "time-outline" : view === k ? icon : icon + "-outline", 26)}<span>${l}</span></button>`).join("")}''', 'bottom tab links')

# The Apps tab is now the one-stop screen for pairing, credentials, importing,
# installed apps and scheduled renewals. A missing setup never blocks the view.
replace('''  if (!S.configured) return `<div class="list"><div class="empty">${ic("phone-portrait-outline", 44)}<b>Not Set Up Yet</b>
    Add a device, an app and your Apple ID.<div style="margin-top:18px"><button class="cap solid" data-go="settings">Open Settings</button></div></div></div>`;
''', '', 'premature setup screen')
replace('if (!S.services.anisette || !S.services.muxer) issues.push',
        'if (S.configured && (!S.services.anisette || !S.services.muxer)) issues.push', 'health alerts')
replace('return `${autoCard}${issues.map(', 'return `${settingsView()}${autoCard}${issues.map(', 'setup on home')
# Action links open the appropriate accordion step, not the removed Settings tab.
source = source.replace('data-go="settings"', 'data-step-open="3"')

# Avoid the duplicate auto-renew switch: it lives in Step 4 instead.
last_control = '''  <div class="sect">
    <div class="list"><div class="cell">${tile("var(--green)", "flash")}<span class="k">Re-sign Automatically</span>${sw("auto", c.auto_check)}</div></div>
    <div class="foot">Checks each device when it connects and re-signs ${c.renew_before_days} day${c.renew_before_days > 1 ? "s" : ""} before an app expires.</div>
  </div>`;'''
replace(last_control, '`;', 'duplicate renewal toggle')

# The four original Settings sections are retained (including all their
# controls), reordered to device -> Apple Account -> IPA -> auto-renewal and
# wrapped in accessible accordion panels.
a = source.index('function settingsView() {')
b = source.index('\nfunction ipaWarnings(', a)
old_func = source[a:b]
pre, body = old_func.split('  return `\n', 1)
markup, ending = body.rsplit('`;\n}', 1)
if ending.strip():
    sys.exit('Unexpected text after Settings template')
parts = markup.split('  <div class="sect">\n')
if len(parts) != 5 or parts[0].strip():
    sys.exit('Upstream Settings section structure changed')
sections = []
for part in parts[1:]:
    closing = part.rfind('\n  </div>')
    if closing < 0 or part[closing + len('\n  </div>'):].strip():
        sys.exit('Cannot identify end of Settings section')
    contents = part[:closing]
    contents, changed = re.subn(r'^    <div class="shead"><h3>[^<]*</h3></div>\n', '', contents, count=1)
    if changed != 1:
        sys.exit('Settings section heading changed')
    sections.append(contents)

pre += '''  const onlineDevice = devs.some(d => d.live && d.live.reachable);
  const installedApp = apps.some(a => (a.targets || []).some(t => t.installation && t.installation.state === "installed"));
  const deviceDone = devs.length > 0;
  const appleDone = Boolean(c.apple_id && c.has_password);
  const completed = [deviceDone, appleDone, installedApp, c.auto_check];
  // When an outstanding setup step is completed, collapse it on the next poll.
  // Previously completed steps can still be opened for editing at any time.
  if (setupDoneSnapshot) {
    for (let i = 0; i < completed.length; i++) {
      if (!setupDoneSnapshot[i] && completed[i] && setupChoice === i + 1) setupChoice = null;
    }
  }
  setupDoneSnapshot = completed;
  const preferredStep = !deviceDone ? 1 : !appleDone ? 2 : !installedApp ? 3 : 0;
  const expanded = setupChoice === null ? preferredStep : setupChoice;
'''

# The template's own `${...}` interpolations remain intact inside each nested
# template literal. Values are never reinterpreted as Python format strings.
steps = [
    (1, 'Connect your iPhone',
     'devs.length ? `${esc(devs[0].name)} · ${onlineDevice ? "Connected" : "Saved · Offline"}` : "Connect or scan for a device"',
     'deviceDone', sections[0]),
    (2, 'Apple Account',
     'appleDone ? "Account details saved" : "Enter account and password"',
     'appleDone', sections[2]),
    (3, 'Add and install an app',
     'installedApp ? "Installed on iPhone" : apps.length ? `${apps.length} IPA saved · installation pending` : "Choose a source or IPA"',
     'installedApp', sections[1] + '\n    <div class="step-source"><a href="/sources">Browse AltStore Sources</a></div>'),
    (4, 'Automatic renewal',
     'c.auto_check ? "Automatic renewal enabled" : "Automatic renewal disabled"',
     'c.auto_check', sections[3]),
]
step_markup = []
for n, title, subtitle, done, html in steps:
    step_markup.append('${renderSetupStep(' + str(n) + ', "' + title + '", ' +
                       subtitle + ', ' + done + ', `' + html + '`, expanded)}')
new_func = pre + '  return `\n  <div class="setup-heading">SETUP · EXPAND ANY STEP TO EDIT</div>\n' + '\n'.join(step_markup) + '\n  `;\n}'
source = source[:a] + new_func + source[b:]

replace('''  root.querySelectorAll("[data-go]").forEach(b => b.onclick = () => go(b.dataset.go));''',
        '''  root.querySelectorAll("[data-go]").forEach(b => b.onclick = () => go(b.dataset.go));
  root.querySelectorAll(".setup-step > summary").forEach(summary => summary.onclick = e => {
    e.preventDefault();
    const panel = summary.parentElement;
    setupChoice = panel.open ? -1 : Number(panel.dataset.step);
    render();
  });
  root.querySelectorAll("[data-step-open]").forEach(button => button.onclick = () => {
    setupChoice = Number(button.dataset.stepOpen);
    window.scrollTo({top:0,behavior:"smooth"});
    render();
  });''', 'accordion event handlers')

css = '''
''' + MARKER + '''
.tabbar button, .tabbar a.tab-link{flex:1;border:0;background:none;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:2px;font-size:10px;font-weight:500;letter-spacing:.01em;color:var(--gray);cursor:pointer;padding-top:3px;text-decoration:none}
.tabbar button[aria-current=true], .tabbar a.tab-link[aria-current=page]{color:var(--blue)}
.setup-heading{font-size:12px;color:var(--label-2);margin:4px 6px 9px;letter-spacing:.035em;font-weight:600}
.setup-step{margin:0 0 10px;border-radius:12px;background:var(--cell);overflow:hidden}
.setup-step>summary{list-style:none;cursor:pointer;display:flex;align-items:center;gap:13px;padding:13px 16px;min-height:62px}
.setup-step>summary::-webkit-details-marker{display:none}
.setup-step>summary:focus-visible{outline:2px solid var(--blue);outline-offset:-3px}
.step-number{flex:none;display:grid;place-items:center;width:28px;height:28px;border-radius:50%;font-size:14px;font-weight:700;background:var(--fill-3);color:var(--blue)}
.step-caption{flex:1;min-width:0}
.step-label{display:block;font-size:11px;font-weight:700;color:var(--label-2);text-transform:uppercase;letter-spacing:.055em;margin-bottom:3px}
.step-caption b{display:block;font-size:16px;line-height:1.25}
.step-caption small{display:block;color:var(--label-2);font-size:13px;margin-top:3px;line-height:1.3}
.step-state{font-size:20px;color:var(--label-2);display:grid;place-items:center;flex:none;width:25px}
.step-state.done{color:var(--green);font-weight:700}
.setup-step[open]>summary{border-bottom:.5px solid var(--sep)}
.setup-step>.step-body{padding:10px 0 12px}
.setup-step .list{border-radius:0}
.setup-step .foot{margin:7px 16px 3px}
.step-source{padding:10px 16px 0;font-size:15px}
.step-source a{color:var(--blue);text-decoration:none;font-weight:600;display:flex;align-items:center;min-height:44px}
/* Responsive by default: the navigation remains reachable above the home
   indicator; input labels, cards and app status never force horizontal scroll. */
html{scroll-padding-bottom:calc(92px + env(safe-area-inset-bottom))}
.tabbar .in{max-width:680px;height:56px}
.tabbar button,.tabbar a.tab-link{min-height:50px;min-width:0;touch-action:manipulation}
.setup-step>summary{touch-action:manipulation}
.setup-step .cell{min-width:0}
.setup-step .cell input.fi,.setup-step .cell select.fi{min-width:0;max-width:100%}
@media(max-width:540px){
  .page{padding-left:12px;padding-right:12px;padding-bottom:calc(92px + env(safe-area-inset-bottom))}
  .large{font-size:29px;line-height:1.2;margin-bottom:14px}
  .setup-step{border-radius:12px;margin-bottom:9px}
  .setup-step>summary{padding:12px;gap:10px;min-height:64px}
  .step-caption small{overflow-wrap:anywhere}
  .step-body .cell{padding:11px 12px;gap:8px;min-height:48px}
  .step-body .cell label{font-size:14px}
  .step-body .cell input.fi{font-size:16px}
  .step-body .drop{padding:13px 12px;min-height:48px}
  .step-body .shead{margin-left:12px;margin-right:12px}
  .step-body .foot{margin-left:12px;margin-right:12px}
  .step-body .appcell .chips{margin-top:7px}
  .step-body .appcell .k{overflow-wrap:anywhere}
  .approw{gap:8px;padding:12px}
  .approw .nm{font-size:16px}
  .approw .st{font-size:13px;line-height:1.35;overflow-wrap:anywhere}
  .approw .cap{padding:9px 12px;font-size:14px;min-height:44px}
  .tabbar button,.tabbar a.tab-link{font-size:11px}
  .tabbar{padding-bottom:max(env(safe-area-inset-bottom),4px)}
}
@media(max-width:350px){
  .step-body .cell:has(input.fi){flex-wrap:wrap}
  .step-body .cell input.fi{flex-basis:100%;text-align:left}
  .approw{flex-wrap:wrap}
  .approw .cap{margin-left:auto}
}
@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}}

'''
# Embed diagnostics in the Activity page, keeping the screen clear on phones.
replace('    <div class="list"><pre class="logs" id="logs">Loading…</pre></div></div>`;',
        '    <div class="list"><button class="cell action" type="button" id="sideloader-copy-diagnostics">Copy Diagnostics</button><pre class="logs" id="logs">Loading…</pre></div></div>`;',
        'Activity diagnostics action')
replace('</style>', css + '</style>', 'step and tab styles')
upgrade_offline_step()
save()
print('SideLoader setup wizard and three-tab navigation installed.')