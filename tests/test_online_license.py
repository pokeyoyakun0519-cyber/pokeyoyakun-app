from __future__ import annotations

import json
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
sys.path.insert(0, str(APP_DIR))

from core.online_license_client import (
    HttpsOnlyRedirectHandler,
    OnlineLicenseClient,
)
from core.online_license_config import (
    UNCONFIGURED_PUBLIC_URL,
    OnlineLicenseConfig,
    is_public_endpoint_configured,
    load_bundled_public_url,
    validate_public_server_url,
)
from core.release_config import ReleaseConfig


PRODUCTION_URL = "https://pokeyoyakun.duckdns.org"


class FakeResponse:
    def __init__(self, data: dict):
        self.body = json.dumps(data).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self) -> bytes:
        return self.body


class FakeOpener:
    def __init__(self, response: FakeResponse | None = None, error=None):
        self.response = response
        self.error = error
        self.request = None

    def open(self, request, timeout):
        self.request = request
        if self.error is not None:
            raise self.error
        return self.response


class OnlineLicenseConfigTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config = OnlineLicenseConfig()
        self.config.path = Path(self.temp_dir.name) / "settings.json"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_fresh_install_uses_production_https_endpoint(self):
        loaded = self.config.load()
        self.assertTrue(loaded["enabled"])
        self.assertEqual(loaded["server_url"], PRODUCTION_URL)
        self.assertTrue(loaded["endpoint_configured"])
        self.assertFalse(loaded["configuration_error"])

    def test_release_channel_ignores_legacy_runtime_override(self):
        legacy_url = "http" + "://127.0.0.1:" + str(8700 + 65)
        self.config.path.write_text(
            json.dumps({"enabled": True, "server_url": legacy_url}),
            encoding="utf-8",
        )
        loaded = self.config.load()
        self.assertTrue(loaded["enabled"])
        self.assertEqual(loaded["server_url"], PRODUCTION_URL)

    def test_developer_mode_accepts_only_production_grade_https(self):
        config = OnlineLicenseConfig(ReleaseConfig(channel="dev"))
        config.path = Path(self.temp_dir.name) / "developer-settings.json"
        config.save({"enabled": True, "server_url": PRODUCTION_URL + "/"})
        self.assertEqual(config.load()["server_url"], PRODUCTION_URL)
        self.assertTrue(config.load()["enabled"])

    def test_public_url_validation_rejects_unsafe_destinations(self):
        self.assertEqual(
            validate_public_server_url(PRODUCTION_URL + "/"),
            PRODUCTION_URL,
        )
        unsafe = (
            "http" + "://pokeyoyakun.duckdns.org",
            "https://203.0.113.10",
            PRODUCTION_URL + ":" + str(8700 + 65),
            UNCONFIGURED_PUBLIC_URL,
            PRODUCTION_URL + "/unexpected/path",
        )
        for value in unsafe:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    validate_public_server_url(value)
        self.assertTrue(is_public_endpoint_configured(PRODUCTION_URL))

    def test_bundled_endpoint_is_https_and_client_sources_have_no_direct_port(self):
        endpoint = load_bundled_public_url()
        self.assertEqual(endpoint, PRODUCTION_URL)
        direct_port = ":" + str(8700 + 65)
        local_http = "http" + "://127.0.0.1"
        named_http = "http" + "://license"
        for relative in (
            "core/online_license_endpoint.json",
            "core/online_license_config.py",
            "core/online_license_client.py",
        ):
            source = (APP_DIR / relative).read_text(encoding="utf-8")
            self.assertNotIn(direct_port, source)
            self.assertNotIn(local_http, source)
            self.assertNotIn(named_http, source)


class OnlineLicenseClientTest(unittest.TestCase):
    def setUp(self):
        self.client = OnlineLicenseClient()
        self.config = {
            "enabled": True,
            "server_url": PRODUCTION_URL,
            "timeout_seconds": 10,
            "offline_grace_hours": 0,
        }

    @patch("core.online_license_client.build_https_opener")
    def test_connection_uses_https_health_endpoint(self, build_opener):
        opener = FakeOpener(FakeResponse({"ok": True, "message": "ready"}))
        build_opener.return_value = opener
        with patch.object(self.client.config_manager, "load", return_value=self.config):
            ok, message = self.client.test_connection()
        self.assertTrue(ok, message)
        self.assertEqual(opener.request.full_url, PRODUCTION_URL + "/health")
        self.assertIsInstance(
            build_opener.call_args.args[0],
            HttpsOnlyRedirectHandler,
        )

    @patch("core.online_license_client.get_device_id", return_value="PC-1")
    @patch("core.online_license_client.build_https_opener")
    def test_activate_posts_expected_https_payload(self, build_opener, _device_id):
        opener = FakeOpener(
            FakeResponse({"ok": True, "message": "認証成功"})
        )
        build_opener.return_value = opener
        with patch.object(self.client.config_manager, "load", return_value=self.config):
            ok, message, _ = self.client.activate(" pky-test ")
        self.assertTrue(ok, message)
        self.assertEqual(
            opener.request.full_url,
            PRODUCTION_URL + "/api/v1/licenses/activate",
        )
        self.assertIsInstance(
            build_opener.call_args.args[0],
            HttpsOnlyRedirectHandler,
        )
        payload = json.loads(opener.request.data.decode("utf-8"))
        self.assertEqual(payload["license_key"], "PKY-TEST")
        self.assertEqual(payload["device_id"], "PC-1")

    def test_redirect_handler_rejects_non_https_and_other_hosts(self):
        handler = HttpsOnlyRedirectHandler(PRODUCTION_URL)
        request = urllib.request.Request(PRODUCTION_URL + "/health")
        unsafe_targets = (
            "http" + "://pokeyoyakun.duckdns.org/health",
            "https://other.duckdns.org/health",
            PRODUCTION_URL + ":" + str(8700 + 65) + "/health",
        )
        for target in unsafe_targets:
            with self.subTest(target=target):
                with self.assertRaises(urllib.error.URLError):
                    handler.redirect_request(
                        request,
                        None,
                        307,
                        "Temporary Redirect",
                        {},
                        target,
                    )

    @patch("core.online_license_client.build_https_opener")
    def test_server_rejection_is_not_replaced_by_local_success(self, build_opener):
        build_opener.return_value = FakeOpener(
            FakeResponse({"ok": False, "message": "このライセンスは停止されています。"})
        )
        with patch.object(self.client.config_manager, "load", return_value=self.config):
            ok, message, _ = self.client.verify("PKY-TEST")
        self.assertFalse(ok)
        self.assertIn("停止", message)

    @patch("core.online_license_client.build_https_opener")
    def test_network_failure_never_grants_access(self, build_opener):
        build_opener.return_value = FakeOpener(
            error=urllib.error.URLError("timed out")
        )
        with patch.object(self.client.config_manager, "load", return_value=self.config):
            ok, message, _ = self.client.verify("PKY-TEST")
        self.assertFalse(ok)
        self.assertIn("タイムアウト", message)


if __name__ == "__main__":
    unittest.main()
