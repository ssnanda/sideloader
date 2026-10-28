import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]


class GithubOverlayTests(unittest.TestCase):
    def test_routes_repeatable_existing_sources_and_v2(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'sideloop'
            p.mkdir()
            server=p/'server.py'
            server.write_text('''class App:
    def routes(self):
        return {
            "/api/sources/install": lambda data: self.sources.install(data, self),
        }

class Handler:
    def do_GET(self):
        if path == "/api/sources":
                return self.send(200, app.sources.list())
''')
            args=[sys.executable,str(ROOT/'overlay/patch-github.py'),tmp,str(ROOT/'overlay')]
            first=subprocess.run(args,check=True,capture_output=True,text=True)
            result=server.read_text()
            self.assertIn('"/api/sources/github/scan": self.sources.scan_github',result)
            self.assertIn('"/api/sources/github/disconnect": self.sources.disconnect_github',result)
            self.assertIn('if path == "/api/sources/github/status":',result)
            self.assertTrue((p/'github_sources.py').exists())
            subprocess.run(args,check=True,capture_output=True,text=True)
            self.assertEqual(result,server.read_text())


if __name__=='__main__':
    unittest.main()