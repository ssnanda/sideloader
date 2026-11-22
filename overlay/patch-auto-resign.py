#!/usr/bin/env python3
"""Install the canonical six-hour automatic renewal scheduler."""
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
old = '''  if [[ "$status" == missing ]]; then
    rm -f "$EXPIRY"
    FORCE=1
    log "NOT INSTALLED on device; attempting a fresh installation"
  elif [[ "$status" == unknown ]]; then'''
new = '''  if [[ "$status" == missing ]]; then
    rm -f "$EXPIRY"
    if (( AUTO )); then
      log "NOT INSTALLED on device; automatic renewal skipped"
      record missing "automatic renewal never reinstalls a removed app"
      exit 0
    fi
    FORCE=1
    log "NOT INSTALLED on device; attempting a fresh installation"
  elif [[ "$status" == unknown ]]; then'''
if new not in shell:
    if shell.count(old) != 1:
        sys.exit(f"Auto re-sign patch missing-app guard: expected one anchor, got {shell.count(old)}")
    shell = shell.replace(old, new, 1)
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
    'Automatically re-signs every installed app with less than 6 hours remaining. Enable it after the first successful manual install. Signing pauses on a failed attempt.')
index.write_text(page)
print("SideLoader automatic renewal installed: all due apps, six-hour threshold.")
