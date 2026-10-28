#!/usr/bin/env python3
"""Apply SideLoader v2 installation verification, diagnostics and signing support."""
from pathlib import Path
import sys

if len(sys.argv) != 3:
    sys.exit('Usage: patch-v2.py <sideloop-checkout> <overlay-dir>')
root, overlays = Path(sys.argv[1]), Path(sys.argv[2])
package = root / 'sideloop'


def replace_once(path, original, replacement, marker):
    source = path.read_text()
    if marker in source:
        return
    count = source.count(original)
    if count != 1:
        sys.exit(f'Cannot safely patch {path.name}: found {count} matches for {original[:70]!r}')
    path.write_text(source.replace(original, replacement, 1))


for name in ('installed.py', 'diagnostics.py'):
    (package / name).write_bytes((overlays / name).read_bytes())

server = package / 'server.py'
replace_once(server,
    'from . import auth, config, ipa, pairing, store',
    'from . import auth, config, ipa, pairing, store\nfrom .installed import enrich_apps  # SideLoader installation verification\nfrom .diagnostics import report as diagnostic_report',
    'from .installed import enrich_apps')
replace_once(server,
    '"apps": [store.app_view(a) for a in store.app_ids()],',
    '"apps": enrich_apps([store.app_view(a) for a in store.app_ids()], live),',
    '"apps": enrich_apps(')
replace_once(server,
    'if path == "/api/logs":\n                return self.send(200, app.logs())',
    'if path == "/api/logs":\n                return self.send(200, app.logs())\n            if path == "/api/diagnostics":\n                return self.send(200, diagnostic_report(app).encode("utf-8"), "text/plain; charset=utf-8")',
    'if path == "/api/diagnostics":')

index = package / 'index.html'
replace_once(index,
    'function sig(t) {\n  const e = t.signature.expiry, left = e ? e - S.now : 0;',
    '''function sig(t) {
  const presence = t.installation && t.installation.state;
  if (presence === "missing") return {cls:"bad", text:"Not installed on iPhone", left:0};
  if (presence === "offline") return {cls:"idle", text:"Device offline — install unverified", left:0};
  if (presence !== "installed") return {cls:"warn", text:"Installation status unknown", left:0};
  const e = t.signature.expiry, left = e ? e - S.now : 0;''',
    'Device offline — install unverified')
replace_once(index,
    '${t.signature.expiry ? `<div class="meter ${s.cls}"><i style="width:${pct}%"></i></div>` : ""}',
    '${t.installation?.state === "installed" && t.signature.expiry ? `<div class="meter ${s.cls}"><i style="width:${pct}%"></i></div>` : ""}',
    't.installation?.state === "installed" && t.signature.expiry')
replace_once(index,
    '${t.signature.expiry ? "Re-sign" : "Install"}',
    '${t.installation?.state === "installed" ? "Re-sign" : "Install"}',
    't.installation?.state === "installed" ? "Re-sign"')
replace_once(index,
    'const due = onDev(d).some(({t}) => !t.signature.expiry || t.signature.expiry - S.now <= window);',
    'const due = onDev(d).some(({t}) => t.installation?.state === "missing" || !t.signature.expiry || t.signature.expiry - S.now <= window);',
    't.installation?.state === "missing" ||')
replace_once(index,
    'const s = sig(t), lr = t.signature.last_run, failed = lr && lr.result === "fail";',
    'const s = sig(t), lr = t.signature.last_run, failed = lr && lr.result === "fail";',
    'SideLoader-no-op') if False else None
# Avoid marking a missing app as "Last re-sign failed" in place of its absence.
replace_once(index,
    '${failed ? "Last re-sign failed" : s.text}',
    '${t.installation?.state === "missing" ? s.text : failed ? "Last re-sign failed — " + s.text : s.text}',
    '"Last re-sign failed — "')
source = index.read_text()
if 'id="sideloader-copy-diagnostics"' not in source:
    marker = '</body>'
    if source.count(marker) != 1:
        sys.exit('Cannot locate dashboard body end for diagnostics button')
    index.write_text(source.replace(marker, (overlays / 'diagnostics-ui.html').read_text() + '\n' + marker, 1))

