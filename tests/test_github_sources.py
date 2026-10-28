"""Offline tests for GitHub source discovery, private API access and deduplication."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PKG = 'sample_sideloader_github'
pkg = types.ModuleType(PKG)
pkg.__path__ = []
config = types.ModuleType(PKG + '.config')
sys.modules.update({PKG: pkg, PKG + '.config': config})
spec = importlib.util.spec_from_file_location(PKG + '.github_sources', ROOT / 'overlay/github_sources.py')
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)


class GithubSourceTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        config.DATA = Path(directory.name)

    def test_profile_validation(self):
        self.assertEqual(mod.parse_owner('https://github.com/ssnanda/'), 'ssnanda')
        self.assertEqual(mod.parse_owner('ssnanda'), 'ssnanda')
        for url in ('https://github.com/ssnanda/other', 'http://github.com/ssnanda',
                    'https://github.com/ssnanda?token=abc', 'https://evil.example/ssnanda',
                    'https://github.com@evil.example/ssnanda', 'bad user'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                mod.parse_owner(url)

    def test_token_is_private_and_never_in_reference(self):
        mod.save_token('github_pat_test')
        self.assertEqual(mod.load_token(), 'github_pat_test')
        self.assertEqual(mod.token_file().stat().st_mode & 0o777, 0o600)
        self.assertEqual(mod.make_ref('ssnanda','private-repo','dir/altstore.json'),
                         'github://ssnanda/private-repo/dir/altstore.json')
        self.assertNotIn('github_pat', mod.make_ref('ssnanda','repo','altstore.json'))
        mod.forget_token()
        self.assertEqual(mod.load_token(), '')

    def test_public_raw_and_private_reference_same_dedup_key(self):
        self.assertEqual(mod.dedup_key('github://ssnanda/repo/altstore.json'),
                         mod.dedup_key('https://raw.githubusercontent.com/ssnanda/repo/main/altstore.json'))
        self.assertEqual(mod.dedup_key('github://ssnanda/repo/sub/altstore.json'),
                         mod.dedup_key('https://raw.githubusercontent.com/ssnanda/repo/master/sub/altstore.json'))
        with self.assertRaises(ValueError):
            mod.make_ref('ssnanda','repo','../altstore.json')

    def test_private_and_public_scan_and_nested_files(self):
        repos=[{'name':'public','owner':{'login':'ssnanda'},'default_branch':'main','private':False},
               {'name':'secret','owner':{'login':'ssnanda'},'default_branch':'main','private':True}]
        def fake_json(url, token='', limit=0):
            if '/git/trees/' in url:
                return {'tree':[{'type':'blob','path':'nested/altstore.json'},
                                {'type':'blob','path':'assets/AlStOrE.JSON'},
                                {'type':'blob','path':'README.md'},
                                {'type':'tree','path':'fake/altstore.json'}]}
            raise AssertionError(url)
        with patch.object(mod,'repositories',return_value=(repos,False)),patch.object(mod,'read_json',side_effect=fake_json):
            entries, problems, scanned=mod.discover('ssnanda','token')
        self.assertEqual(scanned, 2)
        self.assertEqual(len(entries), 4)
        self.assertFalse(problems)
        self.assertEqual(len([x for x in entries if x[-1]]),2)

    def test_json_source_uses_saved_token_and_returns_base(self):
        mod.save_token('github_pat_readonly')
        content = json.dumps({'name':'Private', 'apps':[]}).encode()
        record={'type':'file','size':len(content),'encoding':'base64',
                'content':__import__('base64').b64encode(content).decode(),
                'download_url':'https://raw.githubusercontent.com/ssnanda/private/main/altstore.json'}
        with patch.object(mod,'read_json',return_value=record) as m:
            data, url = mod.source_contents('github://ssnanda/private/altstore.json', 2097152)
        self.assertEqual(data['name'], 'Private')
        self.assertTrue(url.endswith('altstore.json'))
        self.assertEqual(m.call_args[0][1], 'github_pat_readonly')

    def test_no_token_sent_to_non_github_api_hosts(self):
        with self.assertRaises(ValueError):
            mod.request('https://example.com/ipa', 'token')
        with self.assertRaises(ValueError):
            mod.request('http://api.github.com/user', 'token')


if __name__ == '__main__':
    unittest.main()