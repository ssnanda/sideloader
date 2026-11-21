"""Repeat builds must not stack signing calls in refresh.sh.

A second `retry_guard success` raised after the first released the
reservation, so a verified install was reported as failed and signing paused.
"""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = '''#!/usr/bin/env bash
log "STAGE 1/4: Checking signing safety lock. No Apple request has been sent."
if ! python3 -m sideloop.retry_guard check; then
  log "STOPPED: a previous signing attempt failed; review Activity and explicitly resume before retrying."
  record blocked "signing paused after a failed attempt"
  exit 73
fi
log "STAGE 2/4: iPhone reachable and IPA ready. Preparing Apple developer signing."
log "STAGE 3/4: Asking AltServer to sign and install. One 2FA code may be required."
log "signing and installing $(basename "$IPA_PATH") on $DEVICE_UDID"
out="$(mktemp)"
if (( rc == 0 )); then
  log "OK $msg"; record ok "$msg"
  # Only a verified installation proves the account worked with AltServer.
  python3 -m sideloop.account verified || log "WARNING: could not persist account verification status"
  prune_profiles
fi
# Pause all further signing attempts on the first failed attempt.
# Keep only classified error and action; never save raw auth output.
python3 -m sideloop.retry_guard failed "$out" "$rc" || true
n=$(( $(read_fails) + 1 )); echo "$n" > "$FAILS"
'''
SUCCESS = '  python3 -m sideloop.retry_guard success "$attempt_token"\n'
VERIFIED = ('  # Only a verified installation proves the account worked with AltServer.\n'
            '  python3 -m sideloop.account verified || log "WARNING: could not persist account verification status"\n')
STAGES = SCRIPT[SCRIPT.index('log "STAGE 1/4'):SCRIPT.index('log "signing and installing')]
FAILED = ('# Pause all further signing attempts on the first failed attempt.\n'
          '# Keep only classified error and action; never save raw auth output.\n'
          'python3 -m sideloop.retry_guard failed "$out" "$rc" || true\n')


class RefreshDedupTests(unittest.TestCase):
    def patch(self, root):
        r = subprocess.run([sys.executable, str(ROOT / 'overlay/patch-one-attempt.py'), str(root)],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return (root / 'scripts/refresh.sh').read_text()

    def test_collapses_stacked_insertions_and_stays_stable(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'scripts').mkdir()
            shell = root / 'scripts/refresh.sh'
            shell.write_text(SCRIPT)
            clean = self.patch(root)
            # Reproduce what repeated builds left behind.
            ok = '  log "OK $msg"; record ok "$msg"\n'
            stacked = clean.replace(ok + SUCCESS + VERIFIED, ok + (SUCCESS + VERIFIED) * 5)
            stacked = stacked.replace(STAGES, STAGES + 'log "Apple Account passed to AltServer (-a): ${APPLE_ID}"\n' + STAGES)
            stacked = stacked.replace('n=$(( $(read_fails)', FAILED + 'n=$(( $(read_fails)')
            self.assertGreater(stacked.count(SUCCESS), 1)
            shell.write_text(stacked)
            repaired = self.patch(root)
            self.assertEqual(repaired.count(SUCCESS), 1)
            self.assertEqual(repaired.count('python3 -m sideloop.account verified'), 1)
            self.assertEqual(repaired.count('STAGE 1/4'), 1)
            self.assertEqual(repaired.count('retry_guard check'), 1)
            self.assertEqual(repaired.count('retry_guard failed'), 1)
            self.assertIn('"$attempt_token" || true', repaired)
            self.assertIn(ok + SUCCESS + VERIFIED + '  prune_profiles', repaired)
            self.assertEqual(self.patch(root), repaired)


if __name__ == '__main__':
    unittest.main()
