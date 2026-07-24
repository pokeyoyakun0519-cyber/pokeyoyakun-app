from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from core.gmail_result_service import (
    GmailDependencyError,
    GmailOAuthConfigurationError,
    GmailResultService,
)


class GmailRuntimeDiagnosticsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.service = GmailResultService.__new__(GmailResultService)
        self.service.client_secret_path = (
            self.root / "config" / "google_client_secret.json"
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_missing_library_names_are_reported_separately(self):
        original = __import__("importlib").import_module

        def import_module(name):
            if name == "google_auth_oauthlib.flow":
                raise ImportError("missing test module")
            return original(name)

        with patch(
            "core.gmail_result_service.importlib.import_module",
            side_effect=import_module,
        ):
            with self.assertRaises(GmailDependencyError) as captured:
                self.service.require_dependencies()
        self.assertIn("google-auth-oauthlib", str(captured.exception))
        self.assertNotIn("google_client_secret.json", str(captured.exception))

    def test_missing_oauth_file_reports_the_exact_search_location(self):
        with self.assertRaises(GmailOAuthConfigurationError) as captured:
            self.service.validate_client_secret()
        message = str(captured.exception)
        self.assertIn("OAuth設定ファイルが未配置", message)
        self.assertIn(str(self.service.client_secret_path), message)

    def test_invalid_oauth_json_is_not_reported_as_missing_library(self):
        self.service.client_secret_path.parent.mkdir(parents=True)
        self.service.client_secret_path.write_text(
            '{"web":{"client_id":"wrong-type"}}',
            encoding="utf-8",
        )
        with self.assertRaises(GmailOAuthConfigurationError) as captured:
            self.service.validate_client_secret()
        self.assertIn("OAuth設定エラー", str(captured.exception))
        self.assertNotIn("ライブラリが不足", str(captured.exception))

    def test_valid_desktop_oauth_json_passes_validation(self):
        self.service.client_secret_path.parent.mkdir(parents=True)
        payload = {
            "installed": {
                "client_id": "test.apps.googleusercontent.com",
                "client_" + "secret": "unit-test-placeholder",
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": ["http://localhost"],
            }
        }
        self.service.client_secret_path.write_text(
            json.dumps(payload),
            encoding="utf-8",
        )
        self.assertEqual(
            self.service.validate_client_secret()["installed"]["client_id"],
            payload["installed"]["client_id"],
        )

    def test_source_environment_has_all_gmail_dependencies(self):
        self.assertEqual(GmailResultService.missing_dependencies(), [])


if __name__ == "__main__":
    unittest.main()
