"""Test persistent global one-attempt guard, interruption, duplicate clicks and recovery."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest

PKG = 'sideloader_one_attempt_tests'
package = types.ModuleType(PKG)
package.__path__ = []
config = types.ModuleType(PKG + '.config')
config.STATE = Path('/tmp/sideloader-one-attempt-unit-tests')
sys.modules.update({PKG: package, PKG + '.config': config})
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(PKG + '.retry_guard', ROOT / 'overlay' / 'retry_guard.py')
guard = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = guard
spec.loader.exec_module(guard)


class OneAttemptTests(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        config.STATE = Path(td.name) / 'state'
        self.account = {'APPLE_ID': 'a@example.org', 'APPLE_PASSWORD': 'not-saved-in-guard'}
        config.read = lambda: self.account
        guard.FILE = config.STATE / 'sideloader-signing-block.json'
        guard.LOCK = config.STATE / '.sideloader-signing-block.lock'

    def test_reserves_before_network_and_blocks_duplicate_click(self):
        token = guard.begin()
        self.assertTrue(guard.status()['blocked'])
        self.assertEqual(guard.status()['code'], 'attempt_in_progress')
        with self.assertRaises(RuntimeError):
            guard.begin()
        with self.assertRaises(RuntimeError):
            guard.assert_allowed()
        self.assertNotIn('not-saved-in-guard', guard.FILE.read_text())
        self.assertNotIn('a@example.org', guard.FILE.read_text())
        guard.succeeded(token)
        self.assertFalse(guard.status()['blocked'])
        guard.begin()  # successful install permits a different later manual action

    def test_crash_or_docker_restart_stays_blocked(self):
        token = guard.begin()
        self.assertTrue(token)
        self.assertEqual(guard.status()['code'], 'attempt_in_progress')
        with self.assertRaises(RuntimeError):
            guard.begin()
        guard.resume()
        self.assertFalse(guard.status()['blocked'])
        self.assertTrue(guard.begin())

    def test_cancelled_child_cannot_rearm_with_old_token(self):
        old = guard.begin()
        guard.resume()
        fresh = guard.begin()
        with self.assertRaises(RuntimeError):
            guard.succeeded(old)
        self.assertEqual(guard.status()['code'], 'attempt_in_progress')
        guard.failed('Apple: -36607', 1, old)
        self.assertEqual(guard.status()['code'], 'attempt_in_progress')
        guard.failed('Apple: -36607', 1, fresh)
        self.assertEqual(guard.status()['code'], '-36607')

    def test_one_failed_attempt_blocks_until_explicit_resume(self):
        token = guard.begin()
        guard.failed('Unable to sign you in to your Apple Account. Try again later. (-36607)', 1, token)
        self.assertEqual(guard.status()['code'], '-36607')
        with self.assertRaises(RuntimeError):
            guard.begin()
        guard.resume()
        self.assertTrue(guard.begin())

    def test_new_apple_account_does_not_implicitly_reset_failure(self):
        token = guard.begin()
        guard.failed('Locked: -20209', 1, token)
        self.account['APPLE_ID'] = 'second@example.org'
        self.assertTrue(guard.status()['blocked'])
        self.assertEqual(guard.status()['code'], 'previous_account_attempt')
        with self.assertRaises(RuntimeError):
            guard.begin()
        guard.resume()
        self.assertTrue(guard.begin())

    def test_pty_output_can_refine_generic_failure(self):
        t = guard.begin()
        guard.failed('', 1, t)
        self.assertEqual(guard.status()['code'], 'install_failed')
        guard.failed('Apple refused: (-80046)', 1)
        self.assertEqual(guard.status()['code'], '-80046')

    def test_malformed_state_is_fail_closed(self):
        guard.FILE.parent.mkdir(parents=True)
        guard.FILE.write_text('not-json')
        with self.assertRaises(RuntimeError):
            guard.begin()
        self.assertEqual(guard.status()['code'], 'guard_state_unreadable')

    def test_cannot_approve_old_success_after_account_changed(self):
        token = guard.begin()
        self.account['APPLE_ID'] = 'second@example.org'
        with self.assertRaises(RuntimeError):
            guard.succeeded(token)
        self.assertTrue(guard.status()['blocked'])


class PatcherTests(unittest.TestCase):
    SCRIPT = ROOT / 'overlay' / 'patch-one-attempt.py'
    FIXTURE = '''#!/usr/bin/env bash
log "STAGE 1/4: Checking signing safety lock. No Apple request has been sent."
log "signing and installing app.ipa on $DEVICE_UDID"
out="$(mktemp)"
trap 'rm -f "$out"' EXIT
timeout 2400 "$ALTSERVER_BIN" -u "$DEVICE_UDID" -a "$APPLE_ID" -p "$APPLE_PASSWORD" "$IPA_PATH"
if (( rc == 0 )) && stamp_success; then
  log "OK $msg"; record ok "$msg"
  python3 -m sideloop.account verified
  exit 0
fi
python3 -m sideloop.retry_guard failed "$out" "$rc" || true
'''

    def test_patch_reservation_is_before_altserver_and_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'scripts'
            path.mkdir()
            shell = path / 'refresh.sh'
            shell.write_text(self.FIXTURE)
            cmd = [sys.executable, str(self.SCRIPT), d]
            run = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            once = shell.read_text()
            self.assertLess(once.index('retry_guard begin'), once.index('timeout 2400'))
            self.assertIn('retry_guard success "$attempt_token"', once)
            self.assertIn('failed "$out" "$rc" "$attempt_token"', once)
            run = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertEqual(once, shell.read_text())
            result = subprocess.run(['bash', '-n', str(shell)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_refuse_unknown_shell_without_partial_write(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'scripts'
            path.mkdir()
            shell = path / 'refresh.sh'
            shell.write_text('unexpected file')
            result = subprocess.run([sys.executable, str(self.SCRIPT), d], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(shell.read_text(), 'unexpected file')


if __name__ == '__main__':
    unittest.main()