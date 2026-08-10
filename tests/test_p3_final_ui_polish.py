from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from PySide6.QtWidgets import (
    QApplication, QFrame, QLineEdit, QPushButton, QVBoxLayout,
)

from core.app_setup import configure_application, configure_high_dpi
from ui.design_system import (
    CARD_RADIUS, CONTROL_HEIGHT, ICON_SIZE, PAGE_MARGIN, SPACING,
    UiPolishFilter, busy_button, install_ui_polish,
)
from ui.style import PALETTE, STYLE


class FinalUiPolishTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_design_tokens_and_dark_theme_are_centralized(self):
        self.assertEqual((PAGE_MARGIN, SPACING), (24, 12))
        self.assertEqual((CONTROL_HEIGHT, CARD_RADIUS, ICON_SIZE), (38, 12, 18))
        for key in ("background", "surface", "card", "primary", "success", "warning", "error"):
            self.assertRegex(PALETTE[key], r"^#[0-9a-fA-F]{6}$")
        self.assertIn("icon-size: 18px", STYLE)
        self.assertIn("QPushButton:focus", STYLE)
        self.assertIn('QLabel[state="error"]', STYLE)

    def test_application_polish_is_installed_only_once(self):
        configure_application(self.app)
        first = install_ui_polish(self.app)
        second = install_ui_polish(self.app)
        self.assertIs(first, second)
        self.assertIn("QWidget", self.app.styleSheet())
        self.assertEqual(self.app.font().family(), "Yu Gothic UI")

    def test_controls_receive_accessible_size_focus_and_tooltip(self):
        polish = UiPolishFilter()
        button = QPushButton("設定を保存")
        edit = QLineEdit()
        polish.polish_widget(button)
        polish.polish_widget(edit)
        self.assertGreaterEqual(button.minimumHeight(), CONTROL_HEIGHT)
        self.assertEqual(button.accessibleName(), "設定を保存")
        self.assertTrue(button.toolTip())
        self.assertGreaterEqual(edit.minimumHeight(), CONTROL_HEIGHT)
        button.close()
        edit.close()

    def test_page_and_card_layouts_are_normalized(self):
        polish = UiPolishFilter()
        page = QFrame()
        page.setObjectName("ContentPanel")
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(28, 26, 28, 26)
        page_layout.setSpacing(14)
        polish.polish_widget(page)
        margins = page_layout.contentsMargins()
        self.assertEqual(
            (margins.left(), margins.top(), margins.right(), margins.bottom()),
            (24, 24, 24, 24),
        )
        self.assertEqual(page_layout.spacing(), 12)

        card = QFrame()
        card.setObjectName("HomeSectionCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(18, 16, 18, 16)
        card_layout.setSpacing(12)
        polish.polish_widget(card)
        card_margins = card_layout.contentsMargins()
        self.assertEqual(
            (card_margins.left(), card_margins.top(), card_margins.right(), card_margins.bottom()),
            (16, 16, 16, 16),
        )
        self.assertEqual(card_layout.spacing(), 10)
        page.close()
        card.close()

    def test_rapid_double_click_is_blocked_without_affecting_navigation(self):
        polish = UiPolishFilter()
        button = QPushButton("実行")
        self.assertFalse(polish._prevent_rapid_click(button))
        self.assertTrue(polish._prevent_rapid_click(button))
        navigation = QPushButton("ホーム")
        navigation.setObjectName("NavigationButton")
        navigation.setCheckable(True)
        self.assertFalse(polish._prevent_rapid_click(navigation))
        button.close()
        navigation.close()

    def test_busy_button_restores_state_on_success_and_error(self):
        button = QPushButton("開始")
        with busy_button(button, "処理中…"):
            self.assertFalse(button.isEnabled())
            self.assertEqual(button.text(), "処理中…")
            self.assertTrue(button.property("busy"))
        self.assertTrue(button.isEnabled())
        self.assertEqual(button.text(), "開始")

        with self.assertRaisesRegex(RuntimeError, "failure"):
            with busy_button(button):
                raise RuntimeError("failure")
        self.assertTrue(button.isEnabled())
        self.assertEqual(button.text(), "開始")
        button.close()

    def test_high_dpi_policy_is_configured_before_application_creation(self):
        with patch("core.app_setup.QGuiApplication.instance", return_value=None), patch(
            "core.app_setup.QGuiApplication.setHighDpiScaleFactorRoundingPolicy"
        ) as setter:
            configure_high_dpi()
        setter.assert_called_once()


if __name__ == "__main__":
    unittest.main()
