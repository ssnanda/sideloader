"""Verify new + previously-patched source, build provenance and account log."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
PATCH=ROOT/'overlay'/'patch-backend-info.py'
DOCKER='''ARG ALTSERVER_TAG=ng
FROM altserver-builder AS altserver
ARG ALTSERVER_TAG
ARG ALTSERVER_REV
RUN echo build
 && cd /src && test "$(git rev-parse HEAD)" = "$ALTSERVER_REV" && git apply /tmp/patches/*.patch
FROM debian:trixie-slim
COPY --from=altserver /AltServer /usr/local/bin/AltServer
'''
SERVER='''from .account import verification, save_account
class App:
    def signing_resume(self, data):
        return None

    def routes(self):
        return {
            "/api/signing/resume": self.signing_resume,
        }

    def state(self):
        return {
            "account_verification": verification(),
        }
'''
INDEX='''<html><script>
function settingsView() {
 return `
  <div class="setup-heading">SETTINGS · OPTIONAL</div>
  <div>Renewal</div>`;
}
</script></html>
'''
REFRESH='''#!/bin/bash
log "STAGE 3/4: Asking AltServer to sign and install. One 2FA code may be required."
log "signing and installing $(basename "$IPA_PATH") on $DEVICE_UDID"
timeout 2400 "$ALTSERVER_BIN" -u "$DEVICE_UDID" -a "$APPLE_ID" -p "$APPLE_PASSWORD" "$IPA_PATH"
'''
class PatchTests(unittest.TestCase):
    def test_new_and_repeat_build_preserve_original(self):
        with tempfile.TemporaryDirectory() as temp:
            checkout=Path(temp)
            (checkout/'sideloop').mkdir()
            (checkout/'scripts').mkdir()
            templates={'Dockerfile':DOCKER,'sideloop/server.py':SERVER,'sideloop/index.html':INDEX,'scripts/refresh.sh':REFRESH}
            for name,contents in templates.items():
                (checkout/name).write_text(contents)
            cmd=[sys.executable,str(PATCH),temp,str(ROOT/'overlay')]
            subprocess.run(cmd,check=True,capture_output=True,text=True)
            once={name:(checkout/name).read_text() for name in templates}
            self.assertIn('actual_rev="$(git rev-parse HEAD)"',once['Dockerfile'])
            self.assertIn('git fetch -q --depth 1 origin "$ALTSERVER_REV"',once['Dockerfile'])
            self.assertIn('git checkout -q --detach "$ALTSERVER_REV"',once['Dockerfile'])
            self.assertIn('COPY --from=altserver /AltServer-build.json',once['Dockerfile'])
            self.assertIn('"altserver_build": altserver_status()',once['sideloop/server.py'])
            self.assertIn('"/api/altserver/check-updates": self.altserver_check_updates',once['sideloop/server.py'])
            self.assertIn('altserverBackendCard()',once['sideloop/index.html'])
            self.assertIn('id="sideloader-altserver-updates"',once['sideloop/index.html'])
            self.assertIn('"Check for updates"',once['sideloop/index.html'])
            self.assertIn('https://github.com/jaakkopalvaila/AltServer-Linux/tree/ng',once['sideloop/index.html'])
            self.assertIn('https://github.com/jaakkopalvaila/AltServer-Linux/commits/ng',once['sideloop/index.html'])
            self.assertIn('GitHub source</a>',once['sideloop/index.html'])
            self.assertIn('Apple Account passed to AltServer (-a): ${APPLE_ID}',once['scripts/refresh.sh'])
            self.assertIn('"$APPLE_ID"',once['scripts/refresh.sh'])
            subprocess.run(cmd,check=True,capture_output=True,text=True)
            self.assertEqual(once,{name:(checkout/name).read_text() for name in templates})

    def test_rebuild_after_responsive_layout_keeps_links_and_version_controls(self):
        """Regression: responsive patch moved ${version} into a named span."""
        with tempfile.TemporaryDirectory() as temp:
            checkout = Path(temp)
            (checkout/'sideloop').mkdir()
            (checkout/'scripts').mkdir()
            templates = {
                'Dockerfile': DOCKER,
                'sideloop/server.py': SERVER,
                'sideloop/index.html': INDEX.replace(
                    '<html><script>', '<html><head><style>.page{max-width:680px}</style></head><script>'),
                'scripts/refresh.sh': REFRESH,
            }
            for name, contents in templates.items():
                (checkout/name).write_text(contents)
            patch = [sys.executable, str(PATCH), temp, str(ROOT/'overlay')]
            responsive = [sys.executable,
                          str(ROOT/'overlay'/'patch-responsive-ui.py'), temp]
            subprocess.run(patch, check=True, capture_output=True, text=True)
            subprocess.run(responsive, check=True, capture_output=True, text=True)
            page = checkout/'sideloop'/'index.html'
            before = page.read_text()
            self.assertIn('<span class="sideloader-backend-version">${version}</span>', before)
            self.assertIn('GitHub source</a>', before)
            self.assertIn('Recent commits</a>', before)
            for _ in range(2):
                rebuilt = subprocess.run(patch, capture_output=True, text=True)
                self.assertEqual(rebuilt.returncode, 0, rebuilt.stdout + rebuilt.stderr)
                self.assertIn('already installed', rebuilt.stdout)
                self.assertEqual(page.read_text(), before)
            self.assertEqual(before.count('GitHub source</a>'), 1)
            self.assertEqual(before.count('Recent commits</a>'), 1)
            self.assertEqual(before.count('id="sideloader-altserver-updates"'), 1)

    def test_partial_upstream_links_abort_without_duplicating_controls(self):
        with tempfile.TemporaryDirectory() as temp:
            checkout = Path(temp)
            (checkout/'sideloop').mkdir()
            (checkout/'scripts').mkdir()
            templates = {
                'Dockerfile': DOCKER, 'sideloop/server.py': SERVER,
                'sideloop/index.html': INDEX, 'scripts/refresh.sh': REFRESH,
            }
            for name, contents in templates.items():
                (checkout/name).write_text(contents)
            cmd = [sys.executable, str(PATCH), temp, str(ROOT/'overlay')]
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            page = checkout/'sideloop'/'index.html'
            modified = page.read_text().replace('GitHub source</a>', 'Missing source</a>')
            page.write_text(modified)
            result = subprocess.run(cmd, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('partially installed', result.stderr)
            self.assertEqual(page.read_text(), modified)

    def test_changed_dockerfile_fails_safe(self):
        with tempfile.TemporaryDirectory() as temp:
            checkout=Path(temp)
            (checkout/'sideloop').mkdir()
            (checkout/'scripts').mkdir()
            (checkout/'Dockerfile').write_text(DOCKER.replace('FROM debian:trixie-slim','FROM nonexistent'))
            proc=subprocess.run([sys.executable,str(PATCH),temp,str(ROOT/'overlay')],capture_output=True,text=True)
            self.assertNotEqual(proc.returncode,0)
            self.assertIn('expected 1 anchor',proc.stderr)

if __name__=='__main__': unittest.main()