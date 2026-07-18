from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from PySide6.QtWidgets import QApplication, QMessageBox


class SettingsRenewalTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_page(self, directory):
        from ui.settings_page import SettingsPage

        environment = patch.dict(
            "os.environ", {"POKEYOYA_DATA_ROOT": directory}, clear=False
        )
        environment.start()
        self.addCleanup(environment.stop)
        page = SettingsPage()
        self.addCleanup(page.close)
        return page

    def test_categories_and_simple_mode_show_only_major_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            page = self.make_page(directory)
            self.assertEqual(tuple(page.category_pages), page.CATEGORY_NAMES)
            visible = {
                name
                for name, widget in page.category_pages.items()
                if page.category_tabs.isTabVisible(page.category_tabs.indexOf(widget))
            }
            self.assertEqual(visible, page.SIMPLE_CATEGORIES)
            self.assertFalse(page.has_unsaved_changes)
            self.assertEqual(page.save_status.text(), "変更はありません。")

    def test_detailed_mode_shows_all_categories_and_search_filters_cards(self):
        with tempfile.TemporaryDirectory() as directory:
            page = self.make_page(directory)
            page.ui_mode.setCurrentIndex(page.ui_mode.findData("detailed"))
            visible = {
                name
                for name, widget in page.category_pages.items()
                if page.category_tabs.isTabVisible(page.category_tabs.indexOf(widget))
            }
            self.assertEqual(visible, set(page.CATEGORY_NAMES))

            page.settings_search.setText("パスワード")
            self.assertEqual(page.search_result_label.text(), "1件")
            visible = [item for item in page.setting_cards if not item["card"].isHidden()]
            self.assertEqual(len(visible), 1)
            self.assertEqual(visible[0]["category"], "アカウント・連携")

    def test_changed_widget_and_unsaved_status_are_visible(self):
        with tempfile.TemporaryDirectory() as directory:
            page = self.make_page(directory)
            page.popup_enabled.setChecked(not page.popup_enabled.isChecked())
            self.assertTrue(page.has_unsaved_changes)
            self.assertTrue(page.popup_enabled.property("settingsChanged"))
            self.assertIn("未保存の変更", page.save_status.text())
            self.assertEqual(page.save_button.text(), "変更を保存")

            page.popup_enabled.setChecked(not page.popup_enabled.isChecked())
            self.assertFalse(page.has_unsaved_changes)
            self.assertFalse(page.popup_enabled.property("settingsChanged"))

    def test_save_success_clears_dirty_state_and_shows_success(self):
        with tempfile.TemporaryDirectory() as directory:
            page = self.make_page(directory)
            page.name_input.setText("テスト利用者")
            with (
                patch.object(page.credential_store, "save_password"),
                patch.object(QMessageBox, "information"),
            ):
                page.save_settings()
            self.assertFalse(page.has_unsaved_changes)
            self.assertEqual(page.save_status.property("state"), "success")
            self.assertIn("設定を保存しました", page.save_status.text())

    def test_save_failure_keeps_dirty_state_and_reports_cause(self):
        with tempfile.TemporaryDirectory() as directory:
            page = self.make_page(directory)
            page.email_input.setText("test@example.jp")
            with (
                patch.object(page.config_manager, "save", side_effect=PermissionError("書き込み権限がありません")),
                patch.object(QMessageBox, "critical"),
            ):
                page.save_settings()
            self.assertTrue(page.has_unsaved_changes)
            self.assertEqual(page.save_status.property("state"), "error")
            self.assertIn("PermissionError", page.save_status.text())
            self.assertIn("書き込み権限がありません", page.save_status.text())

    def test_user_and_owner_use_the_common_settings_page(self):
        from ui.owner_main_window import OwnerMainWindow
        from ui.settings_page import SettingsPage
        from ui.settings_window import SettingsWindow

        with tempfile.TemporaryDirectory() as directory, patch.dict(
            "os.environ", {"POKEYOYA_DATA_ROOT": directory}, clear=False
        ):
            window = SettingsWindow()
            self.assertIsInstance(window.centralWidget(), SettingsPage)
            self.assertEqual(OwnerMainWindow.SETTINGS_EXECUTABLE, "PokeyoyaKun_Owner_Settings.exe")
            window.close()


if __name__ == "__main__":
    unittest.main()
