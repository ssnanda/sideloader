#!/usr/bin/env python3
"""Merge imported IPA and scanned iPhone apps into a single Step 3.

Idempotent overlay for SideLoader's persistent, already patched checkout. Works
AFTER all earlier navigation, signing, responsive and provenance overlays.
Never changes /data or starts an Apple authentication request.
"""
from pathlib import Path
import sys

if len(sys.argv) != 3:
    sys.exit('Usage: patch-apps-dashboard.py <sideloop-checkout> <overlay-dir>')
checkout, overlays = Path(sys.argv[1]), Path(sys.argv[2])
server = checkout / 'sideloop' / 'server.py'
index = checkout / 'sideloop' / 'index.html'
marker = '/* SideLoader unified iPhone Apps step v1 */'
s = server.read_text()
h = index.read_text()


def replace(source, old, new, label):
    if new in source:
        return source
    if source.count(old) != 1:
        sys.exit(f'Apps dashboard patch {label}: expected one anchor, got {source.count(old)}')
    return source.replace(old, new, 1)


# Import beside the upstream module import, which is unique across overlay
# generations. Earlier overlays may legitimately repeat the log_maintenance
# import in old persistent checkouts; its count is not a migration invariant.
# Existing inventory import is accepted wherever it appears in the import block.
if 'from . import device_app_inventory' not in s:
    s = replace(s, 'from . import auth, config, ipa, pairing, store',
                'from . import auth, config, ipa, pairing, store\n'
                'from . import device_app_inventory', 'inventory import')
s = replace(s,
            '    def signing_resume(self, data):',
            '''    def remove_phone_apps(self, data):
        if data.get("acknowledge") is not True:
            raise ValueError("Confirm which iPhone apps will be uninstalled, including their data")
        self.idle()
        udid = self.device({"device": data.get("device", "")})
        if not udid:
            raise ValueError("Select a registered iPhone")
        return device_app_inventory.remove_apps(self, udid, data.get("bundles", []))

    def signing_resume(self, data):''', 'explicit uninstall handler')
# Locate the active routes() and do_GET() structurally. Older builds may
# contain duplicate log route entries from interacting overlays; do not add an
# inventory route per duplicate or rely on the number of log anchors.
def insert_scoped(source, start, end, anchor, addition, present, label, after=False):
    if source.count(start) != 1 or source.count(end) != 1:
        sys.exit(f'Apps dashboard patch {label}: ambiguous handler boundaries')
    a = source.index(start)
    b = source.index(end, a + len(start))
    section = source[a:b]
    if present in section:
        return source
    if section.count(anchor) != 1:
        sys.exit(f'Apps dashboard patch {label}: expected one insertion boundary, got {section.count(anchor)}')
    section = section.replace(anchor, anchor + addition if after else addition + anchor, 1)
    return source[:a] + section + source[b:]


s = insert_scoped(
    s, '    def routes(self):', '\n\ndef handler(app):',
    '        return {\n',
    '            "/api/device/apps/remove": self.remove_phone_apps,\n',
    '"/api/device/apps/remove": self.remove_phone_apps',
    'uninstall POST route', after=True)
s = insert_scoped(
    s, '        def do_GET(self):', '        def do_POST(self):',
    '            self.error(404, "not found")',
    '''            if path == "/api/device/apps":
                udid = app.device({"device": urllib.parse.parse_qs(query).get("device", [""])[0]})
                if not udid:
                    return self.error(400, "Select a registered iPhone")
                try:
                    return self.send(200, {"apps": device_app_inventory.inventory(udid)})
                except (RuntimeError, ValueError) as e:
                    return self.error(409, str(e))
''',
    'if path == "/api/device/apps":',
    'protected read-only inventory GET')

