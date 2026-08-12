from __future__ import annotations

import json
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
from release_security import (
    EXPECTED_PUBLIC_LICENSE_ENDPOINT,
    verify_distribution,
    verify_public_license_endpoint,
)


LICENSE_API_ORIGIN = "https://api.pokeyoyakun.com"
PUBLIC_CONTENT_API_ORIGIN = "https://pokeyoyakun.duckdns.org"


class Release125Rc5Test(unittest.TestCase):
    def test_application_version_is_rc5(self):
        self.assertEqual(APP_VERSION, "1.25.0")
        self.assertEqual(APP_CHANNEL, "rc5")
        self.assertEqual(CURRENT_RELEASE, "1.25.0-rc5")

    def test_public_apis_use_their_fixed_production_https_origins(self):
        endpoint = json.loads((
            APP_DIR / "core" / "online_license_endpoint.json"
        ).read_text(encoding="utf-8"))
        self.assertEqual(endpoint["public_url"], LICENSE_API_ORIGIN)
        self.assertEqual(EXPECTED_PUBLIC_LICENSE_ENDPOINT, LICENSE_API_ORIGIN)
        self.assertEqual(FEEDBACK_API_ORIGIN, PUBLIC_CONTENT_API_ORIGIN)
        self.assertEqual(PUBLIC_ROADMAP_ORIGIN, PUBLIC_CONTENT_API_ORIGIN)

    def test_user_builds_include_and_validate_license_material(self):
        pyinstaller = (
            PROJECT_ROOT / "tools" / "build_user_edition.py"
        ).read_text(encoding="utf-8")
        nuitka = (
            PROJECT_ROOT / "tools" / "build_user_edition_nuitka.py"
        ).read_text(encoding="utf-8")
        for source in (pyinstaller, nuitka):
            self.assertIn("online_license_endpoint.json", source)
            self.assertIn("online_license_public_keys.json", source)
            self.assertIn("verify_public_license_endpoint", source)
        self.assertIn(
            "--license-api-lifecycle-self-test",
            (APP_DIR / "monitor_main.py").read_text(encoding="utf-8"),
        )
        self.assertIn(
            "online-2026-07-vps",
            (
                PROJECT_ROOT / "tools" / "verify_frozen_license.py"
            ).read_text(encoding="utf-8"),
        )
        frozen_verifier = (
            PROJECT_ROOT / "tools" / "verify_frozen_license.py"
        ).read_text(encoding="utf-8")
        self.assertIn("user_dist_rc5", frozen_verifier)
        self.assertNotIn("user_dist_rc4", frozen_verifier)
        verify_public_license_endpoint(PROJECT_ROOT)

    def test_endpoint_preflight_rejects_stale_build_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            endpoint = root / "app" / "core" / "online_license_endpoint.json"
            endpoint.parent.mkdir(parents=True)
            endpoint.write_text(
                json.dumps({"public_url": PUBLIC_CONTENT_API_ORIGIN}),
                encoding="utf-8",
            )
            with self.assertRaises(SystemExit):
                verify_public_license_endpoint(root)

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
        self.assertIn("1.25.0.51", version_info)
        self.assertIn("1.25.0 RC5.1", version_info)
        self.assertIn("1.25.0 RC5.1 User Edition", installer)
        self.assertIn("PokeyoyaKun_User_Setup_Ver1.25.0_RC5.1", installer)
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
