from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from PySide6.QtWidgets import QApplication


class SidebarRenewalTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_user_prioritizes_five_sections_and_hides_developer_items(self):
        from ui.main_window import MainWindow

        with tempfile.TemporaryDirectory() as directory, patch.dict(
            "os.environ", {"POKEYOYA_DATA_ROOT": directory}, clear=False
        ):
            window = MainWindow()
            self.assertEqual(
                list(window.menu_sections),
                ["商品・応募", "監視", "通知", "その他", "設定"],
            )
            self.assertFalse(window.menu_sections["商品・応募"][1].isHidden())
            self.assertFalse(window.menu_sections["監視"][1].isHidden())
            self.assertFalse(window.menu_sections["通知"][1].isHidden())
            self.assertTrue(window.menu_sections["その他"][1].isHidden())
            self.assertTrue(window.developer_menu_container.isHidden())
            for button in (
                window.self_test_button,
                window.regression_button,
                window.release_readiness_button,
            ):
                self.assertIn(button, window.page_map)
                self.assertIs(button.parentWidget(), window.developer_menu_container)
            window.menu_sections["その他"][0].setChecked(True)
            window.developer_menu_button.setChecked(True)
            self.assertFalse(window.developer_menu_container.isHidden())
            window.close()

    def test_owner_keeps_license_omitted_and_opens_developer_menu(self):
        from core.config_manager import ConfigManager
        from ui.owner_main_window import OwnerMainWindow

        with tempfile.TemporaryDirectory() as directory, patch.dict(
            "os.environ", {"POKEYOYA_DATA_ROOT": directory}, clear=False
        ):
            config_manager = ConfigManager(Path(directory))
            config = config_manager.load()
            config["general"]["ui_mode"] = "detailed"
            config_manager.save(config)
            window = OwnerMainWindow()
            self.assertFalse(hasattr(window, "online_license_button"))
            self.assertEqual(window.developer_menu_button.text(), "Owner開発者メニュー")
            self.assertFalse(window.menu_sections["その他"][1].isHidden())
            self.assertFalse(window.developer_menu_container.isHidden())
            self.assertIn(window.self_test_button, window.page_map)
            window.close()


if __name__ == "__main__":
    unittest.main()
