"""Regression coverage for full-screen Apps prompts and repeat Docker builds."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / "overlay" / "patch-screen-flow.py"
FIXTURE = """<html><head><style>body{color:black}</style></head><body><script>
async function boot() {
  await refresh();
  render(); poll();
}
function renderAuth(first) {}
async function poll() {
  if (S.job && S.job.running) watched.add(S.job.id);
  if (sheetJob()) await pullJob();
  render();
}
function render() {
  return view === "apps" ? appsView() : activityView();
}
function renderSheet() {
  const legacy = "modal not used";
}
async function startJob(path, body={}) {
  const reply = await api(path,{json:body});
  watched.add(reply.job);
}
function wire() {
  const button = null;
}
function upload(f) {}
</script></body></html>"""


class ScreenFlowTests(unittest.TestCase):
    def make(self, root):
        pkg = root / "sideloop"
        pkg.mkdir()
        (pkg / "index.html").write_text(FIXTURE)
        return pkg / "index.html"

    def run_patch(self, root):
        return subprocess.run(
            [sys.executable, str(PATCH), str(root), str(ROOT / "overlay")],
            capture_output=True, text=True
        )

    def test_first_and_repeat_build_keep_in_page_prompts(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            index = self.make(root)
            result = self.run_patch(root)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            first = index.read_text()
            self.assertIn("slScreenView() : appsView()", first)
            self.assertIn("slWireScreen();", first)
            self.assertIn("return slStartJob(path, body);", first)
            self.assertIn("legacy modal intentionally disabled", first)
            self.assertIn("S.job.needs_input", first)
            self.assertIn("/* SideLoader in-page workflow v1", first)
            result = self.run_patch(root)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertEqual(first, index.read_text())

    def test_unrecognized_page_fails_before_writing(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            index = self.make(root)
            page = FIXTURE.replace('function renderSheet() {', 'function unknownSheet() {')
            index.write_text(page)
            result = self.run_patch(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(page, index.read_text())

    def test_no_native_alerts_for_apps_or_sources(self):
        ui = (ROOT / "overlay" / "apps-dashboard-ui.js").read_text()
        flow = (ROOT / "overlay" / "screen-flow-ui.js").read_text()
        sources = (ROOT / "overlay" / "sources.html").read_text()
        for name, src in (("Apps", ui), ("Flow", flow), ("Sources", sources)):
            with self.subTest(name=name):
                self.assertNotIn("window.alert(", src)
                self.assertNotIn("window.confirm(", src)
        self.assertIn('id="sl-screen-otp"', flow)
        self.assertIn('id="sl-screen-install"', flow)
        self.assertIn('id="sl-screen-uninstall"', flow)
        self.assertIn('document.querySelectorAll("[data-sign]")', flow)
        self.assertIn('slInstall(app,udid,installed);', flow)
        self.assertIn('on("signall","onclick"', flow)
        self.assertIn('on("sideloader-clear-logs","onclick"', flow)
        self.assertIn('sourceConfirm(', sources)

    def test_javascript_syntax(self):
        if subprocess.run(["which", "node"], capture_output=True).returncode:
            self.skipTest("Node.js not installed")
        flow = (ROOT / "overlay" / "screen-flow-ui.js").read_text()
        result = subprocess.run(["node", "--check"], input=flow, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
