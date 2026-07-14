from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
sys.path.insert(0, str(APP_DIR))

from core.online_license_client import OnlineLicenseClient
from core.online_license_config import DEFAULT_CONFIG, OnlineLicenseConfig
from core.release_config import ReleaseConfig


class FakeResponse:
    def __init__(self, data: dict):
        self.body = json.dumps(data).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self) -> bytes:
        return self.body


class OnlineLicenseConfigTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config = OnlineLicenseConfig()
        self.config.path = (
            Path(self.temp_dir.name) / "online_license_settings.json"
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_fresh_install_uses_external_server(self):
        loaded = self.config.load()
        self.assertTrue(loaded["enabled"])
        self.assertEqual(
            loaded["server_url"],
            "http://180.24.86.226:8765",
        )

    def test_legacy_disabled_localhost_is_migrated(self):
        self.config.path.write_text(
            json.dumps(
                {
                    "enabled": False,
                    "server_url": "http://127.0.0.1:8765",
                    "timeout_seconds": 10,
                    "offline_grace_hours": 72,
                }
            ),
            encoding="utf-8",
        )
        loaded = self.config.load()
        self.assertEqual(loaded, DEFAULT_CONFIG)

    def test_release_channel_ignores_local_server_override(self):
        self.config.save(
            {
                "enabled": True,
                "server_url": "http://127.0.0.1:8765/",
            }
        )
        loaded = self.config.load()
        self.assertEqual(
            loaded["server_url"],
            DEFAULT_CONFIG["server_url"],
        )

    def test_developer_mode_can_change_server_url(self):
        config = OnlineLicenseConfig(ReleaseConfig(channel="dev"))
        config.path = Path(self.temp_dir.name) / "developer-settings.json"
        config.save({"server_url": "http://127.0.0.1:8765/"})
        self.assertEqual(config.load()["server_url"], "http://127.0.0.1:8765")

    def test_invalid_url_is_rejected(self):
        valid, _ = self.config.validate_server_url("ftp://example.com")
        self.assertFalse(valid)
        developer_config = OnlineLicenseConfig(ReleaseConfig(channel="dev"))
        developer_config.path = Path(self.temp_dir.name) / "invalid.json"
        with self.assertRaises(ValueError):
            developer_config.save({"server_url": "not-a-url"})


class OnlineLicenseClientTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.client = OnlineLicenseClient()
        self.client.config_manager.path = (
            Path(self.temp_dir.name) / "settings.json"
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    @patch("core.online_license_client.urllib.request.urlopen")
    def test_connection_uses_health_endpoint(self, urlopen):
        urlopen.return_value = FakeResponse(
            {"ok": True, "message": "ready"}
        )
        ok, message = self.client.test_connection()
        self.assertTrue(ok, message)
        request = urlopen.call_args.args[0]
        self.assertEqual(
            request.full_url,
            "http://180.24.86.226:8765/health",
        )

    @patch("core.online_license_client.get_device_id", return_value="PC-1")
    @patch("core.online_license_client.urllib.request.urlopen")
    def test_activate_posts_expected_payload(self, urlopen, _device_id):
        urlopen.return_value = FakeResponse(
            {
                "ok": True,
                "message": "認証成功",
                "expires_at": "2027-01-01T00:00:00+00:00",
            }
        )
        ok, message, _ = self.client.activate(" pky-test ")
        self.assertTrue(ok, message)
        request = urlopen.call_args.args[0]
        self.assertEqual(
            request.full_url,
            "http://180.24.86.226:8765/api/v1/licenses/activate",
        )
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(payload["license_key"], "PKY-TEST")
        self.assertEqual(payload["device_id"], "PC-1")
        self.assertEqual(payload["app_version"], "1.24.0")

    @patch("core.online_license_client.get_device_id", return_value="PC-1")
    @patch("core.online_license_client.urllib.request.urlopen")
    def test_server_rejection_does_not_use_offline_cache(
        self,
        urlopen,
        _device_id,
    ):
        urlopen.return_value = FakeResponse(
            {"ok": False, "message": "このライセンスは停止されています。"}
        )
        ok, message, _ = self.client.verify("PKY-TEST")
        self.assertFalse(ok)
        self.assertIn("停止", message)

    @patch("core.online_license_client.get_device_id", return_value="PC-1")
    @patch("core.online_license_client.urllib.request.urlopen")
    def test_network_failure_never_grants_offline_access(self, urlopen, _device_id):
        import urllib.error

        urlopen.side_effect = urllib.error.URLError("timed out")
        ok, message, _ = self.client.verify("PKY-TEST")
        self.assertFalse(ok)
        self.assertIn("タイムアウト", message)


if __name__ == "__main__":
    unittest.main()
