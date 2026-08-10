from __future__ import annotations

import ast
import os
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
TOOLS_DIR = PROJECT_ROOT / "tools"
sys.path.insert(0, str(APP_DIR))
sys.path.insert(0, str(TOOLS_DIR))


def _source(relative: str) -> str:
    return (PROJECT_ROOT / relative).read_text(encoding="utf-8")


class OwnerEditionSeparationTest(unittest.TestCase):
    def test_build_flavor_is_fixed_in_separate_build_scripts(self):
        user = _source("tools/build_user_edition.py")
        owner = _source("tools/build_owner_edition.py")
        self.assertIn("BUILD_OWNER_EDITION = False", user)
        self.assertIn("BUILD_OWNER_EDITION = True", owner)
        self.assertNotIn("owner_main.py", user)
        self.assertIn('APP_DIR / "owner_main.py"', owner)
        self.assertNotIn("os.environ", owner)

    def test_owner_entrypoint_has_no_license_authentication_path(self):
        source = _source("app/owner_main.py")
        tree = ast.parse(source)
        imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        for forbidden in (
            "license_dialog",
            "license_manager",
            "online_license_client",
            "online_license_config",
        ):
            self.assertFalse(any(forbidden in name for name in imports))
        self.assertIn("OwnerMainWindow", source)
        self.assertNotIn("authenticated", source)

    def test_owner_window_omits_license_page_and_marks_distribution_forbidden(self):
        source = _source("app/ui/owner_main_window.py")
        self.assertIn("Owner Edition", source)
        self.assertIn("開発者専用・配布禁止", source)
        self.assertIn('item[0] != "online_license_button"', source)
        self.assertNotIn("OnlineLicensePage", source)
        tree = ast.parse(source)
        method = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_add_license_page"
        )
        self.assertTrue(any(isinstance(node, ast.Return) for node in method.body))

    def test_normal_user_edition_still_requires_authentication(self):
        entrypoint = _source("app/monitor_main.py")
        main_window = _source("app/ui/main_window.py")
        self.assertIn("LicenseDialog", entrypoint)
        self.assertIn("login.authenticated", entrypoint)
        self.assertIn("OnlineLicensePage", main_window)
        self.assertIn("online_license_button", main_window)

    def test_config_and_environment_cannot_enable_owner_mode(self):
        owner_entry = _source("app/owner_main.py")
        self.assertNotIn("os.environ", owner_entry)
        self.assertNotIn("--owner", owner_entry.lower())
        for folder in (APP_DIR / "core", APP_DIR / "ui"):
            for path in folder.rglob("*.py"):
                if path.name == "owner_main_window.py":
                    continue
                text = path.read_text(encoding="utf-8", errors="ignore")
                self.assertNotIn("OWNER_EDITION_BUILD", text)
                self.assertNotIn("BUILD_OWNER_EDITION", text)
        for variable in ("OWNER_EDITION", "POKEYOYAKUN_OWNER", "OWNER_MODE"):
            self.assertNotIn(variable, os.environ)

    def test_owner_binary_excludes_license_modules_and_endpoint(self):
        build = _source("tools/build_owner_edition.py")
        for module in (
            "ui.license_dialog",
            "ui.online_license_page",
            "core.license_manager",
            "core.online_license_client",
            "core.online_license_config",
        ):
            self.assertIn(f'"{module}"', build)
        self.assertNotIn("online_license_endpoint.json", build)
        self.assertIn('"certifi\\\\cacert.pem"', build)
        self.assertIn("open_embedded_archive", build)
        self.assertIn("included_forbidden", build)

    def test_owner_outputs_are_separate_and_never_public_assets(self):
        builder = _source("tools/build_owner_edition.py")
        installer = _source("installer/PokeyoyaKun_Owner_Setup.iss")
        public_assets = _source("tools/prepare_github_assets_125_rc5.py")
        self.assertIn('"owner_dist_rc5"', builder)
        self.assertIn("owner_installer_rc5", installer)
        self.assertIn("PokeyoyaKun_OwnerEdition.exe", installer)
        self.assertNotIn("Owner", public_assets)
        self.assertNotIn("owner_", public_assets.lower())

    def test_owner_build_retains_certifi_tls_and_external_features(self):
        build = _source("tools/build_owner_edition.py")
        owner_window = _source("app/ui/owner_main_window.py")
        main_window = _source("app/ui/main_window.py")
        self.assertIn('"--collect-data"', build)
        self.assertIn('"certifi"', build)
        self.assertIn("feedback_button", owner_window)
        self.assertIn("public_roadmap_button", owner_window)
        self.assertIn("FeedbackPage", main_window)
        self.assertIn("PublicRoadmapPage", main_window)
        for relative in ("app/core/feedback_api.py", "app/core/public_roadmap.py"):
            source = _source(relative)
            self.assertIn("build_https_opener", source)
            self.assertNotIn("_create_unverified_context", source)
            self.assertNotIn("CERT_NONE", source)

    def test_owner_metadata_and_readme_are_explicit(self):
        version = _source("installer/owner_version_info.txt")
        readme = _source("OWNER_EDITION_README.txt")
        self.assertIn("1.25.0 RC5 Owner", version)
        self.assertIn("PokeyoyaKun_OwnerEdition.exe", version)
        self.assertIn("開発者専用・配布禁止", readme)
        self.assertIn("GitHub Releases", readme)
        self.assertIn("環境変数", readme)
        self.assertIn("設定ファイル", readme)

    def test_user_installer_and_public_builder_remain_owner_free(self):
        for relative in (
            "installer/PokeyoyaKun_User_Setup.iss",
            "tools/build_user_installer.py",
            "tools/prepare_github_assets_125_rc5.py",
        ):
            text = _source(relative)
            self.assertNotIn("Owner Edition", text)
            self.assertNotIn("owner_dist", text.lower())


if __name__ == "__main__":
    unittest.main()
