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


# AltServer's fatal error dialog waits for "Press any key to continue".
# Its CLI is running under a PTY, so without acknowledging that dialog the
# browser shows "Signing in to Apple" indefinitely after Apple has rejected
# authentication. Send one newline ONLY after an explicit fatal alert and
# the terminal's closing prompt; this is not another Apple login or 2FA entry.
if 'def run_pty(job, argv):' in jobs and 'job.add(data.decode("utf-8", "replace"))' in jobs:
    jobs = change(jobs,
        '    status = None\n    try:\n        while True:',
        '    status = None\n    fatal_dialog_buffer = ""\n    fatal_dialog_dismissed = False\n    try:\n        while True:',
        'track AltServer terminal failure')
    jobs = change(jobs,
        '                job.add(data.decode("utf-8", "replace"))',
        '''                decoded = data.decode("utf-8", "replace")
                job.add(decoded)
                # Include split PTY chunks, but retain only recent output.
                fatal_dialog_buffer = (fatal_dialog_buffer + decoded)[-8192:]
                if (not fatal_dialog_dismissed
                        and "Alert: Could not install" in fatal_dialog_buffer
                        and "Press any key to continue" in fatal_dialog_buffer):
                    fatal_dialog_dismissed = True
                    # Dismiss only AltServer's already-failed terminal dialog.
                    # This does not submit a code or start another attempt.
                    os.write(fd, b"\\n")
                    job.say("AltServer reported an installation error; closing its error dialog.")''',
        'dismiss AltServer fatal terminal dialog')

# A 60-second deadline begins only when the PTY actually requests a code.
# The deadline is enforced server-side, even when the browser is closed.
jobs = change(jobs,
    '        self.lines, self.partial, self.needs_input = [], "", False',
    '        self.lines, self.partial, self.needs_input = [], "", False\n'
    '        self.verification_deadline = None\n'
    '        self.timed_out_2fa = False',
    'verification timeout fields')
jobs = change(jobs,
    '            self.lines = self.lines[-1500:]',
    '            if self.needs_input and self.verification_deadline is None:\n'
    '                self.verification_deadline = time.monotonic() + 60\n'
    '            self.lines = self.lines[-1500:]',
    'start verification deadline')
jobs = change(jobs,
    '            self.needs_input = False\n            self.lines.append("Apple verification code submitted [redacted]")',
    '            self.needs_input = False\n            self.verification_deadline = None\n'
    '            self.lines.append("Apple verification code submitted [redacted]")',
    'clear verification deadline on submission')

if 'def run_pty(job, argv):' in jobs:
    jobs = change(jobs,
        '        while True:\n            if select.select([fd], [], [], 0.5)[0]:',
        '''        while True:
            with job.lock:
                timed_out = (job.kind == "refresh" and job.needs_input
                             and job.verification_deadline is not None
                             and time.monotonic() >= job.verification_deadline)
                if timed_out:
                    job.timed_out_2fa = True
                    job.needs_input = False
                    job.verification_deadline = None
            if timed_out:
                from . import retry_guard
                retry_guard.cancelled_2fa_timeout()
                job.say("Verification code not entered within 60 seconds. Signing cancelled locally.")
                try:
                    os.killpg(pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                break
            if select.select([fd], [], [], 0.5)[0]:''',
        'stop PTY on expired verification deadline')
    # Do not relabel a deliberate timeout as an AltServer failure.
    jobs = change(jobs,
        '    if job.rc and argv and argv[0] == "refresh.sh" and "--recheck" not in argv:',
        '    if job.rc and not job.timed_out_2fa and argv and argv[0] == "refresh.sh" and "--recheck" not in argv:',
        'keep cancellation separate from signing errors')
    # The shell's PTY path does not write AltServer's interactive errors into
    # its temporary output file. Preserve explicit Apple errors captured by
    # Job.lines instead of leaving the generic "install_failed" classification.
    # This only refines an existing failed reservation; it never retries login.
    jobs = change(jobs,
        '    if job.rc and not job.timed_out_2fa and argv and argv[0] == "refresh.sh" and "--recheck" not in argv:\n        from . import retry_guard\n        retry_guard.failed("\\n".join(job.lines[-100:]), job.rc)',
        '''    if not job.timed_out_2fa and argv and argv[0] == "refresh.sh" and "--recheck" not in argv:
        from . import retry_guard
        terminal = "\\n".join(job.lines[-150:])
        if job.rc or any(marker in terminal for marker in ("-36607", "-20209", "-80046", "-80045", "-22406")):
            retry_guard.failed(terminal, job.rc or 1)''',
        'preserve explicit Apple sign-in errors from PTY')

    jobs = change(jobs,
        '                "needs_input": self.needs_input, "accepts_input": self.fd is not None,',
        '                "needs_input": self.needs_input, "accepts_input": self.fd is not None,\n'
        '                "verification_seconds_remaining": max(0, int(self.verification_deadline - time.monotonic() + 0.999)) if self.verification_deadline is not None else None,',
        'show remaining verification time')

if '<form class="otp" id="askf">' in page:
    page = change(page,
        '<h2>Apple Verification Code</h2><p>Apple sends the six-digit code to your trusted devices when this sign-in reaches verification. Enter it here to continue this same installation attempt.</p>',
        '<h2>Apple Verification Code</h2><p>Enter the six-digit code sent to your trusted Apple device.</p><p id="sideloader-code-countdown">60 seconds remaining</p>',
        'show verification deadline')
    page = change(page,
        '  box._mode = mode; box._stage = j.stage;',
        '''  if (mode === "ask") {
    const countdown = sheetHost.querySelector("#sideloader-code-countdown");
    if (countdown && j.verification_seconds_remaining !== undefined && j.verification_seconds_remaining !== null)
      countdown.textContent = j.verification_seconds_remaining + " seconds remaining before cancellation";
  }
  box._mode = mode; box._stage = j.stage;''',
        'update 2FA countdown without resetting input')

# The unit-test fixture has only the input element, while the complete
# upstream dashboard includes the surrounding challenge explanation.
if '<h2>Verification Code</h2><p>Enter the code sent to your Apple devices.</p>' in page:
    page = change(page,
        '<h2>Verification Code</h2><p>Enter the code sent to your Apple devices.</p>',
        '<h2>Apple Verification Code</h2><p>Apple sends the six-digit code to your trusted devices when this sign-in reaches verification. Enter it here to continue this same installation attempt.</p>',
        'explain code delivery at active 2FA prompt')

# No partial application on unknown layouts.
job_file.write_text(jobs)
page_file.write_text(page)
print('Apple 2FA prompt hardened: six-digit validation, one submission, echoed-code masking (no authentication attempted).')