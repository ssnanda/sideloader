import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PATCH=Path(__file__).with_name('patch-responsive-ui.py')
ORIGINAL='''<!doctype html><html><head><style>.page{max-width:680px}</style></head><body>
<script>
function altserverBackendCard() {
  const version = b.revision ? `${esc(b.ref || "unknown")} @ ${esc(b.revision.slice(0, 12))}` : "Version unknown";
  return `<div class="sect"><div class="list">
      <div class="cell ind"><span class="k">Installed backend<span class="sub">${esc(b.name || "AltServer-Linux NG")}</span></span><span>${version}</span><a class="cap" href="https://github.com/jaakkopalvaila/AltServer-Linux/tree/ng" target="_blank" rel="noopener noreferrer">GitHub source</a><a class="cap" href="https://github.com/jaakkopalvaila/AltServer-Linux/commits/ng" target="_blank" rel="noopener noreferrer">Recent commits</a><button type="button" class="cap" id="sideloader-altserver-updates" ${altserverChecking ? "disabled" : ""}>${altserverChecking ? "Checking…" : "Check for updates"}</button></div>
    </div></div>`;
}
</script></body></html>'''

class ResponsivePatchTest(unittest.TestCase):
 def prepare(self,text=ORIGINAL):
  context=tempfile.TemporaryDirectory();self.addCleanup(context.cleanup)
  folder=Path(context.name)/'sideloop';folder.mkdir()
  page=folder/'index.html';page.write_text(text)
  return Path(context.name),page
 def test_upgrades_existing_dashboard_and_repeat_build(self):
  root,page=self.prepare()
  cmd=[sys.executable,str(PATCH),str(root)]
  first=subprocess.run(cmd,text=True,capture_output=True)
  self.assertEqual(first.returncode,0,first.stdout+first.stderr)
  updated=page.read_text()
  self.assertIn('.page { width: 100%; max-width: 1360px',updated)
  self.assertIn('max-width: 1900px',updated)
  self.assertIn('class="sideloader-backend-controls"',updated)
  self.assertIn('grid-template-columns: minmax(0, 1fr)',updated)
  self.assertEqual(updated.count('id="sideloader-altserver-updates"'),1)
  self.assertEqual(updated.count('SideLoader responsive desktop layout v1'),1)
  self.assertEqual(updated.count('sideloader-backend-row"'),1)
  again=subprocess.run(cmd,text=True,capture_output=True)
  self.assertEqual(again.returncode,0,again.stdout+again.stderr)
  self.assertEqual(page.read_text(),updated)
  node=subprocess.run(['node','--check'],input=updated.split('<script>')[1].split('</script>')[0],capture_output=True,text=True)
  self.assertEqual(node.returncode,0,node.stderr)
 def test_unknown_html_fails_without_changing_page(self):
  root,page=self.prepare(ORIGINAL.replace('Installed backend','Something else'))
  result=subprocess.run([sys.executable,str(PATCH),str(root)],capture_output=True,text=True)
  self.assertNotEqual(result.returncode,0)
  self.assertEqual(page.read_text(),ORIGINAL.replace('Installed backend','Something else'))
 def test_partial_migration_does_not_duplicate_existing_wrappers(self):
  root,page=self.prepare()
  cmd=[sys.executable,str(PATCH),str(root)]
  subprocess.run(cmd,check=True,capture_output=True)
  updated=page.read_text()
  self.assertIn('class="sideloader-backend-version"',updated)
  subprocess.run(cmd,check=True,capture_output=True)
  self.assertEqual(page.read_text(),updated)
if __name__=='__main__':unittest.main()