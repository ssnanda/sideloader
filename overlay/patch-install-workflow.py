#!/usr/bin/env python3
"""Separate IPA import, on-device installation, and optional renewal settings.

Run after navigation, device health, Apple verification and signing-guard patches.
Supports already-patched local upstream checkouts and preserves stored data.
"""
from pathlib import Path
import re
import sys

if len(sys.argv) != 2:
    sys.exit("Usage: patch-install-workflow.py <sideloop-checkout>")

index = Path(sys.argv[1]) / "sideloop" / "index.html"
source = index.read_text()
marker = "/* SideLoader four-stage installation workflow v1 */"
if marker in source:
    print("Four-stage installation workflow already installed.")
    sys.exit(0)


def once(before, after, name):
    global source
    count = source.count(before)
    if count != 1:
        sys.exit(f"Cannot safely upgrade installation workflow ({name}): {count} anchors")
    source = source.replace(before, after, 1)


start = source.find("function settingsView() {")
end = source.find("\nfunction ipaWarnings(", start)
if start < 0 or end < 0:
    sys.exit("Cannot safely find setup wizard")
wizard = source[start:end]
old4_start = wizard.find('${renderSetupStep(4, "Automatic renewal",')
old4_end = wizard.find(", expanded)}", old4_start)
if old4_start < 0 or old4_end < 0:
    sys.exit("Cannot safely locate old Step 4 renewal settings")
old4_end += len(", expanded)}")
old4 = wizard[old4_start:old4_end]
open_body = old4.find(", `")
close_body = old4.rfind("`, expanded)}")
if open_body < 0 or close_body < open_body:
    sys.exit("Cannot safely preserve the renewal controls")
renewal_controls = old4[open_body + 3:close_body]
if 'id="rb"' not in renewal_controls or 'sw("auto2", c.auto_check)' not in renewal_controls:
    sys.exit("Automatic renewal controls changed; refusing to move them")

once(
    '  const completed = [deviceDone, appleDone, installedApp, c.auto_check];',
    '''  /* SideLoader four-stage installation workflow v1 */
  const accountReady = Boolean(c.apple_id && c.has_password);
  const appReady = apps.length > 0;
  const installTargets = apps.flatMap(a => a.targets || []);
  const everyAppInstalled = installTargets.length > 0 &&
      installTargets.every(t => t.installation?.state === "installed");
  // Initial installation needs saved credentials, but verification is only
  // possible AFTER a successfully signed and installed app.
  const completed = [deviceDone, appleDone, appReady, everyAppInstalled];
  const ready = [deviceDone, accountReady, appReady, everyAppInstalled];''',
    "wizard completion and readiness")
once(
    '      if (!setupDoneSnapshot[i] && completed[i] && setupChoice === i + 1) setupChoice = null;',
    '      if (!setupDoneSnapshot[i] && ready[i] && setupChoice === i + 1) setupChoice = null;',
    "automatic advance")
once('  setupDoneSnapshot = completed;', '  setupDoneSnapshot = ready;', "readiness snapshot")
once(
    '  const preferredStep = !deviceDone ? 1 : !appleDone ? 2 : !installedApp ? 3 : 0;',
    '  const preferredStep = !deviceDone ? 1 : !accountReady ? 2 : !appReady ? 3 : !everyAppInstalled ? 4 : 0;',
    "wizard progression")
once(
    'renderSetupStep(3, "Add and install an app", installedApp ? "Installed on iPhone" : apps.length ? `${apps.length} IPA saved · installation pending` : "Choose a source or IPA", installedApp,',
    'renderSetupStep(3, "Add an IPA", appReady ? `${apps.length} IPA${apps.length === 1 ? "" : "s"} saved · continue to Step 4 to install` : "Import an IPA or browse Sources; no installation yet", appReady,',
    "Step 3 accurate label")

