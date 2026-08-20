from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QDialog, QFrame, QHBoxLayout,
    QLabel, QPushButton, QRadioButton, QScrollArea, QStackedWidget,
    QVBoxLayout, QWidget,
)

from core.runtime_paths import is_frozen
from core.setup_coordinator import SETUP_VERSION, SUPPORTED_TCG_KEYS, SetupCoordinator


TCG_LABELS = {
    "pokemon": "ポケモンカード",
    "onepiece": "ワンピースカード",
    "gundam": "ガンダムカードゲーム",
    "union_arena": "UNION ARENA",
    "dragon_ball_fusion_world": "DBSCG フュージョンワールド",
    "yugioh": "遊戯王OCG",
}


def owner_settings_runtime() -> bool:
    return is_frozen() and "owner" in Path(sys.executable).stem.casefold()


class SetupWizard(QDialog):
    completed = Signal(dict)

    def __init__(self, *, coordinator=None, owner_edition=False, parent=None):
        super().__init__(parent)
        self.coordinator = coordinator or SetupCoordinator()
        self.owner_edition = bool(owner_edition)
        self.initial_values = self.coordinator.current_values()
        self.setWindowTitle("ポケヨヤ君 初回セットアップ")
        self.setModal(True)
        self.resize(760, 610)
        self.setMinimumSize(600, 480)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)
        self.progress_label = QLabel("")
        self.progress_label.setObjectName("SetupProgress")
        root.addWidget(self.progress_label)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        self.pages = QStackedWidget()
        scroll.setWidget(self.pages)
        root.addWidget(scroll, 1)

        self._build_pages()

        self.error_label = QLabel("")
        self.error_label.setObjectName("SetupError")
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        root.addWidget(self.error_label)

        buttons = QHBoxLayout()
        self.cancel_button = QPushButton("キャンセル(&C)")
        self.back_button = QPushButton("戻る(&B)")
        self.skip_button = QPushButton("スキップ(&S)")
        self.next_button = QPushButton("次へ(&N)")
        self.next_button.setObjectName("AccentButton")
        self.next_button.setDefault(True)
        self.cancel_button.clicked.connect(self.reject)
        self.back_button.clicked.connect(self._back)
        self.skip_button.clicked.connect(self._skip)
        self.next_button.clicked.connect(self._next)
        buttons.addWidget(self.cancel_button)
        buttons.addStretch()
        buttons.addWidget(self.back_button)
        buttons.addWidget(self.skip_button)
        buttons.addWidget(self.next_button)
        root.addLayout(buttons)
        self.pages.currentChanged.connect(self._update_navigation)
        self._update_navigation(0)

    def _page(self, title, description):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(14)
        heading = QLabel(title)
        heading.setObjectName("PageTitle")
        text = QLabel(description)
        text.setObjectName("PageText")
        text.setWordWrap(True)
        layout.addWidget(heading)
        layout.addWidget(text)
        self.pages.addWidget(page)
        return layout

    def _build_pages(self):
        welcome = self._page(
            "ようこそ",
            "ポケヨヤ君は、TCG商品の発売・予約・抽選応募をまとめて確認し、"
            "締切や結果発表を見逃さないためのアプリです。\n\n"
            "このウィザードでは、利用開始に必要な最低限の設定だけを行います。",
        )
        edition = "Owner Edition（開発者向け機能を含みます）" if self.owner_edition else "User Edition"
        edition_label = QLabel(f"対象エディション: {edition}")
        edition_label.setObjectName("SetupInfo")
        welcome.addWidget(edition_label)
        welcome.addStretch()

        display = self._page("表示モード", "必須：使いやすい表示モードを選択してください。後から設定画面で変更できます。")
        self.mode_group = QButtonGroup(self)
        self.simple_mode = QRadioButton("かんたんモード — 日常的に使う機能だけを表示")
        self.detailed_mode = QRadioButton("詳細モード — すべての機能と開発者向け項目を表示")
        self.mode_group.addButton(self.simple_mode)
        self.mode_group.addButton(self.detailed_mode)
        (self.detailed_mode if self.initial_values["ui_mode"] == "detailed" else self.simple_mode).setChecked(True)
        display.addWidget(self.simple_mode)
        display.addWidget(self.detailed_mode)
        display.addStretch()

        tcg = self._page("監視対象TCG", "必須：監視するTCGを1つ以上選択してください。")
        self.tcg_checks = {}
        selected = set(self.initial_values["tcg_keys"])
        for key in SUPPORTED_TCG_KEYS:
            checkbox = QCheckBox(TCG_LABELS[key])
            checkbox.setChecked(key in selected)
            self.tcg_checks[key] = checkbox
            tcg.addWidget(checkbox)
        tcg.addStretch()

        notification = self._page(
            "通知設定",
            "任意：締切や情報変更をWindows上で知らせる方法を選択します。"
            "Discordなどの外部通知は、セットアップ完了後に設定できます。",
        )
        self.popup_enabled = QCheckBox("ポップアップ通知を表示する")
        self.sound_enabled = QCheckBox("通知音を鳴らす")
        self.popup_enabled.setChecked(self.initial_values["show_popup"])
        self.sound_enabled.setChecked(self.initial_values["play_notification_sound"])
        notification.addWidget(self.popup_enabled)
        notification.addWidget(self.sound_enabled)
        notification.addStretch()

        gmail = self._page(
            "Gmail連携",
            "任意：Gmailの抽選結果メールを確認できます。連携は必須ではなく、後からいつでも設定できます。",
        )
        self.gmail_group = QButtonGroup(self)
        self.gmail_now = QRadioButton("完了後にGmail設定を開く")
        self.gmail_later = QRadioButton("後で設定する（推奨）")
        self.gmail_group.addButton(self.gmail_now)
        self.gmail_group.addButton(self.gmail_later)
        self.gmail_later.setChecked(True)
        gmail.addWidget(self.gmail_now)
        gmail.addWidget(self.gmail_later)
        gmail.addStretch()

        monitoring = self._page("自動監視", "任意：指定した間隔で商品・応募情報を自動確認します。")
        self.monitoring_enabled = QCheckBox("自動監視を有効にする")
        self.monitoring_enabled.setChecked(self.initial_values["monitoring_enabled"])
        self.interval_combo = QComboBox()
        for minutes, label in ((15, "15分ごと"), (30, "30分ごと"), (60, "1時間ごと"), (180, "3時間ごと"), (360, "6時間ごと")):
            self.interval_combo.addItem(label, minutes)
        index = self.interval_combo.findData(self.initial_values["interval_minutes"])
        self.interval_combo.setCurrentIndex(index if index >= 0 else self.interval_combo.findData(30))
        self.interval_combo.setEnabled(self.monitoring_enabled.isChecked())
        self.monitoring_enabled.toggled.connect(self.interval_combo.setEnabled)
        monitoring.addWidget(self.monitoring_enabled)
        monitoring.addWidget(self.interval_combo)
        monitoring.addStretch()

        final = self._page("最終確認", "以下の内容を確認し、「セットアップを完了」を押してください。")
        self.summary_label = QLabel("")
        self.summary_label.setObjectName("SetupSummary")
        self.summary_label.setWordWrap(True)
        self.summary_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        final.addWidget(self.summary_label)
        final.addStretch()

    def selected_values(self):
        return {
            "ui_mode": "detailed" if self.detailed_mode.isChecked() else "simple",
            "tcg_keys": [key for key, checkbox in self.tcg_checks.items() if checkbox.isChecked()],
            "show_popup": self.popup_enabled.isChecked(),
            "play_notification_sound": self.sound_enabled.isChecked(),
            "gmail_setup_now": self.gmail_now.isChecked(),
            "monitoring_enabled": self.monitoring_enabled.isChecked(),
            "interval_minutes": int(self.interval_combo.currentData()),
        }

    def _next(self):
        self._clear_error()
        index = self.pages.currentIndex()
        if index == 2 and not any(checkbox.isChecked() for checkbox in self.tcg_checks.values()):
            self._show_error("監視対象TCGを1つ以上選択してください。")
            return
        if index == self.pages.count() - 1:
            self._finish()
            return
        self.pages.setCurrentIndex(index + 1)

    def _back(self):
        self._clear_error()
        self.pages.setCurrentIndex(max(0, self.pages.currentIndex() - 1))

    def _skip(self):
        self._clear_error()
        self.pages.setCurrentIndex(min(self.pages.count() - 1, self.pages.currentIndex() + 1))

    def _update_navigation(self, index):
        self.progress_label.setText(f"ステップ {index + 1} / {self.pages.count()}")
        self.back_button.setEnabled(index > 0)
        self.skip_button.setVisible(index in {3, 4, 5})
        self.next_button.setText("セットアップを完了(&F)" if index == self.pages.count() - 1 else "次へ(&N)")
        if index == self.pages.count() - 1:
            self._update_summary()
        self._clear_error()

    def _update_summary(self):
        values = self.selected_values()
        tcg_names = "、".join(TCG_LABELS[key] for key in values["tcg_keys"]) or "未選択"
        self.summary_label.setText(
            f'表示モード：{"詳細モード" if values["ui_mode"] == "detailed" else "かんたんモード"}\n\n'
            f"監視対象TCG：{tcg_names}\n\n"
            f'ポップアップ：{"有効" if values["show_popup"] else "無効"}\n'
            f'通知音：{"有効" if values["play_notification_sound"] else "無効"}\n\n'
            f'Gmail連携：{"完了後に設定" if values["gmail_setup_now"] else "後で設定"}\n\n'
            f'自動監視：{"有効" if values["monitoring_enabled"] else "無効"}\n'
            f'監視頻度：{self.interval_combo.currentText()}\n\n'
            f"セットアップ設定バージョン：{SETUP_VERSION}"
        )

    def _finish(self):
        values = self.selected_values()
        try:
            saved = self.coordinator.complete(values)
        except Exception as error:
            self._show_error(f"設定を保存できませんでした。原因: {type(error).__name__}: {error}")
            return
        self.completed.emit(saved)
        self.accept()

    def _show_error(self, message):
        self.error_label.setText(message)
        self.error_label.show()

    def _clear_error(self):
        self.error_label.clear()
        self.error_label.hide()


class GmailSetupDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Gmail連携設定")
        self.resize(900, 680)
        self.setMinimumSize(650, 480)
        layout = QVBoxLayout(self)
        from ui.email_accounts_page import EmailAccountsPage

        layout.addWidget(EmailAccountsPage())
