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


s = replace(s, 'from . import log_maintenance',
            'from . import log_maintenance\nfrom . import device_app_inventory', 'inventory import')
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
s = replace(s, '            "/api/logs/clear": self.clear_activity_logs,',
            '            "/api/logs/clear": self.clear_activity_logs,\n'
            '            "/api/device/apps/remove": self.remove_phone_apps,',
            'uninstall POST route')
s = replace(s,
            '            if path == "/api/logs":\n                return self.send(200, app.logs())',
            '''            if path == "/api/logs":
                return self.send(200, app.logs())
            if path == "/api/device/apps":
                udid = app.device({"device": urllib.parse.parse_qs(query).get("device", [""])[0]})
                if not udid:
                    return self.error(400, "Select a registered iPhone")
                try:
                    return self.send(200, {"apps": device_app_inventory.inventory(udid)})
                except (RuntimeError, ValueError) as e:
                    return self.error(409, str(e))''', 'protected read-only inventory GET')

if marker not in h:
    step3_start = h.find('${renderSetupStep(3, "Add an IPA"')
    step4_start = h.find('${renderSetupStep(4, "Install on iPhone"', step3_start)
    ending = ', expanded)}'
    if step3_start < 0 or step4_start < 0:
        sys.exit('Apps dashboard patch: cannot locate installed four-step wizard')
    step3_end = h.find(ending, step3_start, step4_start)
    step4_end = h.find(ending, step4_start)
    if step3_end < 0 or step4_end < 0:
        sys.exit('Apps dashboard patch: unexpected wizard template closing')
    step3_end += len(ending)
    step4_end += len(ending)
    old3 = h[step3_start:step3_end]
    old4 = h[step4_start:step4_end]
    if ('id="recheck"' not in old4 or 'data-sign=' not in old4 or
            'step-source' not in old3):
        sys.exit('Apps dashboard patch: previous install/import controls differ; refusing migration')
    open3, close3 = old3.find(', `'), old3.rfind('`, expanded)}')
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

# Only commit when ALL validation and transformations succeed.
server.write_text(s)
index.write_text(h)
(checkout / 'sideloop' / 'device_app_inventory.py').write_bytes(
    (overlays / 'device_app_inventory.py').read_bytes())
print('Unified three-step Apps dashboard, iPhone inventory and compact version status applied (repeatable).')