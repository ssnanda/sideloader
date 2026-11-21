#!/usr/bin/env python3
"""Make Step 2 evidence-based; never verify an Apple Account by saving secrets."""
from pathlib import Path
import sys

if len(sys.argv) != 2:
    sys.exit("Usage: patch-apple-verification.py <sideloop-checkout>")
root = Path(sys.argv[1])


def replace(path, before, after, label):
    s = path.read_text()
    if after in s:
        return
    count = s.count(before)
    if count != 1:
        sys.exit(f"Apple account status patch {label}: expected 1 anchor, got {count}")
    path.write_text(s.replace(before, after, 1))


server = root / "sideloop" / "server.py"
if 'from .account import verification, save_account' not in server.read_text():
    replace(server,
        "from . import retry_guard",
        "from . import retry_guard\nfrom .account import verification, save_account",
        "account imports")
replace(server,
    '            "signing_guard": retry_guard.status(),',
    '            "signing_guard": retry_guard.status(),\n'
    '            "account_verification": verification(),',
    "account state")
start = '    def apple_id(self, data):'
stop = '    def settings(self, data):'
source = server.read_text()
if '        return save_account(self, data)' not in source:
    if source.count(start) != 1 or source.count(stop) != 1:
        sys.exit("Apple Account handler changed; no migration applied")
    first = source.index(start)
    last = source.index(stop, first)
    updated = source[:first] + (
        '    def apple_id(self, data):\n'
        '        return save_account(self, data)\n\n'
    ) + source[last:]
    server.write_text(updated)

watcher = root / "sideloop" / "watcher.py"
replace(watcher,
    "from . import config, store, retry_guard",
    "from . import config, store, retry_guard\nfrom .account import is_verified",
    "scheduler import")
replace(watcher,
    '            job = self.jobs.claim_auto()',
    '''            # Do not send background Apple authentication requests when an
            # account has merely been saved but has never signed successfully.
            if not is_verified():
                with self.lock:
                    self.queue.clear()
                self.schedule()
                continue
            job = self.jobs.claim_auto()''',
    "disable unverified automatic sign-in")

shell = root / "scripts" / "refresh.sh"
# patch-one-attempt.py later inserts its success line right after the same
# anchor, so detect this insertion by its own line, not by adjacency.
if 'python3 -m sideloop.account verified' not in shell.read_text():
  replace(shell,
    'log "OK $msg"; record ok "$msg"',
    '''log "OK $msg"; record ok "$msg"
  # Only a verified installation proves the account worked with AltServer.
  python3 -m sideloop.account verified || log "WARNING: could not persist account verification status"''',
    "remember verified account only after installation")

index = root / "sideloop" / "index.html"
replace(index,
    '  const appleDone = Boolean(c.apple_id && c.has_password);',
    '''  const appleInfo = S.account_verification || {};
  const appleDone = Boolean(c.apple_id && c.has_password && appleInfo.state === "verified");''',
    "Step 2 completion must be verified")
# An existing unified Apps dashboard deliberately uses a shorter Step 2
# subtitle, but still depends on the verified Apple account state. Never
# regress that newer layout or require the original pre-migration caption.
page = index.read_text()
compact_step2 = ('/* SideLoader unified iPhone Apps step v1 */' in page
                 and '${renderSetupStep(2, "Apple Account", appleDone ? "Verified"' in page
                 and 'appleInfo.state === "failed"' in page)
if not compact_step2:
    replace(index,
        'appleDone ? "Credentials saved · not verified with Apple" : "Enter account and password"',
        '''appleDone ? `Verified by successful install · ${new Date(appleInfo.verified_at * 1000).toLocaleString()}` : c.apple_id && c.has_password ? (appleInfo.state === "failed" ? `Apple authentication failed (${appleInfo.code || "unknown"}) · retry paused` : "Credentials saved · Apple sign-in not yet verified") : "Enter account and password"''',
        "Step 2 exact status")
replace(index,
    '<button class="cell action">Save</button>',
    '<button class="cell action">Save credentials</button>',
    "Save must not imply sign-in")
replace(index,
    '<div class="foot">Use the regular password, not an app-specific one.</div>',
    '''<div class="foot">Use the regular password, not an app-specific one.</div>
    <div class="foot"><strong>Verification status:</strong> Saving a password does not sign in to Apple. This AltServer backend has no independent login-only check. SideLoader marks this step verified only after one successful app signing and confirmed installation. If a signing attempt fails, see Activity → Copy Diagnostics; retries stay paused. You can also check that your account works at <a href="https://account.apple.com/" target="_blank" rel="noopener noreferrer">Apple Account</a>, but that does not verify AltServer itself. After changing accounts, automatic renewal is turned off until you enable it again following a successful installation.</div>''',
    "explain verification without another Apple attempt")
print("Apple Account Step 2 now distinguishes saved, verified, and rejected credentials.")
