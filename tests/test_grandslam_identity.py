"""No-network regression tests for Mac anisette/GrandSlam identity alignment."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ANISETTE = 'ANISETTE_SERVER: "${SIDELOADER_ANISETTE_SERVER:-https://new.ani.sidestore.io}"'
DEFAULT_AGENT = (
    'ALTSERVER_GSA_USER_AGENT: '
    '"${SIDELOADER_GSA_USER_AGENT:-akd/1.0 CFNetwork/811.5.4 Darwin/16.7.0}"'
)


class GrandSlamIdentityTests(unittest.TestCase):
    def test_mac_and_ubuntu_use_same_matching_default_auth_identity(self):
        for name in ("mac-host.yml", "ubuntu-host.yml"):
            with self.subTest(host=name):
                cfg = (ROOT / "deploy" / name).read_text()
                self.assertIn(DEFAULT_ANISETTE, cfg)
                self.assertIn(DEFAULT_AGENT, cfg)
                self.assertNotIn("ALTSERVER_CLIENT_INFO:", cfg)

    def test_provider_and_agent_are_overridable_together(self):
        for name in ("mac-host.yml", "ubuntu-host.yml"):
            cfg = (ROOT / "deploy" / name).read_text()
            self.assertIn("SIDELOADER_ANISETTE_SERVER:-", cfg)
            self.assertIn("SIDELOADER_GSA_USER_AGENT:-", cfg)


if __name__ == "__main__":
    unittest.main()
