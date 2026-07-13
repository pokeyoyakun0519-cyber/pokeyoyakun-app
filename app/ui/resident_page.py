from PySide6.QtWidgets import (
    QCheckBox, QFrame, QLabel, QMessageBox, QPushButton, QVBoxLayout,
)
from core.autostart_manager import AutoStartError, AutoStartManager
from core.behavior_config import BehaviorConfig

class ResidentPage(QFrame):
    def __init__(self, tray_controller=None):
        super().__init__()
        self.setObjectName("ContentPanel")
        self.tray_controller = tray_controller
        self.config = BehaviorConfig()
        self.autostart_manager = AutoStartManager()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 26)
        layout.setSpacing(16)

        title = QLabel("常駐・自動起動")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        description = QLabel(
            "画面を閉じてもタスクトレイで自動監視を続けられます。"
        )
        description.setObjectName("MutedText")
        description.setWordWrap(True)
        layout.addWidget(description)

        card = QFrame()
        card.setObjectName("SettingsCard")
        card_layout = QVBoxLayout(card)

        self.autostart = QCheckBox("Windowsログイン時に自動起動")
        self.start_minimized = QCheckBox("自動起動時は最小化して開始")
        self.minimize_to_tray = QCheckBox("最小化時にタスクトレイへ格納")
        self.close_to_tray = QCheckBox("閉じるボタンでタスクトレイへ格納")
        self.show_notifications = QCheckBox("タスクトレイ通知を表示")

        save_button = QPushButton("設定を保存")
        save_button.setObjectName("AccentButton")
        save_button.clicked.connect(self.save_settings)

        hide_button = QPushButton("今すぐタスクトレイへ格納")
        hide_button.clicked.connect(self.hide_now)

        for widget in (
            self.autostart, self.start_minimized, self.minimize_to_tray,
            self.close_to_tray, self.show_notifications,
            save_button, hide_button,
        ):
            card_layout.addWidget(widget)

        layout.addWidget(card)
        layout.addStretch()
        self.load_settings()

    def load_settings(self):
        config = self.config.load()
        self.autostart.setChecked(self.autostart_manager.is_enabled())
        self.start_minimized.setChecked(config.get("start_minimized", False))
        self.minimize_to_tray.setChecked(config.get("minimize_to_tray", True))
        self.close_to_tray.setChecked(config.get("close_to_tray", True))
        self.show_notifications.setChecked(
            config.get("show_tray_notifications", True)
        )

    def save_settings(self):
        try:
            self.autostart_manager.set_enabled(self.autostart.isChecked())
        except AutoStartError as error:
            QMessageBox.critical(self, "自動起動設定エラー", str(error))
            return

        self.config.save({
            "start_minimized": self.start_minimized.isChecked(),
            "minimize_to_tray": self.minimize_to_tray.isChecked(),
            "close_to_tray": self.close_to_tray.isChecked(),
            "show_tray_notifications": self.show_notifications.isChecked(),
        })
        QMessageBox.information(self, "保存完了", "設定を保存しました。")

    def hide_now(self):
        if self.tray_controller is None:
            QMessageBox.information(
                self, "未初期化", "タスクトレイがまだ利用できません。"
            )
            return
        self.tray_controller.hide_window()
