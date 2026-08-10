from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from core.config_manager import ConfigManager
from core.scheduler_config import SchedulerConfig
from core.setup_coordinator import SETUP_VERSION, SetupCoordinator


def completed_values(**overrides):
    values = {
        "ui_mode": "simple",
        "tcg_keys": ["pokemon", "onepiece"],
        "show_popup": True,
        "play_notification_sound": True,
        "gmail_setup_now": False,
        "monitoring_enabled": False,
        "interval_minutes": 30,
    }
    values.update(overrides)
    return values


class SetupCoordinatorTest(unittest.TestCase):
    def test_completion_updates_existing_structures_at_once(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manager = ConfigManager(root)
            config = manager.load()
            config["profile"]["email"] = "existing@example.jp"
            config["general"]["show_ended_applications"] = True
            manager.save(config)

            saved = SetupCoordinator(root).complete(completed_values(
                ui_mode="detailed", tcg_keys=["pokemon", "yugioh"],
                show_popup=False, play_notification_sound=False,
                monitoring_enabled=True, interval_minutes=60,
            ))
            config = manager.load()
            scheduler = SchedulerConfig(root).load()
            self.assertTrue(config["general"]["setup_completed"])
            self.assertEqual(config["general"]["setup_version"], SETUP_VERSION)
            self.assertEqual(config["general"]["ui_mode"], "detailed")
            self.assertFalse(config["general"]["show_popup"])
            self.assertEqual(config["profile"]["email"], "existing@example.jp")
            self.assertTrue(config["general"]["show_ended_applications"])
            self.assertTrue(config["games"]["pokemon"])
            self.assertFalse(config["games"]["onepiece"])
            self.assertTrue(config["games"]["yugioh"])
            self.assertTrue(scheduler["enabled"])
            self.assertEqual(scheduler["interval_minutes"], 60)
            self.assertEqual(saved["ui_mode"], "detailed")

    def test_invalid_required_values_are_not_saved(self):
        with tempfile.TemporaryDirectory() as directory:
            coordinator = SetupCoordinator(Path(directory))
            before = coordinator.config_manager.load()
            with self.assertRaisesRegex(ValueError, "1つ以上"):
                coordinator.complete(completed_values(tcg_keys=[]))
            self.assertEqual(coordinator.config_manager.load(), before)
            self.assertFalse(coordinator.is_completed())

    def test_scheduler_failure_rolls_back_main_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            coordinator = SetupCoordinator(Path(directory))
            before = coordinator.config_manager.load()
            with patch.object(
                coordinator.scheduler_config, "save", side_effect=OSError("保存失敗")
            ):
                with self.assertRaises(OSError):
                    coordinator.complete(completed_values())
            self.assertEqual(coordinator.config_manager.load(), before)


class SetupWizardUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_first_start_shows_once_and_completion_returns_home(self):
        from ui.main_window import MainWindow

        with tempfile.TemporaryDirectory() as directory, patch.dict(
            "os.environ", {"POKEYOYA_DATA_ROOT": directory}, clear=False
        ):
            first = MainWindow()
            self.app.processEvents()
            QTest.qWait(20)
            self.app.processEvents()
            self.assertIsNotNone(first.setup_wizard)
            self.assertTrue(first.setup_wizard.isVisible())
            self.assertFalse(first.setup_wizard.owner_edition)
            first.pages.setCurrentWidget(first.product_page)
            first.setup_wizard._finish()
            self.app.processEvents()
            self.assertTrue(SetupCoordinator(Path(directory)).is_completed())
            self.assertIs(first.pages.currentWidget(), first.home_page)
            first.close()

            second = MainWindow()
            self.app.processEvents()
            QTest.qWait(20)
            self.app.processEvents()
            self.assertIsNone(second.setup_wizard)
            second.close()

    def test_cancel_does_not_change_existing_settings(self):
        from ui.setup_wizard import SetupWizard

        with tempfile.TemporaryDirectory() as directory:
            coordinator = SetupCoordinator(Path(directory))
            before_config = coordinator.config_manager.load()
            before_scheduler = coordinator.scheduler_config.load()
            wizard = SetupWizard(coordinator=coordinator)
            wizard.detailed_mode.setChecked(True)
            wizard.popup_enabled.setChecked(False)
            wizard.monitoring_enabled.setChecked(True)
            wizard.reject()
            self.assertEqual(coordinator.config_manager.load(), before_config)
            self.assertEqual(coordinator.scheduler_config.load(), before_scheduler)
            self.assertFalse(coordinator.is_completed())

    def test_required_error_is_inline_and_navigation_buttons_are_accessible(self):
        from ui.setup_wizard import SetupWizard

        with tempfile.TemporaryDirectory() as directory:
            wizard = SetupWizard(coordinator=SetupCoordinator(Path(directory)))
            wizard.pages.setCurrentIndex(2)
            for checkbox in wizard.tcg_checks.values():
                checkbox.setChecked(False)
            wizard._next()
            self.assertEqual(wizard.pages.currentIndex(), 2)
            self.assertFalse(wizard.error_label.isHidden())
            self.assertIn("1つ以上", wizard.error_label.text())
            self.assertTrue(wizard.next_button.isDefault())
            wizard.close()

    def test_settings_page_rerun_uses_current_values_and_saves_on_completion(self):
        from ui.settings_page import SettingsPage

        with tempfile.TemporaryDirectory() as directory, patch.dict(
            "os.environ", {"POKEYOYA_DATA_ROOT": directory}, clear=False
        ):
            SetupCoordinator(Path(directory)).complete(completed_values(
                ui_mode="detailed", tcg_keys=["gundam"], interval_minutes=180
            ))
            page = SettingsPage()
            wizard = page.open_setup_wizard()
            self.assertIsNotNone(wizard)
            self.assertTrue(wizard.detailed_mode.isChecked())
            self.assertTrue(wizard.tcg_checks["gundam"].isChecked())
            self.assertFalse(wizard.tcg_checks["pokemon"].isChecked())
            self.assertEqual(wizard.interval_combo.currentData(), 180)
            wizard.simple_mode.setChecked(True)
            wizard.tcg_checks["pokemon"].setChecked(True)
            wizard._finish()
            self.app.processEvents()
            self.assertEqual(page.ui_mode.currentData(), "simple")
            self.assertTrue(page.game_checks["pokemon"].isChecked())
            self.assertIn("初回セットアップ設定を保存", page.save_status.text())
            page.close()

    def test_regular_settings_save_preserves_setup_completion(self):
        from ui.settings_page import SettingsPage

        with tempfile.TemporaryDirectory() as directory, patch.dict(
            "os.environ", {"POKEYOYA_DATA_ROOT": directory}, clear=False
        ):
            SetupCoordinator(Path(directory)).complete(completed_values())
            page = SettingsPage()
            page.popup_enabled.setChecked(False)
            with (
                patch.object(page.credential_store, "save_password"),
                patch.object(QMessageBox, "information"),
            ):
                page.save_settings()
            general = ConfigManager(Path(directory)).load()["general"]
            self.assertTrue(general["setup_completed"])
            self.assertEqual(general["setup_version"], SETUP_VERSION)
            page.close()

    def test_owner_main_uses_owner_wizard(self):
        from ui.owner_main_window import OwnerMainWindow

        with tempfile.TemporaryDirectory() as directory, patch.dict(
            "os.environ", {"POKEYOYA_DATA_ROOT": directory}, clear=False
        ):
            window = OwnerMainWindow()
            self.app.processEvents()
            QTest.qWait(20)
            self.app.processEvents()
            self.assertTrue(window.setup_wizard.owner_edition)
            self.assertTrue(any(
                "Owner Edition" in label.text()
                for label in window.setup_wizard.findChildren(type(window.setup_wizard.progress_label))
            ))
            window.close()

    def test_frozen_path_and_owner_settings_detection(self):
        from core.runtime_paths import APP_FOLDER_NAME
        from ui.setup_wizard import owner_settings_runtime

        with tempfile.TemporaryDirectory() as directory, patch.dict(
            "os.environ",
            {"POKEYOYA_DATA_ROOT": "", "LOCALAPPDATA": directory},
            clear=False,
        ), patch.object(sys, "frozen", True, create=True), patch.object(
            sys, "executable", str(Path(directory) / "PokeyoyaKun_Owner_Settings.exe")
        ):
            coordinator = SetupCoordinator()
            self.assertEqual(
                coordinator.config_manager.config_path,
                Path(directory) / APP_FOLDER_NAME / "config" / "settings.json",
            )
            self.assertTrue(owner_settings_runtime())


if __name__ == "__main__":
    unittest.main()
