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
from core.update_manager_base import current_tag
from core.version import APP_CHANNEL, APP_VERSION
from release_security import (
    EXPECTED_PUBLIC_LICENSE_ENDPOINT,
    verify_distribution,
    verify_public_license_endpoint,
)


LICENSE_ORIGIN = "https://api.pokeyoyakun.com"
LEGACY_SERVICE_ORIGIN = "https://pokeyoyakun.duckdns.org"


class Release125Rc4Test(unittest.TestCase):
    def test_application_and_update_version_are_rc4(self):
        self.assertEqual(APP_VERSION, "1.25.0")
        self.assertEqual(APP_CHANNEL, "rc4")
        self.assertEqual(current_tag(), "v1.25.0-rc4")

    def test_license_api_uses_production_origin_without_changing_other_services(self):
        endpoint = json.loads(
            (APP_DIR / "core" / "online_license_endpoint.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(endpoint["public_url"], LICENSE_ORIGIN)
        self.assertEqual(EXPECTED_PUBLIC_LICENSE_ENDPOINT, LICENSE_ORIGIN)
        self.assertEqual(FEEDBACK_API_ORIGIN, LEGACY_SERVICE_ORIGIN)
        self.assertEqual(PUBLIC_ROADMAP_ORIGIN, LEGACY_SERVICE_ORIGIN)

    def test_user_builds_include_and_validate_bundled_endpoint(self):
        pyinstaller = (PROJECT_ROOT / "tools" / "build_user_edition.py").read_text(
            encoding="utf-8"
        )
        nuitka = (
            PROJECT_ROOT / "tools" / "build_user_edition_nuitka.py"
        ).read_text(encoding="utf-8")
        for source in (pyinstaller, nuitka):
            self.assertIn("online_license_endpoint.json", source)
            self.assertIn("online_license_public_keys.json", source)
            self.assertIn("verify_public_license_endpoint", source)
        monitor_main = (APP_DIR / "monitor_main.py").read_text(encoding="utf-8")
        frozen_check = (
            PROJECT_ROOT / "tools" / "verify_frozen_license.py"
        ).read_text(encoding="utf-8")
        self.assertIn("--license-api-self-test", monitor_main)
        self.assertIn("--license-api-self-test", frozen_check)
        self.assertIn("--license-api-lifecycle-self-test", monitor_main)
        self.assertIn("--lifecycle", frozen_check)
        self.assertIn(LICENSE_ORIGIN, frozen_check)
        verify_public_license_endpoint(PROJECT_ROOT)

    def test_executable_installer_and_build_versions_are_rc4(self):
        version_info = (
            PROJECT_ROOT / "installer" / "version_info.txt"
        ).read_text(encoding="utf-8")
        installer = (
            PROJECT_ROOT / "installer" / "PokeyoyaKun_User_Setup.iss"
        ).read_text(encoding="utf-8")
        build_installer = (
            PROJECT_ROOT / "tools" / "build_user_installer.py"
        ).read_text(encoding="utf-8")
        build_bat = (PROJECT_ROOT / "BUILD_USER_EDITION.bat").read_text(
            encoding="utf-8"
        )
        self.assertIn("1.25.0.4", version_info)
        self.assertIn("1.25.0 RC4", version_info)
        self.assertIn("1.25.0 RC4 User Edition", installer)
        for source in (installer, build_installer, build_bat):
            self.assertIn("PokeyoyaKun_User_Setup_Ver1.25.0_RC4", source)
        self.assertIn("user_dist_rc4", installer)
        self.assertIn("user_installer_rc4", installer)
        self.assertIn("user_installer_rc4_vps_key", build_installer)
        self.assertIn("RC4_VPSKey", build_installer)

    def test_tester_documents_mark_rc4_as_non_final(self):
        for name in (
            "USER_EDITION_README.txt",
            "RELEASE_NOTES_Ver1.25.0_RC4.txt",
            "TESTER_README_Ver1.25.0_RC4.txt",
        ):
            with self.subTest(name=name):
                text = (PROJECT_ROOT / name).read_text(encoding="utf-8")
                self.assertIn("RC4", text)
                self.assertIn("正式版ではありません", text)
                self.assertIn("3か月無料ライセンス", text)
                self.assertIn(LICENSE_ORIGIN, text)

    def test_rc4_documents_keep_tls_yugioh_and_license_scope(self):
        readme = (PROJECT_ROOT / "README.txt").read_text(encoding="utf-8")
        notes = (PROJECT_ROOT / "RELEASE_NOTES_Ver1.25.0_RC4.txt").read_text(
            encoding="utf-8"
        )
        self.assertIn("遊戯王OCG", readme)
        self.assertIn("TLS", notes)
        self.assertIn(LICENSE_ORIGIN, readme)
        self.assertEqual(display_name("yugioh"), "遊戯王OCG")

    def test_endpoint_preflight_rejects_stale_build_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            endpoint = root / "app" / "core" / "online_license_endpoint.json"
            endpoint.parent.mkdir(parents=True)
            endpoint.write_text(
                json.dumps({"public_url": LEGACY_SERVICE_ORIGIN}),
                encoding="utf-8",
            )
            with self.assertRaises(SystemExit):
                verify_public_license_endpoint(root)

    def test_distribution_rejects_runtime_config_database_and_dpapi(self):
        forbidden = (
            "config/online_license_settings.json",
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
