#!/usr/bin/env python3
"""Install the canonical automatic renewal scheduler (renews below six days)."""
from pathlib import Path
import re
import sys

if len(sys.argv) != 3:
    sys.exit("Usage: patch-auto-resign.py <sideloop-checkout> <overlay-dir>")
checkout, overlay = Path(sys.argv[1]), Path(sys.argv[2])
target = checkout / "sideloop" / "watcher.py"
source = (overlay / "auto_resign_watcher.py").read_text()
if target.read_text() != source:
    target.write_text(source)

# Automatic renewal must never turn a stale assignment into a reinstall.
refresh = checkout / "scripts" / "refresh.sh"
shell = refresh.read_text()
if 'AUTO=0; APP=""; DEVICE=""' not in shell:
    shell = shell.replace('FORCE=0; RECHECK=0; APP=""; DEVICE=""',
                          'FORCE=0; RECHECK=0; AUTO=0; APP=""; DEVICE=""')
if '    --auto) AUTO=1 ;;' not in shell:
    shell = shell.replace('    --recheck) RECHECK=1 ;;',
                          '    --recheck) RECHECK=1 ;;\n    --auto) AUTO=1 ;;')
if '      (( AUTO )) && args+=(--auto)' not in shell:
    shell = shell.replace('      (( RECHECK )) && args+=(--recheck)',
                          '      (( RECHECK )) && args+=(--recheck)\n      (( AUTO )) && args+=(--auto)')
# Manual bulk refresh is renewal-only, unlike an explicit single-app install.
# Propagate --bulk to each child refresh so one removed IPA cannot be reinstalled.
bulk_header = 'FORCE=0; RECHECK=0; AUTO=0; BULK=0; APP=""; DEVICE=""'
if bulk_header not in shell:
    prior_header = 'FORCE=0; RECHECK=0; AUTO=0; APP=""; DEVICE=""'
    if shell.count(prior_header) != 1:
        sys.exit("Bulk re-sign patch: cannot identify refresh argument defaults")
    shell = shell.replace(prior_header, bulk_header, 1)
bulk_switch = '    --bulk) BULK=1 ;;'
if bulk_switch not in shell:
    switch_anchor = '    --auto) AUTO=1 ;;'
    if shell.count(switch_anchor) != 1:
        sys.exit("Bulk re-sign patch: cannot identify refresh argument parser")
    shell = shell.replace(switch_anchor, switch_anchor + '\n' + bulk_switch, 1)
bulk_forward = '      [[ -z "$APP" || "$BULK" == 1 ]] && args+=(--bulk)'
if bulk_forward not in shell:
    forward_anchor = '      (( AUTO )) && args+=(--auto)'
    if shell.count(forward_anchor) != 1:
        sys.exit("Bulk re-sign patch: cannot identify child refresh loop")
    shell = shell.replace(forward_anchor, forward_anchor + '\n' + bulk_forward, 1)

old = '''  if [[ "$status" == missing ]]; then
    rm -f "$EXPIRY"
    FORCE=1
    log "NOT INSTALLED on device; attempting a fresh installation"
  elif [[ "$status" == unknown ]]; then'''
auto_only = '''  if [[ "$status" == missing ]]; then
    rm -f "$EXPIRY"
    if (( AUTO )); then
      log "NOT INSTALLED on device; automatic renewal skipped"
      record missing "automatic renewal never reinstalls a removed app"
      exit 0
    fi
    FORCE=1
    log "NOT INSTALLED on device; attempting a fresh installation"
  elif [[ "$status" == unknown ]]; then'''
bulk_safe = '''  if [[ "$status" == missing ]]; then
    rm -f "$EXPIRY"
    if (( AUTO )); then
      log "NOT INSTALLED on device; automatic renewal skipped"
      record missing "automatic renewal never reinstalls a removed app"
      exit 0
    elif (( BULK )); then
      log "NOT INSTALLED on device; bulk re-sign skipped"
      record missing "bulk re-sign never reinstalls a removed app"
      exit 0
    fi
    FORCE=1
    log "NOT INSTALLED on device; attempting a fresh installation"
  elif [[ "$status" == unknown ]]; then'''
if bulk_safe not in shell:
    candidate = auto_only if auto_only in shell else old
    if shell.count(candidate) != 1:
        sys.exit("Bulk re-sign patch: unrecognized missing-app guard")
    shell = shell.replace(candidate, bulk_safe, 1)

# Fail closed for bulk/automatic work when the device inventory cannot be read.
unknown_anchor = '''  elif [[ "$status" == unknown ]]; then
    log "WARNING: cannot verify app inventory; do not assume it is installed"'''
unknown_safe = '''  elif [[ "$status" == unknown ]]; then
    if (( AUTO || BULK )); then
      log "Cannot verify installed-app inventory; renewal skipped"
      record unknown "installed-app inventory could not be verified"
      exit 0
    fi
    log "WARNING: cannot verify app inventory; do not assume it is installed"'''
if unknown_safe not in shell:
    if shell.count(unknown_anchor) != 1:
        sys.exit("Bulk re-sign patch: cannot identify unknown-inventory guard")
    shell = shell.replace(unknown_anchor, unknown_safe, 1)
refresh.write_text(shell)

# Present the fixed policy accurately and remove the obsolete day selector.
index = checkout / "sideloop" / "index.html"
page = index.read_text()
page = page.replace('S.config.renew_before_days * 86400', '6 * 60 * 60')
page = page.replace('const window = c.renew_before_days * 86400,',
                    'const window = 6 * 60 * 60,')
page = re.sub(
    r'\n\s*<div class="cell ind">\$\{tile\("var\(--orange\)", "time-outline"\)\}<label for="rb".*?\n\s*<span class="chev">\$\{ic\("chevron-forward", 16\)\}</span></div>',
    '', page, count=1, flags=re.S)
page = page.replace(
    'Automatic renewal is a preference, not a setup step. Enable it after the first successful manual install. Signing pauses on a failed attempt.',
    'Automatically re-signs every installed app with less than 6 days remaining. Enable it after the first successful manual install. Signing pauses on a failed attempt.')
# Builds reuse the patched checkout; update the earlier six-hour wording too.
page = page.replace('every installed app with less than 6 hours remaining.',
                    'every installed app with less than 6 days remaining.')
index.write_text(page)
print("SideLoader automatic renewal installed: all due apps, six-day threshold, source updates.")
