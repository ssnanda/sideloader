#!/usr/bin/env python3
"""Upgrade SideLoader's responsive desktop layout without touching runtime data.

This runs AFTER the version-display and Install Step overlays. The patch is
idempotent for persistent, already patched sideloop checkouts.
"""
from pathlib import Path
import sys

if len(sys.argv) != 2:
    sys.exit('Usage: patch-responsive-ui.py <sideloop-checkout>')
page = Path(sys.argv[1]) / 'sideloop' / 'index.html'
source = page.read_text()


def replace_exact(old, new, label):
    global source
    if new in source:
        return
    matches = source.count(old)
    if matches != 1:
        sys.exit(f'Responsive layout patch {label}: expected 1 anchor, found {matches}')
    source = source.replace(old, new, 1)


replace_exact(
    '<div class="cell ind"><span class="k">Installed backend<span class="sub">',
    '<div class="cell ind sideloader-backend-row"><span class="k">Installed backend<span class="sub">',
    'backend version row')
replace_exact(
    '<span>${version}</span><a class="cap" href="https://github.com/jaakkopalvaila/AltServer-Linux/tree/ng"',
    '<div class="sideloader-backend-controls"><span class="sideloader-backend-version">${version}</span><a class="cap" href="https://github.com/jaakkopalvaila/AltServer-Linux/tree/ng"',
    'backend version/actions grouping')
replace_exact(
    '${altserverChecking ? "Checking…" : "Check for updates"}</button></div>',
    '${altserverChecking ? "Checking…" : "Check for updates"}</button></div></div>',
    'backend controls wrapper')

css_marker = '/* SideLoader responsive desktop layout v1 */'
if css_marker not in source:
    if source.count('</style>') != 1:
        sys.exit('Responsive layout patch: cannot safely identify stylesheet')
    css = '''
/* SideLoader responsive desktop layout v1 */
/* Keep the existing iPhone-first appearance, but use desktop viewport space. */
@media (min-width: 900px) {
  .page { width: 100%; max-width: 1360px; margin-inline: auto; padding-inline: 32px; box-sizing: border-box; }
  .tabbar .in { max-width: 1360px; }
  .setup-step>summary { padding: 17px 20px; }
  .setup-step { margin-bottom: 13px; }
}
@media (min-width: 1700px) {
  .page { max-width: 1600px; }
  .tabbar .in { max-width: 1600px; }
}
@media (min-width: 2200px) {
  .page { max-width: 1900px; }
  .tabbar .in { max-width: 1900px; }
}
/* Never squeeze the version, source links, and check button into one row. */
.sideloader-backend-row {
  display: grid;
  grid-template-columns: minmax(160px, 1fr) minmax(0, 2fr);
  align-items: center;
  gap: 12px;
  min-width: 0;
}
.sideloader-backend-row>.k { min-width: 0; overflow-wrap: anywhere; }
.sideloader-backend-controls {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  min-width: 0;
}
.sideloader-backend-version { font-size: 14px; font-weight: 600; overflow-wrap: anywhere; }
.sideloader-backend-controls>.cap { text-decoration: none; min-height: 36px; box-sizing: border-box; font-size: 13px; }
.sideloader-backend-row .sub { overflow-wrap: anywhere; }
@media (max-width: 840px) {
  .sideloader-backend-row { grid-template-columns: minmax(0, 1fr); }
  .sideloader-backend-controls { justify-content: flex-start; }
}
@media (max-width: 540px) {
  .sideloader-backend-row { padding: 13px 12px; }
  .sideloader-backend-controls { gap: 7px; }
}
'''
    source = source.replace('</style>', css + '\n</style>', 1)
page.write_text(source)
print('Responsive desktop layout applied; backend version actions wrap safely.')