from __future__ import annotations

import time
from contextlib import contextmanager

from PySide6.QtCore import QEvent, QEventLoop, QObject, Qt
from PySide6.QtWidgets import (
    QAbstractButton, QAbstractItemView, QApplication, QComboBox, QLineEdit,
    QPushButton, QWidget,
)


SPACING = 12
PAGE_MARGIN = 24
CONTROL_HEIGHT = 38
COMPACT_CONTROL_HEIGHT = 32
CARD_RADIUS = 12
ICON_SIZE = 18


TOOLTIP_HINTS = (
    ("今すぐ監視", "監視対象を今すぐ確認します"),
    ("状態を更新", "最新の状態を読み込みます"),
    ("再読込", "保存済みデータをもう一度読み込みます"),
    ("一覧を更新", "一覧を最新の状態へ更新します"),
    ("設定を保存", "変更した設定を保存します"),
    ("変更を保存", "未保存の変更を保存します"),
    ("CSV出力", "表示中の内容をCSVファイルへ保存します"),
    ("バックアップ", "現在の設定とデータをバックアップします"),
    ("削除", "選択したデータを削除します"),
    ("開く", "対応する画面またはページを開きます"),
    ("詳細", "選択した項目の詳細を表示します"),
    ("再実行", "セットアップウィザードをもう一度開きます"),
)

CARD_OBJECT_NAMES = {
    "SettingsCard", "ProductCard", "DashboardCard", "HomeSectionCard",
    "HomeSummaryCard", "GlobalSearchResults",
}


class UiPolishFilter(QObject):
    """既存画面へ軽量なサイズ・操作・アクセシビリティ調整を適用する。"""

    RAPID_CLICK_SECONDS = 0.35

    def eventFilter(self, watched, event):
        if isinstance(watched, QWidget) and event.type() in {
            QEvent.Polish, QEvent.Show,
        }:
            self.polish_widget(watched)

        if isinstance(watched, QPushButton):
            if event.type() == QEvent.MouseButtonPress and self._prevent_rapid_click(watched):
                return True
            if (
                event.type() == QEvent.KeyPress
                and event.isAutoRepeat()
                and event.key() in {Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space}
            ):
                return True
        return super().eventFilter(watched, event)

    def polish_widget(self, widget):
        if widget.property("uiPolished"):
            return
        widget.setProperty("uiPolished", True)

        self._normalize_layout(widget)

        if isinstance(widget, QAbstractButton):
            compact = widget.objectName() in {
                "SmallButton", "MenuSectionButton", "DeveloperMenuButton",
            }
            widget.setMinimumHeight(
                COMPACT_CONTROL_HEIGHT if compact else CONTROL_HEIGHT
            )
            widget.setFocusPolicy(Qt.StrongFocus)
            text = widget.text().replace("&", "").strip()
            if text and not widget.accessibleName():
                widget.setAccessibleName(text)
            if text and not widget.toolTip():
                tooltip = next(
                    (hint for keyword, hint in TOOLTIP_HINTS if keyword in text),
                    "",
                )
                if tooltip:
                    widget.setToolTip(tooltip)

        elif isinstance(widget, (QLineEdit, QComboBox)):
            widget.setMinimumHeight(CONTROL_HEIGHT)
            widget.setFocusPolicy(Qt.StrongFocus)

        elif isinstance(widget, QAbstractItemView):
            widget.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
            widget.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)

    @staticmethod
    def _normalize_layout(widget):
        """既存の代表的なページとカードだけを安全に共通寸法へ寄せる。"""
        # 一部の既存画面は ``self.layout`` 属性でQtのlayout()を隠している。
        layout = QWidget.layout(widget)
        if layout is None:
            return
        object_name = widget.objectName()
        if object_name == "ContentPanel":
            margins = layout.contentsMargins()
            current = (
                margins.left(), margins.top(), margins.right(), margins.bottom()
            )
            if current in {(28, 26, 28, 26), (24, 24, 24, 24)}:
                layout.setContentsMargins(
                    PAGE_MARGIN, PAGE_MARGIN, PAGE_MARGIN, PAGE_MARGIN
                )
            if layout.spacing() in {14, 16}:
                layout.setSpacing(SPACING)
        elif object_name in CARD_OBJECT_NAMES:
            layout.setContentsMargins(16, 16, 16, 16)
            if layout.spacing() > 10:
                layout.setSpacing(10)

    def _prevent_rapid_click(self, button):
        if (
            button.isCheckable()
            or button.objectName() == "NavigationButton"
            or button.property("allowRapidClick")
        ):
            return False
        now = time.monotonic()
        previous = float(button.property("lastAcceptedPress") or 0.0)
        if now - previous < self.RAPID_CLICK_SECONDS:
            return True
        button.setProperty("lastAcceptedPress", now)
        return False


def install_ui_polish(app: QApplication) -> UiPolishFilter:
    current = getattr(app, "_pokeyoya_ui_polish", None)
    if current is not None:
        return current
    event_filter = UiPolishFilter(app)
    app.installEventFilter(event_filter)
    app._pokeyoya_ui_polish = event_filter
    for widget in app.allWidgets():
        event_filter.polish_widget(widget)
    return event_filter


@contextmanager
def busy_button(button: QPushButton, text: str = "処理中…"):
    original = button.text()
    button.setEnabled(False)
    button.setProperty("busy", True)
    button.setText(text)
    button.style().unpolish(button)
    button.style().polish(button)
    QApplication.processEvents(QEventLoop.ExcludeUserInputEvents)
    try:
        yield
    finally:
        button.setText(original)
        button.setProperty("busy", False)
        button.setEnabled(True)
        button.style().unpolish(button)
        button.style().polish(button)
