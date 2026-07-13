from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QVBoxLayout,
)

from core.log_manager import LogManager
from core.notification_manager import NotificationManager


class NotificationPage(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("ContentPanel")

        self.log_manager = LogManager()
        self.notification_manager = NotificationManager()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 26)
        layout.setSpacing(14)

        title = QLabel("通知・ログ")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        description = QLabel(
            "通知音とポップアップの動作確認、過去の動作履歴の確認ができます。"
        )
        description.setObjectName("MutedText")
        layout.addWidget(description)

        buttons = QHBoxLayout()

        test_button = QPushButton("テスト通知を送る")
        test_button.setObjectName("AccentButton")
        test_button.clicked.connect(self.send_test_notification)

        refresh_button = QPushButton("ログを更新")
        refresh_button.clicked.connect(self.refresh_log)

        clear_button = QPushButton("ログを削除")
        clear_button.setObjectName("DangerButton")
        clear_button.clicked.connect(self.clear_log)

        buttons.addWidget(test_button)
        buttons.addWidget(refresh_button)
        buttons.addWidget(clear_button)
        buttons.addStretch()

        layout.addLayout(buttons)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setObjectName("LogView")
        layout.addWidget(self.log_view, 1)

        self.refresh_log()

    def send_test_notification(self) -> None:
        self.notification_manager.notify(
            self,
            "ポケヨヤ君 テスト通知",
            "通知機能は正常に動作しています。",
        )
        self.refresh_log()

    def refresh_log(self) -> None:
        self.log_view.setPlainText(self.log_manager.read_recent())

    def clear_log(self) -> None:
        answer = QMessageBox.question(
            self,
            "ログ削除",
            "保存されている動作ログを削除しますか？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if answer == QMessageBox.Yes:
            self.log_manager.clear()
            self.refresh_log()