if marker not in h:
    step3_start = h.find('${renderSetupStep(3, "Add an IPA"')
    step4_start = h.find('${renderSetupStep(4, "Install on iPhone"', step3_start)
    ending = ', expanded)}'
    if step3_start < 0 or step4_start < 0:
        sys.exit('Apps dashboard patch: cannot locate installed four-step wizard')
    # Accept whitespace variants in the closing expression while keeping
    # each match within its own wizard step.
    import re
    closing_pattern = re.compile(r',\s*expanded\s*\)\s*\}')
    footer = h.find('${sideloopCoreCard()}', step4_start)
    if footer < 0:
        sys.exit('Apps dashboard patch: cannot locate wizard footer')
    closing3 = list(closing_pattern.finditer(h, step3_start, step4_start))
    closing4 = list(closing_pattern.finditer(h, step4_start, footer))
    if not closing3 or not closing4:
        sys.exit('Apps dashboard patch: unexpected wizard template closing '
                 f'(step3={len(closing3)}, step4={len(closing4)})')
    step3_end = closing3[-1].end()
    step4_end = closing4[-1].end()
    old3 = h[step3_start:step3_end]
    old4 = h[step4_start:step4_end]
    if ('id="recheck"' not in old4 or 'data-sign=' not in old4 or
            'step-source' not in old3):
        sys.exit('Apps dashboard patch: previous install/import controls differ; refusing migration')
    open3 = old3.find(', `')
    close3 = old3.rfind('`', 0, closing3[-1].start() - step3_start)
    if open3 < 0 or close3 < open3:
        sys.exit('Apps dashboard patch: cannot retain IPA import controls')
    import_body = old3[open3 + 3:close3]
    # Step 3 is now the one always-open Apps view. Imported IPAs are retained
    # below device scanning and selection; the standalone Install step is gone.
    new3 = '''${renderSetupStep(3, "Apps",
  deviceAppRows.length ? `${deviceAppRows.length} installed on iPhone` :
    apps.length ? `${apps.length} IPA${apps.length === 1 ? "" : "s"} imported · scan iPhone` : "Scan your iPhone or import an IPA",
  appReady || deviceAppRows.length > 0,
  `${deviceAppsManager()}
    <div class="device-app-import-label">IMPORT AN IPA / ALTSTORE SOURCES</div>
''' + import_body + '''`, expanded)}'''
    # Remove Step 4 and reuse Step 3's existing import controls. Keeping the
    # original controls prevents regressions in upload, source browsing, etc.
    h = h[:step3_start] + new3 + h[step3_end:step4_start] + h[step4_end:]
    h = replace(h,
                '  const completed = [deviceDone, appleDone, appReady, everyAppInstalled];',
                '  const completed = [deviceDone, appleDone, appReady];', '3-step completion')
    h = replace(h,
                '  const ready = [deviceDone, accountReady, appReady, everyAppInstalled];',
                '  const ready = [deviceDone, accountReady, appReady];', '3-step readiness')
    h = replace(h,
                '  const preferredStep = !deviceDone ? 1 : !accountReady ? 2 : !appReady ? 3 : !everyAppInstalled ? 4 : 0;',
                '  const preferredStep = 3; // The Apps step remains expanded by default.', 'expand Apps')
    h = replace(h,
                'devs.length ? `${esc(devs[0].name)} · ${connectionLabel} · Last checked ${checkedTime}` : `Connect or scan for a device · Last checked ${checkedTime}`',
                'devs.length ? `${esc(devs[0].name)} · ${connectionLabel}` : "Not connected"', 'short connected status')
    step2start = h.find('${renderSetupStep(2, "Apple Account",')
    step2end = h.find(', appleDone, `', step2start)
    if step2start < 0 or step2end < 0 or step2end-step2start > 1200:
        sys.exit('Apps dashboard patch: cannot locate Apple status subtitle')
    h = h[:step2start] + '${renderSetupStep(2, "Apple Account", appleDone ? "Verified" : c.apple_id && c.has_password ? (appleInfo.state === "failed" ? "Sign-in failed" : "Saved · unverified") : "Not configured"' + h[step2end:]
    # Drop the big developer-build cards. Preserve the underlying functions so
    # older repeat-build migrations remain idempotent after this overlay.
    h = replace(h,
                '  ${sideloopCoreCard()}\n  ${altserverBackendCard()}',
                '  ${sideLoaderVersionStrip()}', 'replace full build provenance cards')
    h = replace(h, 'function settingsView() {',
                (overlays / 'apps-dashboard-ui.js').read_text() +
                '\nfunction settingsView() {', 'apps manager helper')
    h = replace(h,
                '  on("reload", "onclick", loadLogs);',
                '  on("reload", "onclick", loadLogs);\n' +
                (overlays / 'apps-dashboard-wire.js').read_text(),
                'apps manager events')
    css = (overlays / 'apps-dashboard.css').read_text()
    h = replace(h, '</style>', css + '\n</style>', 'compact responsive styling')

