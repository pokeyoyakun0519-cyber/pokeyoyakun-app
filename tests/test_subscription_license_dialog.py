from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "app"))

try:
    from PySide6.QtWidgets import QApplication
    from ui.license_dialog import LicenseDialog
except ModuleNotFoundError:
    QApplication = None
    LicenseDialog = None


class SubscriptionLicenseDialogSourceTest(unittest.TestCase):
    def test_passwordless_flow_and_legacy_fallback_are_wired(self):
        source = (PROJECT_ROOT / "app" / "ui" / "license_dialog.py").read_text(
            encoding="utf-8"
        )
        for marker in (
            "request_subscription_code",
            "activate_subscription",
            "6桁の認証コード",
            "既存のライセンスキーを使用",
            "self.legacy_panel.setVisible(False)",
        ):
            self.assertIn(marker, source)


@unittest.skipIf(QApplication is None, "PySide6 runtime is not installed")
class SubscriptionLicenseDialogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.dialog = LicenseDialog()

    def tearDown(self):
        self.dialog.close()

    def test_passwordless_subscription_flow_is_primary(self):
        self.assertTrue(self.dialog.subscription_email.isVisibleTo(self.dialog))
        self.assertTrue(self.dialog.subscription_code.isVisibleTo(self.dialog))
        self.assertFalse(self.dialog.legacy_panel.isVisibleTo(self.dialog))
        self.assertEqual(self.dialog.subscription_code.maxLength(), 6)
        self.assertEqual(self.dialog.online_key.echoMode(), self.dialog.online_key.Password)

    def test_legacy_manual_license_remains_available_but_collapsed(self):
        self.dialog.legacy_toggle.click()
        self.assertTrue(self.dialog.legacy_panel.isVisibleTo(self.dialog))
        self.dialog.legacy_toggle.click()
        self.assertFalse(self.dialog.legacy_panel.isVisibleTo(self.dialog))

    def test_resend_button_has_sixty_second_client_cooldown(self):
        self.dialog.manager.request_subscription_code = lambda _email: (
            True,
            "送信しました。",
        )
        self.dialog.subscription_email.setText("buyer@example.com")
        self.dialog.send_subscription_code()
        self.assertEqual(self.dialog._resend_seconds, 60)
        self.assertFalse(self.dialog.send_code_button.isEnabled())
        self.dialog._update_resend_cooldown()
        self.assertEqual(self.dialog._resend_seconds, 59)


if __name__ == "__main__":
    unittest.main()
