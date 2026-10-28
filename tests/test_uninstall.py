"""Offline safety tests: no Docker/host services or files are changed."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "bin" / "uninstall.sh"


class UninstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "bin").mkdir()
        (self.root / "mock-bin").mkdir()
        (self.root / "deploy").mkdir()
        (self.root / "build" / "sideloop" / "data").mkdir(parents=True)
        shutil.copy2(SCRIPT, self.root / "bin" / "uninstall.sh")
        (self.root / "build" / "sideloop" / "docker-compose.yml").write_text("name: sideloop\n")
        (self.root / "build" / "sideloop" / ".env").write_text("TZ=UTC\n")
        (self.root / "build" / "sideloop" / "data" / "sensitive.ipa").write_bytes(b"saved")
        (self.root / "deploy" / "ubuntu-host.yml").write_text("services: {}\n")
        (self.root / "deploy" / "mac-host.yml").write_text("services: {}\n")
        (self.root / "mock-bin" / "docker").write_text(
            "#!/usr/bin/env bash\nprintf '%s\\n' \"$*\" >> \"$MOCK_DOCKER_LOG\"\nexit 0\n"
        )
        (self.root / "mock-bin" / "docker").chmod(0o755)
        self.log = self.root / "docker.log"
        self.env = dict(os.environ, PATH=str(self.root / "mock-bin") + os.pathsep + os.environ["PATH"],
                        MOCK_DOCKER_LOG=str(self.log))

    def run_uninstall(self, *args):
        return subprocess.run([str(self.root / "bin" / "uninstall.sh"), *args],
                              cwd=self.root, env=self.env, capture_output=True, text=True, timeout=5)

    def calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def test_default_removes_containers_but_preserves_data(self):
        result = self.run_uninstall()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.root / "build" / "sideloop" / "data" / "sensitive.ipa").exists())
        self.assertTrue((self.root / "build" / "sideloop" / ".env").exists())
        self.assertTrue(any("down --remove-orphans" in line for line in self.calls()))
        self.assertFalse(any("--volumes" in line or "image rm" in line for line in self.calls()))

    def test_purge_requires_confirmation_before_docker(self):
        result = self.run_uninstall("--purge-data")
        self.assertEqual(result.returncode, 2)
        self.assertFalse(self.calls())
        self.assertTrue((self.root / "build" / "sideloop" / "data" / "sensitive.ipa").exists())

    def test_explicit_purge_deletes_only_data_and_env(self):
        result = self.run_uninstall("--purge-data", "--yes")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.root / "build" / "sideloop" / "data").exists())
        self.assertFalse((self.root / "build" / "sideloop" / ".env").exists())
        self.assertTrue((self.root / "build" / "sideloop" / "docker-compose.yml").exists())
        self.assertTrue(any("--volumes" in line for line in self.calls()))
        self.assertFalse(any("image rm" in line for line in self.calls()))

    def test_image_removal_is_opt_in(self):
        result = self.run_uninstall("--remove-image", "--yes")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(any("image rm sideloop" in line for line in self.calls()))
        self.assertTrue((self.root / "build" / "sideloop" / "data" / "sensitive.ipa").exists())

    def test_data_symlink_refuses_purge(self):
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "private").write_text("do not delete")
        shutil.rmtree(self.root / "build" / "sideloop" / "data")
        (self.root / "build" / "sideloop" / "data").symlink_to(outside)
        result = self.run_uninstall("--purge-data", "--yes")
        self.assertEqual(result.returncode, 1)
        self.assertTrue((outside / "private").exists())
        self.assertFalse(self.calls())

    def test_unknown_arg_and_help_do_not_touch_services(self):
        self.assertEqual(self.run_uninstall("--help").returncode, 0)
        self.assertEqual(self.run_uninstall("--oops").returncode, 2)
        self.assertFalse(self.calls())

    def test_missing_checkout_is_harmless(self):
        shutil.rmtree(self.root / "build" / "sideloop")
        result = self.run_uninstall()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.calls())


if __name__ == '__main__':
    unittest.main()