# Refresh Apps manager code inside a persistent, already unified dashboard.
# Without this migration, the marker above skips the new UI on future builds.
else:
    current_ui = (overlays / 'apps-dashboard-ui.js').read_text()
    start = h.find(marker)
    end = h.find('\nfunction settingsView() {', start)
    if start < 0 or end < 0 or h.count(marker) != 1:
        sys.exit('Apps dashboard patch: cannot safely refresh existing Apps helper')
    previous_ui = h[start:end].rstrip('\n')
    if 'function deviceAppsManager()' not in previous_ui:
        sys.exit('Apps dashboard patch: unrecognized existing Apps helper')
    h = h[:start] + current_ui.rstrip('\n') + h[end:]

    # Keep the existing event wiring and add only the new filter event.
    filter_event = '  on("sideloader-sideloaded-only", "onchange", e => {'
    if filter_event not in h:
        scan_event = '  on("sideloader-device-app-scan", "onclick", () => {'
        if h.count(scan_event) != 1:
            sys.exit('Apps dashboard patch: cannot locate scan handler for filter migration')
        h = h.replace(scan_event,
            '''  on("sideloader-sideloaded-only", "onchange", e => {
    deviceAppSideloadedOnly = e.target.checked;
    render();
  });
''' + scan_event, 1)
    css = (overlays / 'apps-dashboard.css').read_text()
    filter_css = '\n.sl-app-filter{display:inline-flex;align-items:center;gap:8px;font-size:14px;font-weight:600;padding:8px 2px;cursor:pointer;}\n.sl-app-filter input{width:18px;height:18px;accent-color:var(--blue);}\n'
    if '.sl-app-filter{' not in h:
        h = replace(h, '</style>', filter_css + '</style>', 'filter CSS migration')

# Route every install through the existing job sheet, even if Apple rejects it
# before the ordinary 1.5-second polling interval. Sources carries its job ID
# in sessionStorage during the same-tab navigation back to Apps.
old_start = 'function startJob(path, body={}) { return act(async () => { const r = await api(path, {json: body}); if (r.job) watched.add(r.job); }); }'
new_start = '''async function startJob(path, body={}) {
  try {
    const r = await api(path, {json:body});
    if (!r.job) throw new Error("Install did not return a signing job");
    watched.add(r.job);
    dismissedJob = null;
    await refresh();
    if (S.job?.id === r.job) {
      await pullJob();
      render();
      renderSheet();
    } else {
      await poll();
    }
  } catch (e) {
    // A signing lock or setup error must be shown, not lost in a toast.
    window.alert("Installation was not started: " + e.message);
    await poll();
  }
}'''
if old_start in h:
    h = h.replace(old_start, new_start, 1)
elif new_start not in h:
    sys.exit('Apps dashboard patch: unrecognized install job launcher')

# Boot can occur after a Sources installation has already finished, so the
# completed job must still be watched to show its result.
old_boot = '  await refresh();\n  if (!S.configured) view = "apps";'
new_boot = '''  await refresh();
  let pendingSourceJob = null;
  try {
    pendingSourceJob = sessionStorage.getItem("sideloaderPendingJob");
    sessionStorage.removeItem("sideloaderPendingJob");
  } catch {}
  if (pendingSourceJob) {
    watched.add(pendingSourceJob);
    dismissedJob = null;
    view = "apps";
  }
  if (!S.configured) view = "apps";'''
if old_boot in h:
    h = h.replace(old_boot, new_boot, 1)
elif new_boot not in h:
    sys.exit('Apps dashboard patch: unrecognized boot method for Sources handoff')

# Only commit when ALL validation and transformations succeed.
server.write_text(s)
index.write_text(h)
(checkout / 'sideloop' / 'device_app_inventory.py').write_bytes(
    (overlays / 'device_app_inventory.py').read_bytes())
print('Unified three-step Apps dashboard, iPhone inventory and compact version status applied (repeatable).')