from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
TOOLS_DIR = PROJECT_ROOT / "tools"
sys.path.insert(0, str(APP_DIR))
sys.path.insert(0, str(TOOLS_DIR))

from core.feedback_api import FEEDBACK_API_ORIGIN
from core.public_roadmap import PUBLIC_ROADMAP_ORIGIN
from core.tcg_categories import display_name
from core.version import APP_CHANNEL, APP_VERSION
from core.whats_new_manager import CURRENT_RELEASE
from release_security import verify_distribution


LICENSE_API_ORIGIN = "https://api.pokeyoyakun.com"
PUBLIC_CONTENT_API_ORIGIN = "https://pokeyoyakun.duckdns.org"


class Release125Rc5Test(unittest.TestCase):
    def test_application_version_is_rc5(self):
        self.assertEqual(APP_VERSION, "1.25.0")
        self.assertEqual(APP_CHANNEL, "rc5")
        self.assertEqual(CURRENT_RELEASE, "1.25.0-rc5")

    def test_public_apis_use_their_fixed_production_https_origins(self):
        endpoint = (
            APP_DIR / "core" / "online_license_endpoint.json"
        ).read_text(encoding="utf-8")
        self.assertIn(LICENSE_API_ORIGIN, endpoint)
        self.assertEqual(FEEDBACK_API_ORIGIN, PUBLIC_CONTENT_API_ORIGIN)
        self.assertEqual(PUBLIC_ROADMAP_ORIGIN, PUBLIC_CONTENT_API_ORIGIN)

    def test_executable_installer_and_build_versions_are_rc5(self):
        version_info = (
            PROJECT_ROOT / "installer" / "version_info.txt"
        ).read_text(encoding="utf-8")
        installer = (
            PROJECT_ROOT / "installer" / "PokeyoyaKun_User_Setup.iss"
        ).read_text(encoding="utf-8")
        build_installer = (
            PROJECT_ROOT / "tools" / "build_user_installer.py"
        ).read_text(encoding="utf-8")
        self.assertIn("1.25.0.5", version_info)
        self.assertIn("1.25.0 RC5", version_info)
        self.assertIn("1.25.0 RC5 User Edition", installer)
        self.assertIn("PokeyoyaKun_User_Setup_Ver1.25.0_RC5", installer)
        self.assertIn("PokeyoyaKun_User_Setup_Ver1.25.0_RC5", build_installer)
        self.assertIn("user_dist_rc5", installer)
        self.assertIn("user_installer_rc5", installer)

    def test_tester_documents_mark_rc5_as_non_final(self):
        for name in (
            "USER_EDITION_README.txt",
            "RELEASE_NOTES_Ver1.25.0_RC5.txt",
            "TESTER_README_Ver1.25.0_RC5.txt",
        ):
            with self.subTest(name=name):
                text = (PROJECT_ROOT / name).read_text(encoding="utf-8")
                self.assertIn("RC5", text)
                self.assertIn("正式版ではありません", text)
                self.assertIn("3か月無料ライセンス", text)

    def test_rc5_documents_include_tls_and_yugioh_scope(self):
        for name in (
            "README.txt",
            "RELEASE_NOTES_Ver1.25.0_RC5.txt",
            "TESTER_README_Ver1.25.0_RC5.txt",
        ):
            text = (PROJECT_ROOT / name).read_text(encoding="utf-8")
            self.assertIn("遊戯王OCG", text)
            self.assertTrue("TLS" in text or "証明書" in text)
        self.assertEqual(display_name("yugioh"), "遊戯王OCG")

    def test_distribution_rejects_runtime_config_database_and_dpapi(self):
        forbidden = (
            "config/online_license_key.json",
            "data/user.sqlite3",
            "config/license_dpapi.bin",
        )
        for relative in forbidden:
            with self.subTest(relative=relative):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    path = root / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(b"must not ship")
                    self.assertTrue(verify_distribution(root))


if __name__ == "__main__":
    unittest.main()
