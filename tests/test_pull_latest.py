"""Real git tests for version reporting, self-replacement and safe updates."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'bin' / 'pull-latest.sh'


def git(*args, cwd=None):
    r = subprocess.run(['git', *args], cwd=cwd, capture_output=True, text=True)
    if r.returncode:
        raise AssertionError(f"git {' '.join(args)}: {r.stdout}\n{r.stderr}")
    return r.stdout


class PullVersionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.remote, self.seed, self.local = root / 'remote.git', root / 'seed', root / 'checkout'
        git('init', '-q', '--bare', str(self.remote))
        git('init', '-q', '-b', 'main', str(self.seed))
        (self.seed / 'VERSION').write_text('0.2.0+1\n')
        (self.seed / '.gitignore').write_text('/build/\n')
        (self.seed / 'bin').mkdir()
        shutil.copy2(SCRIPT, self.seed / 'bin' / 'pull-latest.sh')
        git('add', '.', cwd=self.seed)
        git('-c', 'user.name=Dev', '-c', 'user.email=dev@example.com', 'commit', '-qm', 'initial', cwd=self.seed)
        git('remote', 'add', 'origin', str(self.remote), cwd=self.seed)
        git('push', '-q', 'origin', 'main', cwd=self.seed)
        git('--git-dir', str(self.remote), 'symbolic-ref', 'HEAD', 'refs/heads/main')
        git('clone', '-q', str(self.remote), str(self.local))
        git('remote', 'set-url', 'origin', 'https://github.com/ssnanda/sideloader.git', cwd=self.local)
        git('config', f'url.file://{self.remote}.insteadOf', 'https://github.com/ssnanda/sideloader.git', cwd=self.local)
        git('config', 'user.name', 'Dev', cwd=self.local)
        git('config', 'user.email', 'dev@example.com', cwd=self.local)
        (self.local / 'build').mkdir()
        (self.local / 'build' / 'pairing').write_text('DO NOT DELETE')

    def pull(self, *flags):
        result = subprocess.run(['bash', './bin/pull-latest.sh', *flags], cwd=self.local, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + '\n' + result.stderr)
        return result.stdout

    def advance_remote(self, version, change_script=False):
        (self.seed / 'VERSION').write_text(version + '\n')
        (self.seed / 'notes.txt').write_text('A real upstream update: ' + version)
        if change_script:
            source = (self.seed / 'bin' / 'pull-latest.sh').read_text()
            (self.seed / 'bin' / 'pull-latest.sh').write_text(source + '\n# Updated updater script\n')
        git('add', '.', cwd=self.seed)
        git('-c', 'user.name=Dev', '-c', 'user.email=dev@example.com', 'commit', '-qm', 'remote update', cwd=self.seed)
        git('push', '-q', 'origin', 'main', cwd=self.seed)

    def test_versions_visible_on_every_run_even_if_current(self):
        out = self.pull()
        self.assertIn('SideLoader local version: 0.2.0+1', out)
        self.assertIn('SIDELOADER VERSION COMPARISON (before update)', out)
        self.assertIn('Local SideLoader:  0.2.0+1', out)
        self.assertIn('GitHub SideLoader: 0.2.0+1', out)
        self.assertIn('SIDELOADER VERSION COMPARISON (after update)', out)
        self.assertIn('already current', out)
        self.assertEqual((self.local / 'build' / 'pairing').read_text(), 'DO NOT DELETE')

    def test_remote_version_and_changes(self):
        self.advance_remote('0.2.0+2')
        out = self.pull()
        self.assertIn('SideLoader local version: 0.2.0+1', out)
        self.assertIn('GitHub SideLoader: 0.2.0+2', out)
        self.assertIn('SIDELOADER VERSION COMPARISON (after update)', out)
        self.assertIn('Local SideLoader:  0.2.0+2', out)
        self.assertIn('Changes applied:', out)
        self.assertEqual((self.local / 'VERSION').read_text(), '0.2.0+2\n')
        self.assertEqual((self.local / 'build' / 'pairing').read_text(), 'DO NOT DELETE')

    def test_updater_self_update_runs_new_report_without_another_pull(self):
        self.advance_remote('0.2.0+3', change_script=True)
        out = self.pull()
        self.assertIn('Updater script changed during pull', out)
        self.assertIn('CURRENT VERSIONS (updated updater)', out)
        self.assertIn('Local SideLoader:  0.2.0+3', out)
        self.assertIn('GitHub SideLoader: 0.2.0+3', out)
        self.assertEqual((self.local / 'build' / 'pairing').read_text(), 'DO NOT DELETE')

    def test_local_codex_commit_and_untracked_file_preserved(self):
        self.advance_remote('0.2.0+2')
        (self.local / 'feature.txt').write_text('Codex change\n')
        git('add', 'feature.txt', cwd=self.local)
        git('-c', 'user.name=Dev', '-c', 'user.email=dev@example.com', 'commit', '-qm', 'local fix', cwd=self.local)
        (self.local / 'scratch.txt').write_text('Uncommitted change\n')
        out = self.pull()
        self.assertIn('Local-only commits retained', out)
        self.assertEqual((self.local / 'feature.txt').read_text(), 'Codex change\n')
        self.assertEqual((self.local / 'scratch.txt').read_text(), 'Uncommitted change\n')
        self.assertEqual((self.local / 'VERSION').read_text(), '0.2.0+2\n')
        self.assertEqual((self.local / 'build' / 'pairing').read_text(), 'DO NOT DELETE')

    def test_report_only_is_non_mutating(self):
        out = self.pull('--report-only')
        self.assertIn('CURRENT VERSIONS (updated updater)', out)
        self.assertNotIn('Fetching latest version', out)
        self.assertEqual(git('status', '--porcelain', cwd=self.local), '')

    def test_force_requires_explicit_flag_and_preserves_ignored_data(self):
        self.advance_remote('0.2.0+2')
        (self.local / 'scratch.txt').write_text('delete with force')
        out = self.pull('--force')
        self.assertIn('FORCE MODE', out)
        self.assertFalse((self.local / 'scratch.txt').exists())
        self.assertEqual((self.local / 'build' / 'pairing').read_text(), 'DO NOT DELETE')


if __name__ == '__main__':
    unittest.main()