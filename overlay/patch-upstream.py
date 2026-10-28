#!/usr/bin/env python3
"""Idempotently extend Sideloop's protected API with an AltStore sources page."""
import sys
from pathlib import Path

if len(sys.argv) != 3:
    sys.exit("Usage: patch-upstream.py <upstream-repo> <starter-dir>")
repo, starter = Path(sys.argv[1]), Path(sys.argv[2])
# Dockerfile signing compatibility is handled by patch-v2.py only.
target = repo / "sideloop" / "server.py"
original = target.read_text()
mark = "# MiniSideload source integration v1"
if mark not in original:
    replacements = [
        ("from . import auth, config, ipa, pairing, store",
         "from . import auth, config, ipa, pairing, store\n" + mark + "\nfrom .sources import Sources"),
        ("self.jobs, self.health, self.muxers = jobs, health, muxers",
         "self.jobs, self.health, self.muxers = jobs, health, muxers\n        self.sources = Sources()"),
        ('"/api/job/cancel": self.job_cancel,',
         '"/api/job/cancel": self.job_cancel,\n            "/api/sources/add": self.sources.add,\n            "/api/sources/remove": self.sources.remove,\n            "/api/sources/install": lambda data: self.sources.install(data, self),'),
        ('if path in ("/", "/index.html"):',
         'if path == "/sources":\n'
         '                if not self.authed():\n'
         '                    return self.send(302, b"", "text/plain", [("Location", "/")])\n'
         '                return self.send(200, Path(__file__).with_name("sources.html").read_bytes(), "text/html; charset=utf-8", [("Content-Security-Policy", CSP)])\n'
         '            if path in ("/", "/index.html"):'),
        ('if path == "/api/state":',
         'if path == "/api/sources":\n'
         '                return self.send(200, app.sources.list())\n'
         '            if path == "/api/state":'),
    ]
    edited = original
    for old, new in replacements:
        count = edited.count(old)
        if count != 1:
            sys.exit(f"Upstream Sideloop changed: expected one occurrence of {old!r}, found {count}; no patch applied")
        edited = edited.replace(old, new, 1)
    target.write_text(edited)
    print("Patched protected Sideloop API for AltStore sources.")
else:
    print("Sources API patch already applied.")

for f, dest in (("sources.py", "sources.py"), ("sources.html", "sources.html")):
    (repo / "sideloop" / dest).write_bytes((starter / f).read_bytes())

# Add a link to Sources without disturbing native Sideloop JavaScript.
index = repo / "sideloop" / "index.html"
page = index.read_text()
if 'id="minisideload-link"' not in page:
    anchor = "</body>"
    if page.count(anchor) != 1:
        sys.exit("Sideloop index.html changed: cannot place Sources link")
    addition = '<a id="minisideload-link" href="/sources" style="position:fixed;z-index:12;right:10px;bottom:calc(65px + env(safe-area-inset-bottom));background:#007aff;color:white;padding:8px 13px;border-radius:18px;font:600 13px system-ui;text-decoration:none;box-shadow:0 2px 10px #0004">Sources</a>\n'
    index.write_text(page.replace(anchor, addition + anchor))