step4 = r'''${renderSetupStep(4, "Install on iPhone",
  !appReady ? "Add an IPA in Step 3 first" :
  everyAppInstalled ? "All assigned apps installed on iPhone" :
  S.signing_guard?.blocked ? "Signing paused after a failure — review Activity" :
  !onlineDevice ? "Connect and unlock your iPhone to install" :
  !accountReady ? "Save Apple Account credentials in Step 2" :
  "Ready for manual installation",
  everyAppInstalled,
  `<div class="list">
    ${apps.flatMap(a => (a.targets || []).map(t => {
      const d = devs.find(d => d.udid === t.udid);
      const installed = t.installation?.state === "installed";
      const offline = !recentCheck || !d?.live?.reachable;
      const busy = Boolean(S.job?.running || S.watcher?.running);
      const blocked = Boolean(S.signing_guard?.blocked);
      const status = installed ? "Installed on iPhone" :
        offline ? "Device offline — install not verified" :
        t.installation?.state === "missing" ? "Not installed on iPhone" :
        "Installation not verified";
      return `<div class="cell ind">
        ${appIcon(a, "xs")}
        <span class="k">${esc(a.name)}<span class="sub">${esc(d?.name || t.name || "iPhone")} · ${status}</span></span>
        <button type="button" class="cap ${installed ? "" : "solid"}"
          data-sign="${esc(a.id)}" data-dev="${esc(t.udid)}"
          ${offline || busy || blocked || !accountReady ? "disabled" : ""}>${installed ? "Re-sign" : "Install"}</button>
      </div>`;
    })).join("") || `<div class="cell"><span class="k" style="color:var(--label-2)">No IPA assigned to an iPhone. Add an IPA in Step 3 and connect a device in Step 1.</span></div>`}
  </div>
  ${S.signing_guard?.blocked ? `<div class="foot" style="color:var(--red)">${esc(S.signing_guard.message || "Signing blocked after a failure.")} Review Activity → Copy Diagnostics and explicitly resume before another attempt.</div>` : ""}
  ${S.job?.running && S.job.kind === "refresh" ? `<div class="foot">Signing/installing now · ${esc(S.job.stage || "starting")}. Follow the progress dialog for verification and final status.</div>` : ""}
  <div class="list"><button type="button" class="cell action" id="recheck"
    ${S.job?.running || S.watcher?.running ? "disabled" : ""}>Check installed apps (does not sign in to Apple)</button></div>
  <div class="foot">Installing is a separate action: adding an IPA does not install it. Each click starts one signing and installation attempt. Success is confirmed against the iPhone app inventory. Automatic retries stop after a signing failure.</div>`,
  expanded)}'''
if old4 not in source:
    sys.exit("Old renewal Step 4 disappeared during migration")
optional = (
    '\n  <div class="setup-heading">SETTINGS · OPTIONAL</div>'
    '\n  <div class="sect renewal-settings">'
    '\n    <div class="shead"><h3>Automatic renewal</h3></div>\n'
    + renewal_controls +
    '\n    <div class="foot">Automatic renewal is a preference, not a setup step. '
    'Enable it after the first successful manual install. Signing pauses on a failed attempt.</div>'
    '\n  </div>'
)
source = source.replace(old4, step4 + optional, 1)

# Remove the second copy of install buttons formerly shown below Step 4.
view_start = source.find("function appsView() {")
view_end = source.find("\nconst STEPS =", view_start)
if view_start < 0 or view_end < 0:
    sys.exit("Cannot safely locate dashboard app cards")
old_list = '  ${devs.map(section).join("")}'
start = source.find(old_list, view_start, view_end)
if start < 0:
    sys.exit("Cannot safely locate duplicate install list")
# The navigation overlay moves the final closing backtick onto its own line.
# Both old `</div>`; ` and new `</div>\n  `; ` are legitimate. Anchor to
# the actual *outer* section closure, not a nested template literal.
tail = source[start:view_end]
closing = re.search(r'(?m)^  </div>[ \t]*\n?[ \t]*`;', tail)
if closing is None:
    sys.exit("Cannot safely locate duplicate install controls")
end = start + closing.end()
removed = source[start:end]
# Navigation also rewrites Add App or Device from data-go to data-step-open.
if ('id="recheck"' not in removed or
        not any(action in removed for action in ('data-step-open="3"', 'data-go="settings"')) or
        '<div class="sect">' not in removed):
    sys.exit("Unexpected install controls; refusing to remove")
source = source[:start] + '  `;' + source[end:]

if source.count('id="recheck"') != 1 or 'data-sign="${esc(a.id)}"' not in source:
    sys.exit("Installation actions were not moved correctly")
index.write_text(source)
print("Four-stage Apps wizard installed; renewal moved to optional settings.")