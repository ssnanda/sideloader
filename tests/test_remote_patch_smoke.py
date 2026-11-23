"""Exercise the remote bridge patch against a minimal Sideloop layout."""
import ast
from pathlib import Path
import tempfile
import unittest

from test_remote_server import ROOT, installer


class RemotePatchSmoke(unittest.TestCase):
    def test_patch_twice_without_corruption(self):
        with tempfile.TemporaryDirectory() as folder:
            package = Path(folder) / "sideloop"
            package.mkdir()
            (package / "server.py").write_text(
                "from .installed import enrich_apps\n"
                "class App:\n"
                "    def __init__(self, jobs, health, muxers):\n"
                "        self.jobs, self.health, self.muxers = jobs, health, muxers\n"
                "    def state(self):\n"
                "        return {\n"
                "            \"mode\": MUX,\n"
                "            \"registered\": [],\n"
                "        }\n"
                "    def logs(self):\n"
                "        return []\n"
                "    def refresh(self, data):\n"
                "        return {}\n"
                "    def routes(self):\n"
                "        return {\n"
                "            \"/api/refresh\": self.refresh,\n"
                "        }\n"
                "def handler(app):\n"
                "    class Handler:\n"
                "        def do_GET(self):\n"
                "            if path == \"/api/job\":\n"
                "                return self.send(200, {})\n"
            )
            (package / "jobs.py").write_text(
                "class Job:\n"
                "    def view(self):\n"
                "        return {\"accepts_input\": self.fd is not None}\n"
                "    def send(self, text):\n"
                "        # This endpoint is exclusively for an active 2FA challenge.\n"
                "        if self.fd is None:\n"
                "            raise ValueError('no input')\n"
            )
            (package / "watcher.py").write_text(
                "import time\n"
                "from . import config, retry_guard, store\n"
                "class Watcher:\n"
                "    def loop(self):\n"
                "        while True:\n"
                "            time.sleep(5)\n"
            )
            installer.apply(folder, ROOT / "overlay")
            first = {p.name: p.read_bytes() for p in package.iterdir()}
            installer.apply(folder, ROOT / "overlay")
            self.assertEqual(first, {p.name: p.read_bytes() for p in package.iterdir()})
            for name in ("server.py", "jobs.py", "watcher.py", "remote_altkeeper.py"):
                ast.parse((package / name).read_text())
            server = (package / "server.py").read_text()
            self.assertIn('"/api/remote/latest": self.remote_latest', server)
            self.assertIn("remote_altkeeper.enrich_state(result)", server)
            self.assertIn("remote_altkeeper.bootstrap_device()", server)


if __name__ == "__main__":
    unittest.main()
