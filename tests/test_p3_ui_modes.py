from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from PySide6.QtWidgets import QApplication, QMessageBox

from core.config_manager import ConfigManager


class UiModeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_first_launch_defaults_to_simple_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            config = ConfigManager(Path(directory)).load()
            self.assertEqual(config["general"]["ui_mode"], "simple")

    def test_settings_page_saves_detailed_mode(self):
        from ui.settings_page import SettingsPage

        with tempfile.TemporaryDirectory() as directory, patch.dict(
            "os.environ", {"POKEYOYA_DATA_ROOT": directory}, clear=False
        ):
            page = SettingsPage()
            page.ui_mode.setCurrentIndex(page.ui_mode.findData("detailed"))
            with (
                patch.object(page.credential_store, "save_password"),
                patch.object(QMessageBox, "information"),
            ):
                page.save_settings()
            saved = ConfigManager(Path(directory)).load()
            self.assertEqual(saved["general"]["ui_mode"], "detailed")
            page.close()

    def test_user_simple_mode_and_runtime_switch(self):
        from ui.main_window import MainWindow

        with tempfile.TemporaryDirectory() as directory, patch.dict(
            "os.environ", {"POKEYOYA_DATA_ROOT": directory}, clear=False
        ):
            window = MainWindow()
            self.assertEqual(window.ui_mode, "simple")
            expected = {
                window.home_button,
                window.product_button,
                window.application_dashboard_button,
                window.calendar_button,
                window.notification_center_button,
                window.scheduler_button,
            }
            for button in window.navigation_buttons:
                self.assertEqual(
                    not button.isHidden(),
                    button in expected,
                    button.text(),
                )
            self.assertFalse(window.open_settings_button.isHidden())
            self.assertTrue(window.menu_sections["その他"][0].isHidden())
            self.assertTrue(window.developer_menu_button.isHidden())

            manager = ConfigManager(Path(directory))
            config = manager.load()
            config["general"]["ui_mode"] = "detailed"
            manager.save(config)
            window._reload_ui_mode()

            self.assertEqual(window.ui_mode, "detailed")
            self.assertTrue(all(not button.isHidden() for button in window.navigation_buttons))
            self.assertFalse(window.menu_sections["その他"][0].isHidden())
            self.assertFalse(window.developer_menu_button.isHidden())
            self.assertFalse(window.developer_menu_container.isHidden())
            window.close()

    def test_user_and_owner_restore_saved_mode(self):
        from ui.main_window import MainWindow
        from ui.owner_main_window import OwnerMainWindow

        for window_type in (MainWindow, OwnerMainWindow):
            with self.subTest(window_type=window_type.__name__), tempfile.TemporaryDirectory() as directory, patch.dict(
                "os.environ", {"POKEYOYA_DATA_ROOT": directory}, clear=False
            ):
                manager = ConfigManager(Path(directory))
                config = manager.load()
                config["general"]["ui_mode"] = "detailed"
                manager.save(config)
                window = window_type()
                self.assertEqual(window.ui_mode, "detailed")
                self.assertFalse(window.developer_menu_container.isHidden())
                if window_type is OwnerMainWindow:
                    self.assertFalse(hasattr(window, "online_license_button"))
                window.close()


if __name__ == "__main__":
    unittest.main()
