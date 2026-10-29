#!/usr/bin/env python3
"""Harden the existing AltServer 6-digit 2FA prompt without extra Apple requests.

Idempotent against a persistent patched Sideloop checkout. Changes only PTY
input validation, ephemeral output masking and the existing browser prompt.
Does not modify AltSign/AltServer, provisioning data, sign-in state or cookies.
"""
from pathlib import Path
import sys

if len(sys.argv) != 2:
    sys.exit('Usage: patch-apple-2fa-safety.py <sideloop-checkout>')
root = Path(sys.argv[1]) / 'sideloop'
job_file = root / 'jobs.py'
page_file = root / 'index.html'
jobs, page = job_file.read_text(), page_file.read_text()


def change(source, old, new, label):
    if new in source:
        return source
    matches = source.count(old)
    if matches != 1:
        sys.exit(f'2FA safety patch {label}: expected 1 anchor, found {matches}')
    return source.replace(old, new, 1)

# Do not mistake Apple's notification that it already sent a code for
# AltServer actually waiting for terminal input.
jobs = change(jobs,
    'PROMPT = re.compile(r"two.?factor code|verification code|enter (the )?(2fa |verification )?code", re.I)',
    'PROMPT = re.compile(r"(?:enter|type|provide)\\s+(?:(?:the|your)\\s+)?(?:(?:two[ -]?factor|2fa|verification|security)\\s+)?code\\b|^\\s*(?:two[ -]?factor|2fa|verification)\\s+code\\s*[:>]\\s*$", re.I)',
    'only prompt when verification input is requested')

jobs = change(jobs,
    'MASK = "••••••••"',
    'MASK = "••••••••"\n# A six-digit code may be echoed by the interactive terminal, even when the\n# app deliberately masks the input itself. Never expose one in job state.\nOTP_ECHO = re.compile(r"(?<![0-9])\\d{6}(?![0-9])")',
    'masked six-digit codes')

jobs = change(jobs,
    'return [ln.replace(secret, MASK) if secret else ln for ln in lines if not hidden(ln)]',
    'return [OTP_ECHO.sub(MASK, ln.replace(secret, MASK) if secret else ln)\n            for ln in lines if not hidden(ln)]',
    'saved-log redaction')

jobs = change(jobs,
    'buf = (self.partial + text).replace("\\r\\n", "\\n").replace("\\r", "\\n")',
    'buf = OTP_ECHO.sub(MASK, (self.partial + text).replace("\\r\\n", "\\n").replace("\\r", "\\n"))',
    'PTY echo redaction before lines are exposed')

jobs = change(jobs,
    '''    def send(self, text):
        if self.fd is None:
            raise RuntimeError("this step doesn't take input")
        with self.lock:
            self.needs_input = False
            self.lines.append((self.partial.strip() + " ••••••").strip())
            self.partial = ""
        os.write(self.fd, (text.strip() + "\\n").encode())''',
    '''    def send(self, text):
        # This endpoint is exclusively for an active 2FA challenge. Never feed
        # arbitrary text to a job's terminal or accept a second submission.
        code = text.strip()
        if not re.fullmatch(r"[0-9]{6}", code):
            raise ValueError("Enter exactly six digits from the Apple verification prompt")
        with self.lock:
            if self.kind != "refresh" or not self.running or self.fd is None or not self.needs_input:
                raise RuntimeError("No Apple verification code is currently requested")
            fd = self.fd
            self.needs_input = False
            self.lines.append("Apple verification code submitted [redacted]")
            self.partial = ""
        os.write(fd, (code + "\\n").encode())''',
    'validate and serialize one 2FA submission')

page = change(page,
    '<input class="code" id="code" inputmode="numeric" autocomplete="one-time-code" maxlength="6" placeholder="••••••" autofocus>',
    '<input class="code" id="code" type="text" inputmode="numeric" autocomplete="one-time-code" minlength="6" maxlength="6" pattern="[0-9]{6}" required spellcheck="false" placeholder="••••••" autofocus>',
    '6-digit browser input attributes')
page = change(page,
    '''  const v = $("#code").value.trim(); if (!v) return;
  act(() => api("/api/job/input", {json:{text:v}}));''',
    '''  const input = $("#code");
  if (!input) return;
  const v = input.value.trim();
  if (!/^[0-9]{6}$/.test(v)) return toast("Enter the six-digit Apple verification code.");
  input.value = ""; // never leave a submitted OTP visible in the DOM
  const button = sheetHost.querySelector("#askf button");
  if (button) button.disabled = true; // one submission, not repeat taps
  act(() => api("/api/job/input", {json:{text:v}}));''',
    'validate and clear 2FA browser prompt')

page = change(page,
    '<h2>Verification Code</h2><p>Enter the code sent to your Apple devices.</p>',
    '<h2>Apple Verification Code</h2><p>Apple sends the six-digit code to your trusted devices when this sign-in reaches verification. Enter it here to continue this same installation attempt.</p>',
    'explain code delivery at active 2FA prompt')

# No partial application on unknown layouts.
job_file.write_text(jobs)
page_file.write_text(page)
print('Apple 2FA prompt hardened: six-digit validation, one submission, echoed-code masking (no authentication attempted).')