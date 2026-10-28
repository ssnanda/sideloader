"""Only present real container signing metadata, never assumed versions."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1] / 'overlay' / 'backend_info.py'
spec = importlib.util.spec_from_file_location('sideloader_backend_test', SOURCE)
backend = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backend)

class BackendInfoTest(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root = Path(t.name)
        self.meta = self.root / 'build.json'
        self.bin = self.root / 'AltServer'
        self.bin.write_bytes(b'fake executable')
        self.bin.chmod(0o755)
        self.meta.write_text(json.dumps({'name':'AltServer-Linux NG','ref':'ng',
                    'revision':backend.EXPECTED_REVISION,'built_at':'2026-10-28T15:00:00Z'}))

    def test_expected_revision_in_binary_image(self):
        state=backend.status(self.meta, self.bin)
        self.assertEqual(state['status'], 'pinned')
        self.assertEqual(state['revision'],backend.EXPECTED_REVISION)
        self.assertEqual(len(state['binary_sha256']),64)

    def test_wrong_revision_must_not_be_marked_good(self):
        self.meta.write_text(json.dumps({'ref':'ng','revision':'1'*40}))
        self.assertEqual(backend.status(self.meta,self.bin)['status'],'unexpected')

    def test_missing_metadata_is_unknown(self):
        self.meta.unlink()
        self.assertEqual(backend.status(self.meta,self.bin)['status'],'unknown')

    def test_missing_binary_does_not_claim_good(self):
        self.bin.unlink()
        self.assertEqual(backend.status(self.meta,self.bin)['status'],'missing_binary')

    def test_missing_ref_is_unexpected(self):
        self.meta.write_text(json.dumps({'revision':backend.EXPECTED_REVISION,'ref':'another'}))
        self.assertEqual(backend.status(self.meta,self.bin)['status'],'unexpected')


    def test_check_updates_reports_current_ng_revision(self):
        from unittest.mock import patch
        head = backend.EXPECTED_REVISION
        with patch.object(backend, 'status', return_value={'revision': head}), \
             patch.object(backend, '_github_json', return_value={
                'sha': head, 'commit': {'committer': {'date': '2026-10-27T19:24:30Z'}}}) as fetch:
            result = backend.check_updates()
        self.assertEqual(result['status'], 'up_to_date')
        self.assertEqual(result['latest_revision'], head)
        fetch.assert_called_once_with(backend.API_BASE + '/commits/ng')

    def test_check_updates_detects_ancestor_update_without_installing(self):
        from unittest.mock import patch
        old = backend.EXPECTED_REVISION
        new = 'a' * 40
        responses = [
            {'sha': new, 'commit': {'committer': {'date': '2026-10-29T00:00:00Z'}}},
            {'ahead_by': 4, 'behind_by': 0},
        ]
        with patch.object(backend, 'status', return_value={'revision': old}), \
             patch.object(backend, '_github_json', side_effect=responses) as fetch:
            result = backend.check_updates()
        self.assertEqual(result['status'], 'update_available')
        self.assertEqual(result['latest_revision'], new)
        self.assertEqual(fetch.call_count, 2)
        self.assertIn('validate', result['message'])

    def test_check_updates_does_not_assume_diverged_is_safe(self):
        from unittest.mock import patch
        responses = [{'sha': 'b' * 40}, {'ahead_by': 2, 'behind_by': 1}]
        with patch.object(backend, 'status', return_value={'revision': backend.EXPECTED_REVISION}), \
             patch.object(backend, '_github_json', side_effect=responses):
            self.assertEqual(backend.check_updates()['status'], 'different_revision')

    def test_check_updates_handles_github_outage(self):
        from unittest.mock import patch
        from urllib.error import URLError
        with patch.object(backend, 'status', return_value={'revision': backend.EXPECTED_REVISION}), \
             patch.object(backend, '_github_json', side_effect=URLError('unavailable')):
            result = backend.check_updates()
        self.assertEqual(result['status'], 'unavailable')
        self.assertIsNone(result['latest_revision'])

    def test_check_updates_cannot_guess_version_when_binary_missing(self):
        from unittest.mock import patch
        with patch.object(backend, 'status', return_value={'revision': None}), \
             patch.object(backend, '_github_json', return_value={'sha': 'c' * 40}):
            self.assertEqual(backend.check_updates()['status'], 'unknown_installed')

if __name__=='__main__': unittest.main()