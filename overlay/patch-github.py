#!/usr/bin/env python3
"""Add GitHub profile scanning routes to an existing SideLoader checkout.

Runs after the Sources, v2 and navigation overlays; safe on repeated builds.
"""
from pathlib import Path
import sys

if len(sys.argv) != 3:
    sys.exit('Usage: patch-github.py <sideloop-checkout> <overlay-dir>')
root, overlay = Path(sys.argv[1]), Path(sys.argv[2])
package = root / 'sideloop'
for file in ('github_sources.py', 'github_scan.py'):
    (package / file).write_bytes((overlay / file).read_bytes())
server = package / 'server.py'
source = server.read_text()


def patch(old, new, marker):
    global source
    if marker in source:
        return
    if source.count(old) != 1:
        sys.exit('Cannot safely add GitHub source feature: upstream route anchor changed')
    source = source.replace(old, new, 1)


patch('"/api/sources/install": lambda data: self.sources.install(data, self),',
      '"/api/sources/install": lambda data: self.sources.install(data, self),\n'
      '            "/api/sources/github/scan": self.sources.scan_github,\n'
      '            "/api/sources/github/disconnect": self.sources.disconnect_github,',
      '"/api/sources/github/scan": self.sources.scan_github')
patch('if path == "/api/sources":\n                return self.send(200, app.sources.list())',
      'if path == "/api/sources":\n                return self.send(200, app.sources.list())\n'
      '            if path == "/api/sources/github/status":\n'
      '                return self.send(200, app.sources.github_status())',
      'if path == "/api/sources/github/status":')
server.write_text(source)
print('GitHub account source scanning routes installed (repeatable).')