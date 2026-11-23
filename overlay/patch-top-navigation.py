#!/usr/bin/env python3
"""Install top-right Settings navigation and the authenticated roadmap page."""
from pathlib import Path
import sys

if len(sys.argv) != 3:
    sys.exit("Usage: patch-top-navigation.py <sideloop-checkout> <overlay-dir>")
root, overlay = Path(sys.argv[1]), Path(sys.argv[2])
package = root / "sideloop"
(package / "roadmap.html").write_bytes((overlay / "roadmap.html").read_bytes())

server = package / "server.py"
source = server.read_text()
route = '''            if path == "/roadmap":
                if not self.authed():
                    return self.send(302, b"", "text/plain", [("Location", "/")])
                return self.send(200, Path(__file__).with_name("roadmap.html").read_bytes(), "text/html; charset=utf-8", [("Content-Security-Policy", CSP)])
'''
if 'if path == "/roadmap":' not in source:
    anchor = '            if path == "/sources":\n'
    if source.count(anchor) != 1:
        sys.exit("Top navigation patch: roadmap route anchor changed")
    source = source.replace(anchor, route + anchor, 1)
server.write_text(source)

index = package / "index.html"
page = index.read_text()
marker = "/* SideLoader top Settings navigation v1 */"
if marker not in page:
    old = '<div class="r"><button class="navbtn" id="signout">Sign Out</button></div>'
    new = '''<div class="r sl-top-actions">
      <span class="sl-nav-version">${esc(S.sideloop_build?.side_loader_version || "unknown")}</span>
      <details class="sl-settings-menu"><summary>Settings</summary><nav><a href="/sources">Sources</a><a href="/roadmap">Roadmap</a></nav></details>
      <button class="navbtn" id="signout">Sign Out</button></div>'''
    if page.count(old) != 1:
        sys.exit(f"Top navigation patch: expected one Sign Out header, got {page.count(old)}")
    page = page.replace(old, new, 1)
    css = '''
/* SideLoader top Settings navigation v1 */
.sl-top-actions{gap:8px!important;right:max(12px,calc(50% - 650px))!important}
.sl-nav-version{color:var(--label-2);font-size:12px;font-weight:600;white-space:nowrap}
.sl-settings-menu{position:relative;color:var(--blue)}
.sl-settings-menu summary{list-style:none;cursor:pointer;padding:8px;font-size:15px}
.sl-settings-menu summary::-webkit-details-marker{display:none}
.sl-settings-menu nav{position:absolute;right:0;top:100%;min-width:170px;padding:7px;background:var(--cell);border:1px solid var(--sep);border-radius:12px;box-shadow:0 12px 34px rgba(0,0,0,.18)}
.sl-settings-menu nav a{display:block;padding:10px 12px;border-radius:8px;color:var(--blue);text-decoration:none;font-size:14px}
.sl-settings-menu nav a:hover,.sl-settings-menu nav a:focus{background:var(--fill)}
@media(hover:hover){.sl-settings-menu:hover nav{display:block}.sl-settings-menu:not(:hover):not([open]) nav{display:none}}
@media(max-width:600px){.sl-top-actions{right:8px!important;gap:2px!important}.sl-nav-version{font-size:10px}.sl-settings-menu summary,.sl-top-actions .navbtn{font-size:13px;padding:7px 5px}}
'''
    if page.count("</style>") != 1:
        sys.exit("Top navigation patch: stylesheet boundary changed")
    page = page.replace("</style>", css + "\n</style>", 1)
index.write_text(page)
# Install the optional remote server after the Apple 2FA and screen-flow
# patches. This preserves their expected job and UI anchors on repeat builds.
from remote_server_patch import apply as apply_remote_server
apply_remote_server(root, overlay)

print("Top Settings menu and authenticated Roadmap installed.")