refresh = root / 'scripts' / 'refresh.sh'
replace_once(refresh,
    '''if (( RECHECK )); then
  device_online || { echo "${TAG}${DEVICE_NAME} not reachable; unlock it and try again"; exit 1; }
  p="$(probe_expiry)" || { rm -f "$EXPIRY"; log "not installed on this device"; exit 0; }
  save_probe "$p"
  log "rechecked on the device: signature valid until $(fmt_epoch "$(cat "$EXPIRY")")"
  exit 0
fi''',
    '''# SideLoader verifies app installation independently from provisioning profiles.
app_state() { python3 /opt/sideloop/installed.py "$DEVICE_UDID" "$BUNDLE_ID" --no-cache; }
if (( RECHECK )); then
  device_online || { echo "${TAG}${DEVICE_NAME} not reachable; unlock it and try again"; exit 1; }
  status="$(app_state)"
  if [[ "$status" == missing ]]; then
    rm -f "$EXPIRY"
    log "NOT INSTALLED on device (profile may still exist)"
    record missing "iOS app inventory does not contain the bundle"
    exit 0
  fi
  [[ "$status" == installed ]] || { log "installation status unknown — device inventory query failed"; exit 1; }
  p="$(probe_expiry)" || { rm -f "$EXPIRY"; log "installed on device; provisioning profile missing"; exit 0; }
  save_probe "$p"
  log "rechecked on device: installed, signature valid until $(fmt_epoch "$(cat "$EXPIRY")")"
  exit 0
fi''',
    'SideLoader verifies app installation independently')
replace_once(refresh,
    '''LEFT="$(days_left)"
(( FORCE == 0 && LEFT > RENEW_BEFORE_DAYS )) && exit 0

if [[ -r "$EXPIRY" ]]; then''',
    '''# A cached profile expiry is not evidence that the IPA exists on the iPhone.
# Query inventory BEFORE deciding an app is not due for renewal.
if device_online; then
  status="$(app_state)"
  if [[ "$status" == missing ]]; then
    rm -f "$EXPIRY"
    FORCE=1
    log "NOT INSTALLED on device; attempting a fresh installation"
  elif [[ "$status" == unknown ]]; then
    log "WARNING: cannot verify app inventory; do not assume it is installed"
  fi
fi
LEFT="$(days_left)"
(( FORCE == 0 && LEFT > RENEW_BEFORE_DAYS )) && exit 0

if [[ -r "$EXPIRY" ]]; then''',
    'Query inventory BEFORE deciding')
replace_once(refresh,
    'if (( rc == 0 )) && stamp_success; then',
    'if (( rc == 0 )) && [[ "$(app_state)" == installed ]] && stamp_success; then',
    '[[ "$(app_state)" == installed ]] && stamp_success')
replace_once(refresh,
    '''if (( rc == 0 )); then
  rc=1
  hint="AltServer finished, but the app isn't on the device (did it lock or leave Wi-Fi mid-copy?)"
elif grep -qiE 'two.?factor code|verification code' "$out"; then''',
    '''if (( rc == 0 )); then
  rc=1
  hint="AltServer returned success but installed-app inventory did not confirm this app; check device connectivity and signing"
elif grep -q -- '-80046' "$out"; then
  hint="Apple rejected a developer app token (-80046): confirm Mac anisette is reachable; not a device lock/Wi-Fi error"
elif grep -qiE 'two.?factor code|verification code' "$out"; then''',
    'AltServer returned success but installed-app inventory')

# Build fixes: run the currently maintained NG AltServer with Mac-compatible anisette,
# retain Sideloop's profile and chunking patches, and add the inventory utility.
dockerfile = root / 'Dockerfile'
replace_once(dockerfile, 'ARG ALTSERVER_TAG=ng-2026-09-13',
             'ARG ALTSERVER_TAG=ng\nARG ALTSERVER_REV=5c32531fe0eb6ff87ed8f7b137da803c91945a02',
             'ARG ALTSERVER_REV=5c32531fe0eb6ff87ed8f7b137da803c91945a02')
replace_once(dockerfile, 'ARG ALTSERVER_TAG\nCOPY altserver',
             'ARG ALTSERVER_TAG\nARG ALTSERVER_REV\nCOPY altserver',
             'ARG ALTSERVER_TAG\nARG ALTSERVER_REV\nCOPY')
replace_once(dockerfile, '&& cd /src && git apply /tmp/patches/*.patch',
             '&& cd /src && test "$(git rev-parse HEAD)" = "$ALTSERVER_REV" && git apply /tmp/patches/*.patch',
             'test "$(git rev-parse HEAD)" = "$ALTSERVER_REV"')
replace_once(dockerfile, 'libimobiledevice-utils usbmuxd openssl',
             'libimobiledevice-utils ideviceinstaller usbmuxd openssl',
             'libimobiledevice-utils ideviceinstaller')
print('SideLoader v2 patch applied; old IPA/data/profile directories untouched.')
