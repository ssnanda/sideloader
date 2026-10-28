"""Exercise local/GitHub version reporting with a private, local bare remote."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/'bin'/'pull-latest.sh'


def run(*args,cwd=None):
    r=subprocess.run(list(args),cwd=cwd,text=True,capture_output=True)
    if r.returncode: raise AssertionError(f'{args}: {r.stdout}\n{r.stderr}')
    return r.stdout

class PullTests(unittest.TestCase):
 def test_versions_progress_and_preserves_ignored_data(self):
  with tempfile.TemporaryDirectory() as t:
   root=Path(t); remote=root/'remote.git'; seeded=root/'seed'; local=root/'checkout'
   run('git','init','-q','--bare',str(remote))
   run('git','init','-q','-b','main',str(seeded))
   (seeded/'VERSION').write_text('0.2.0+1\n')
   (seeded/'.gitignore').write_text('/build/\n')
   run('git','add','.',cwd=seeded)
   run('git','-c','user.name=Dev','-c','user.email=dev@example.com','commit','-qm','initial',cwd=seeded)
   run('git','remote','add','origin',str(remote),cwd=seeded)
   run('git','push','-q','origin','main',cwd=seeded)
   run('git','--git-dir',str(remote),'symbolic-ref','HEAD','refs/heads/main')
   run('git','clone','-q',str(remote),str(local))
   (local/'bin').mkdir()
   shutil.copy(SCRIPT,local/'bin'/'pull-latest.sh')
   # A local URL rewrite lets us test exactly the real origin safety check.
   run('git','remote','set-url','origin','https://github.com/ssnanda/sideloader.git',cwd=local)
   run('git','config',f'url.file://{remote}.insteadOf','https://github.com/ssnanda/sideloader.git',cwd=local)
   (local/'build').mkdir();(local/'build'/'my-data').write_text('private pairing')
   (seeded/'VERSION').write_text('0.2.0+2\n')
   (seeded/'README.md').write_text('Changed on remote\n')
   run('git','add','.',cwd=seeded)
   run('git','-c','user.name=Dev','-c','user.email=dev@example.com','commit','-qm','update',cwd=seeded)
   run('git','push','-q','origin','main',cwd=seeded)
   out=run('bash','./bin/pull-latest.sh',cwd=local)
   self.assertIn('Local:  0.2.0+1',out)
   self.assertIn('GitHub: 0.2.0+2',out)
   self.assertIn('Current SideLoader state',out)
   self.assertIn('Changes applied',out)
   self.assertEqual((local/'VERSION').read_text().strip(),'0.2.0+2')
   self.assertEqual((local/'build'/'my-data').read_text(),'private pairing')
   out=run('bash','./bin/pull-latest.sh',cwd=local)
   self.assertIn('already current',out)
   (local/'feature.txt').write_text('Codex local commit\n')
   run('git','add','feature.txt',cwd=local)
   run('git','-c','user.name=Dev','-c','user.email=dev@example.com',
       'commit','-qm','Codex fix',cwd=local)
   (local/'scratch.txt').write_text('Uncommitted local work\n')
   out=run('bash','./bin/pull-latest.sh',cwd=local)
   self.assertIn('Local-only commits retained',out)
   self.assertEqual((local/'feature.txt').read_text(),'Codex local commit\n')
   self.assertEqual((local/'scratch.txt').read_text(),'Uncommitted local work\n')
   self.assertEqual((local/'build'/'my-data').read_text(),'private pairing')

if __name__=='__main__':unittest.main()