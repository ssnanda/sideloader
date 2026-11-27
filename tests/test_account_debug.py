"""Account settings + timing/debug patch: wiring, safety and idempotence."""
from pathlib import Path
import py_compile
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / "overlay" / "patch-account-debug.py"
BUILT = ROOT / "build" / "sideloop" / "sideloop"


class AccountDebugPatchTests(unittest.TestCase):
    def test_build_applies_patch_after_local_login(self):
        build = (ROOT / "bin" / "build-docker.sh").read_text()
        self.assertIn("patch-account-debug.py", build)
        self.assertLess(build.index("patch-local-login.py"), build.index("patch-account-debug.py"))

    def test_password_is_never_logged_or_returned(self):
        patch = PATCH.read_text()
        self.assertIn('"password_length": len(password)', patch)
        self.assertNotIn('"password": password', patch)
        self.assertNotIn("repr(password)", patch)

    def test_password_change_requires_current_password_and_rotates_session(self):
        patch = PATCH.read_text()
        route = patch[patch.index('if path == "/api/auth/password":'):]
        self.assertLess(route.index("auth.check_password(auth.username(), current)"),
                        route.index("auth.set_password(new, auth.username())"))
        self.assertIn("return self.login(auth.new_session())", route)

    def test_username_is_trimmed_at_sign_in(self):
        self.assertIn("auth.check_password(raw_user.strip(), password)", PATCH.read_text())

    @unittest.skipUnless((BUILT / "server.py").is_file(), "no local Sideloop build output")
    def test_applies_to_current_build_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            shutil.copytree(BUILT, Path(tmp) / "sideloop")
            for _ in range(2):
                subprocess.run([sys.executable, str(PATCH), tmp], check=True, capture_output=True)
            server = (Path(tmp) / "sideloop" / "server.py").read_text()
            index = (Path(tmp) / "sideloop" / "index.html").read_text()
            py_compile.compile(str(Path(tmp) / "sideloop" / "server.py"), doraise=True)
            self.assertEqual(server.count("# SideLoader account + debug v1 start"), 1)
            self.assertEqual(index.count('id="sl-password"'), 1)
            self.assertEqual(index.count('id="sl-debug"'), 1)
            self.assertIn('if path == "/api/debug":', server)


if __name__ == "__main__":
    unittest.main()
