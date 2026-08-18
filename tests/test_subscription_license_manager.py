from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "app"))

from core.license_manager import LicenseManager


class SubscriptionLicenseManagerTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.manager = LicenseManager()
        self.manager.online_key_path = Path(self.temp_dir.name) / "online.json"
        self.manager.online_client = Mock()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_request_code_does_not_persist_any_credential(self):
        self.manager.online_client.request_subscription_code.return_value = (
            True,
            "送信しました。",
            {},
        )
        ok, message = self.manager.request_subscription_code("buyer@example.com")
        self.assertTrue(ok, message)
        self.assertFalse(self.manager.online_key_path.exists())

    def test_signed_subscription_activation_persists_internal_key(self):
        self.manager.online_client.activate_subscription.return_value = (
            True,
            "認証しました。",
            {"license_key": "pky-internal-subscription"},
        )
        ok, message = self.manager.activate_subscription(
            "buyer@example.com",
            "123456",
        )
        self.assertTrue(ok, message)
        self.assertEqual(
            self.manager.load_online_key(),
            "PKY-INTERNAL-SUBSCRIPTION",
        )

    def test_rejected_subscription_does_not_replace_existing_manual_key(self):
        self.manager.save_online_key("PKY-EXISTING-MANUAL")
        self.manager.online_client.activate_subscription.return_value = (
            False,
            "契約を確認できません。",
            {},
        )
        ok, _ = self.manager.activate_subscription(
            "buyer@example.com",
            "123456",
        )
        self.assertFalse(ok)
        self.assertEqual(self.manager.load_online_key(), "PKY-EXISTING-MANUAL")

    def test_success_without_internal_key_is_rejected(self):
        self.manager.online_client.activate_subscription.return_value = (
            True,
            "認証しました。",
            {},
        )
        ok, message = self.manager.activate_subscription(
            "buyer@example.com",
            "123456",
        )
        self.assertFalse(ok)
        self.assertIn("保存", message)
        self.assertFalse(self.manager.online_key_path.exists())


if __name__ == "__main__":
    unittest.main()
