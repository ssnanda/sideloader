#!/usr/bin/env python3
"""Add the Android (APK over Wireless-debugging ADB) mode to the Apps page.

Run AFTER every other overlay (it relies on the unified Apps view and the
Sources API). Idempotent against the persistent build/sideloop checkout:
marker-delimited UI/CSS blocks are refreshed on each build. Never touches
/data, Apple credentials, pairing records or signing state.
"""
from pathlib import Path
import sys

if len(sys.argv) != 3:
    sys.exit('Usage: patch-android.py <sideloop-checkout> <overlay-dir>')
checkout, overlays = Path(sys.argv[1]), Path(sys.argv[2])
server_path = checkout / 'sideloop' / 'server.py'
index_path = checkout / 'sideloop' / 'index.html'
docker_path = checkout / 'Dockerfile'
s, h, d = server_path.read_text(), index_path.read_text(), docker_path.read_text()


def fail(label, detail):
    sys.exit(f'Android patch {label}: {detail}; nothing was written')


def once(source, old, new, label, present=None):
    if (present or new) in source:
        return source
    if source.count(old) != 1:
        fail(label, f'expected one anchor, got {source.count(old)}')
    return source.replace(old, new, 1)


def block(source, start, end, content, anchor, label, offset=0):
    """Replace a marker-delimited block, or insert it once at anchor."""
    if source.count(start) > 1 or source.count(end) > 1:
        fail(label, 'duplicate markers')
    a = source.find(start)
    if a >= 0:
        b = source.find(end, a)
        if b < 0:
            fail(label, 'unterminated block')
        return source[:a] + content + source[b + len(end):]
    if source.count(anchor) != 1:
        fail(label, f'expected one insertion point, got {source.count(anchor)}')
    i = source.index(anchor) + offset
    return source[:i] + content + source[i:]


def scoped(source, start, end, anchor, addition, present, label, after=False):
    if source.count(start) != 1:
        fail(label, 'ambiguous handler boundaries')
    a = source.index(start)
    b = source.find(end, a + len(start))
    if b < 0:
        fail(label, 'missing handler end')
    section = source[a:b]
    if present in section:
        return source
    if section.count(anchor) != 1:
        fail(label, f'expected one insertion point, got {section.count(anchor)}')
    section = section.replace(anchor, anchor + addition if after else addition + anchor, 1)
    return source[:a] + section + source[b:]


# --- server.py -------------------------------------------------------------
if 'self.sources = Sources()' not in s:
    fail('server', 'Sources API overlay missing (run patch-upstream.py first)')
if 'from . import android\n' not in s:
    s = once(s, 'from . import auth, config, ipa, pairing, store\n',
             'from . import auth, config, ipa, pairing, store\nfrom . import android\n', 'import')
s = scoped(s, '    def routes(self):', '\n\ndef handler(app):', '        return {\n',
           '''            "/api/android/pair": android.pair,
            "/api/android/connect": android.connect,
            "/api/android/disconnect": android.disconnect,
            "/api/android/install": lambda data: android.install(data, self.sources._urls()),
            "/api/android/repos/add": android.add_repo,
            "/api/android/repos/remove": android.remove_repo,
''', '"/api/android/pair"', 'POST routes', after=True)
s = scoped(s, '        def do_GET(self):', '        def do_POST(self):', '            self.error(404, "not found")',
           '''            if path.startswith("/api/android/"):
                q = urllib.parse.parse_qs(query)
                try:
                    if path == "/api/android/state":
                        return self.send(200, android.state())
                    if path == "/api/android/catalog":
                        return self.send(200, android.catalog(app.sources._urls(), q.get("force") == ["1"]))
                    if path == "/api/android/installed":
                        return self.send(200, android.installed({"device": q.get("device", [""])[0]}))
                except RuntimeError as e:
                    return self.error(409, str(e))
                except ValueError as e:
                    return self.error(400, str(e))
''', 'if path.startswith("/api/android/"):', 'GET routes')

# --- index.html ------------------------------------------------------------
if 'function appsView() {' not in h or '\nfunction wire() {' not in h:
    fail('dashboard', 'Apps view or wire() not found')
ui = (overlays / 'android-ui.js').read_text().rstrip('\n') + '\n'
h = block(h, '/* SideLoader Android v1 start */', '/* SideLoader Android v1 end */\n', ui,
          '\nfunction wire() {', 'UI helpers', offset=1)
h = once(h, 'function appsView() {\n',
         'function appsView() {\n  if (!slPlatformInner) return slPlatformView(); /* SideLoader Android switch */\n',
         'Apple/Android switch', present='/* SideLoader Android switch */')
h = once(h, '\nfunction wire() {\n',
         '\nfunction wire() {\n  androidWire(); /* SideLoader Android wire */\n',
         'event wiring', present='/* SideLoader Android wire */')
css = (overlays / 'android.css').read_text().rstrip('\n') + '\n'
h = block(h, '/* SideLoader Android v1 css start */', '/* SideLoader Android v1 css end */\n', css,
          '<style>\n', 'CSS', offset=len('<style>\n'))

# --- Dockerfile: Debian's adb (platform-tools 34; supports `adb pair`) -----
apt = 'coreutils tzdata \\\n'
if ' adb ' not in d.split('&& rm -rf /var/lib/apt/lists/*', 1)[0]:
    d = once(d, apt, 'coreutils tzdata adb \\\n', 'Dockerfile adb package')

# Only write when every anchor was validated.
server_path.write_text(s)
index_path.write_text(h)
docker_path.write_text(d)
(checkout / 'sideloop' / 'android.py').write_bytes((overlays / 'android.py').read_bytes())
print('Android APK mode (Wireless-debugging ADB, GitHub release APKs) applied (repeatable).')
