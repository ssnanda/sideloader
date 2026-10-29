"""No-network tests for SideLoader's 2FA UI and PTY code submission hardening."""
from pathlib import Path
import importlib.util
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PATCHER = ROOT / 'overlay' / 'patch-apple-2fa-safety.py'

JOBS = '''import os
import re
import threading
import secrets
import time
from . import config
MASK = "••••••••"
ANSI = re.compile(r"\\x1b\\[[0-9;?]*[ -/]*[@-~]")
PROMPT = re.compile(r"two.?factor code|verification code|enter (the )?(2fa |verification )?code", re.I)
PROGRESS = re.compile(r"^(Signing|Installation) Progress:\\s*([0-9.eE+-]+)")
SECRET = re.compile(r"^X-(Apple|Mme|MMe)-")
NOISE = re.compile(r"^Writing File: ")
MAX_LINE=400

def hidden(line):
    return bool(PROGRESS.match(line) or NOISE.match(line) or SECRET.search(line) or len(line)>MAX_LINE)

def redact(lines):
    secret = config.read()["APPLE_PASSWORD"]
    return [ln.replace(secret, MASK) if secret else ln for ln in lines if not hidden(ln)]

class Job:
    def __init__(self, kind, title):
        self.id, self.kind, self.title = secrets.token_hex(4), kind, title
        self.started, self.ended, self.rc = time.time(), None, None
        self.lines, self.partial, self.needs_input = [], "", False
        self.fd = None
        self.lock = threading.Lock()
        self.secret = config.read()["APPLE_PASSWORD"]
    @property
    def running(self):
        return self.ended is None
    def _track(self, t):
        pass
    def add(self, text):
        text = ANSI.sub("", text)
        if self.secret:
            text = text.replace(self.secret, MASK)
        with self.lock:
            buf = (self.partial + text).replace("\\r\\n", "\\n").replace("\\r", "\\n")
            *done, self.partial = buf.split("\\n")
            for line in done:
                t = line.strip()
                if not t:
                    continue
                self._track(t)
                if hidden(t):
                    continue
                self.lines.append(line.rstrip())
                if len(t) < 160 and PROMPT.search(t):
                    self.needs_input = True
            if len(self.partial) < 160 and PROMPT.search(self.partial):
                self.needs_input = True
            self.lines = self.lines[-1500:]
    def send(self, text):
        if self.fd is None:
            raise RuntimeError("this step doesn't take input")
        with self.lock:
            self.needs_input = False
            self.lines.append((self.partial.strip() + " ••••••").strip())
            self.partial = ""
        os.write(self.fd, (text.strip() + "\\n").encode())
'''
PAGE = '''<html><script>
const sheetHost = document.body;
const $ = x => document.querySelector(x);
function show(){ return `<input class="code" id="code" inputmode="numeric" autocomplete="one-time-code" maxlength="6" placeholder="••••••" autofocus>`; }
sheetHost.addEventListener("submit", e => {
  e.preventDefault();
  const v = $("#code").value.trim(); if (!v) return;
  act(() => api("/api/job/input", {json:{text:v}}));
});
</script></html>
'''

class TwoFactorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        pkg=self.base/'sideloop'; pkg.mkdir()
        (pkg/'jobs.py').write_text(JOBS)
        (pkg/'index.html').write_text(PAGE)
        self.cmd=[sys.executable,str(PATCHER),str(self.base)]

    def patched(self):
        result=subprocess.run(self.cmd,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr+result.stdout)
        return self.base/'sideloop'

    def test_repeatable_and_no_login(self):
        pkg=self.patched()
        before=[(pkg/'jobs.py').read_text(),(pkg/'index.html').read_text()]
        pkg=self.patched()
        self.assertEqual(before,[(pkg/'jobs.py').read_text(),(pkg/'index.html').read_text()])
        self.assertIn('pattern="[0-9]{6}"',before[1])
        self.assertIn('only prompt when verification input is requested', PATCHER.read_text())
        self.assertIn('enter|type|provide', before[0])
        self.assertIn('button.disabled = true',before[1])
        self.assertIn('verification_deadline',before[0])
        self.assertIn('time.monotonic() + 60',before[0])
        self.assertIn('input.value = ""',before[1])
        self.assertNotIn('AltServer',before[0])

    def test_rejects_unknown_ui_without_partial_write(self):
        pkg=self.base/'sideloop'
        (pkg/'index.html').write_text('unexpected UI')
        result=subprocess.run(self.cmd,capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0)
        self.assertEqual((pkg/'jobs.py').read_text(),JOBS)

    def test_backend_requires_one_six_digit_code_at_real_prompt(self):
        pkg=self.patched()
        package=types.ModuleType('fake_two_factor');package.__path__=[str(pkg)]
        config=types.ModuleType('fake_two_factor.config')
        config.read=lambda:{'APPLE_PASSWORD':'passphrase'}
        sys.modules.update({'fake_two_factor':package,'fake_two_factor.config':config})
        self.addCleanup(lambda:sys.modules.pop('fake_two_factor.jobs',None))
        self.addCleanup(lambda:sys.modules.pop('fake_two_factor.config',None))
        self.addCleanup(lambda:sys.modules.pop('fake_two_factor',None))
        spec=importlib.util.spec_from_file_location('fake_two_factor.jobs',pkg/'jobs.py')
        module=importlib.util.module_from_spec(spec)
        sys.modules[spec.name]=module
        spec.loader.exec_module(module)
        job=module.Job('refresh','Install test')
        job.fd=42
        with patch.object(module.os,'write') as send:
            for invalid in ('12','12345','1234567','abcdef','12 3456','12345\nmore'):
                with self.assertRaises(ValueError): job.send(invalid)
            with self.assertRaises(RuntimeError):job.send('123456')
            job.add('Apple already sent a verification code to trusted devices (hsc 409).\n')
            self.assertFalse(job.needs_input)
            job.add('Enter verification code: ')
            self.assertTrue(job.needs_input)
            self.assertIsNotNone(job.verification_deadline)
            self.assertGreater(job.verification_deadline - module.time.monotonic(), 50)
            job.send('123456')
            self.assertIsNone(job.verification_deadline)
            send.assert_called_once_with(42,b'123456\n')
            with self.assertRaises(RuntimeError):job.send('123456')
            job.add('123')
            job.add('456\r\n')  # chunks straddle the code boundary
            self.assertNotIn('123456','\n'.join(job.lines)+job.partial)
            self.assertIn('••••••••','\n'.join(job.lines))
            self.assertNotIn('123456',str(module.redact(['verification code: 123456'])))
        auto=module.Job('auto','Automatic')
        auto.fd=42
        auto.needs_input=True
        with self.assertRaises(RuntimeError):auto.send('123456')

    def test_frontend_javascript_syntax(self):
        pkg=self.patched()
        html=(pkg/'index.html').read_text()
        script=html.split('<script>',1)[1].split('</script>')[0]
        try: result=subprocess.run(['node','--check'],input=script,text=True,capture_output=True)
        except FileNotFoundError:self.skipTest('node not installed')
        self.assertEqual(result.returncode,0,result.stderr)

if __name__=='__main__':unittest.main()