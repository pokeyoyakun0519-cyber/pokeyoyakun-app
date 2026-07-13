from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from core.external_notification_config import (
    ExternalNotificationConfig,
)
from core.external_notifier import ExternalNotifier


class TestNotificationThread(QThread):
    completed = Signal(dict)
    failed = Signal(str)

    def run(self):
        try:
            result = ExternalNotifier().send_test()
            self.completed.emit(result)
        except Exception as error:
            self.failed.emit(str(error))


class ExternalNotificationPage(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("ContentPanel")

        self.config_manager = ExternalNotificationConfig()
        self.test_thread = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 26)
        layout.setSpacing(14)

        title = QLabel("外部通知")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        description = QLabel(
            "監視結果をDiscordまたはメールへ送信します。\n"
            "DiscordはWebhookを使用します。"
            "メールはSMTPを使用します。"
        )
        description.setObjectName("MutedText")
        description.setWordWrap(True)
        layout.addWidget(description)

        discord_card = QFrame()
        discord_card.setObjectName("SettingsCard")
        discord_layout = QVBoxLayout(discord_card)

        discord_title = QLabel("Discord通知")
        discord_title.setObjectName("SectionTitle")

        self.discord_enabled = QCheckBox(
            "Discord通知を有効にする"
        )
        self.discord_webhook = QLineEdit()
        self.discord_webhook.setPlaceholderText(
            "https://discord.com/api/webhooks/..."
        )
        self.discord_webhook.setEchoMode(
            QLineEdit.Password
        )

        discord_layout.addWidget(discord_title)
        discord_layout.addWidget(self.discord_enabled)
        discord_layout.addWidget(self.discord_webhook)

        email_card = QFrame()
        email_card.setObjectName("SettingsCard")
        email_layout = QVBoxLayout(email_card)

        email_title = QLabel("メール通知")
        email_title.setObjectName("SectionTitle")
        email_layout.addWidget(email_title)

        self.email_enabled = QCheckBox(
            "メール通知を有効にする"
        )
        email_layout.addWidget(self.email_enabled)

        form = QFormLayout()

        self.smtp_host = QLineEdit()
        self.smtp_host.setPlaceholderText(
            "smtp.example.com"
        )

        self.smtp_port = QSpinBox()
        self.smtp_port.setRange(1, 65535)
        self.smtp_port.setValue(587)

        self.smtp_tls = QCheckBox(
            "STARTTLSを使用"
        )

        self.smtp_username = QLineEdit()
        self.smtp_password = QLineEdit()
        self.smtp_password.setEchoMode(
            QLineEdit.Password
        )

        self.email_from = QLineEdit()
        self.email_to = QLineEdit()

        form.addRow("SMTPサーバー", self.smtp_host)
        form.addRow("ポート", self.smtp_port)
        form.addRow("", self.smtp_tls)
        form.addRow("ユーザー名", self.smtp_username)
        form.addRow("パスワード", self.smtp_password)
        form.addRow("送信元", self.email_from)
        form.addRow("送信先", self.email_to)

        email_layout.addLayout(form)

        filter_card = QFrame()
        filter_card.setObjectName("SettingsCard")
        filter_layout = QVBoxLayout(filter_card)

        filter_title = QLabel("通知対象")
        filter_title.setObjectName("SectionTitle")

        self.notify_source_changes = QCheckBox(
            "公式情報の変更候補"
        )
        self.notify_lottery_wins = QCheckBox(
            "当選候補"
        )
        self.notify_errors = QCheckBox(
            "監視エラー"
        )

        filter_layout.addWidget(filter_title)
        filter_layout.addWidget(
            self.notify_source_changes
        )
        filter_layout.addWidget(
            self.notify_lottery_wins
        )
        filter_layout.addWidget(
            self.notify_errors
        )

        buttons = QHBoxLayout()

        save_button = QPushButton("設定を保存")
        save_button.setObjectName("AccentButton")
        save_button.clicked.connect(
            self.save_settings
        )

        test_button = QPushButton("テスト通知を送信")
        test_button.clicked.connect(
            self.send_test
        )

        buttons.addWidget(save_button)
        buttons.addWidget(test_button)
        buttons.addStretch()

        self.status = QLabel("")
        self.status.setObjectName("MutedText")
        self.status.setWordWrap(True)

        warning = QLabel(
            "注意：SMTPパスワードはこのPCの設定ファイルへ保存されます。"
            "通常のログインパスワードではなく、"
            "メールサービスのアプリパスワードを使用してください。"
        )
        warning.setObjectName("MutedText")
        warning.setWordWrap(True)

        layout.addWidget(discord_card)
        layout.addWidget(email_card)
        layout.addWidget(filter_card)
        layout.addLayout(buttons)
        layout.addWidget(self.status)
        layout.addWidget(warning)
        layout.addStretch()

        self.load_settings()

    def load_settings(self):
        config = self.config_manager.load()

        self.discord_enabled.setChecked(
            bool(config.get("discord_enabled", False))
        )
        self.discord_webhook.setText(
            str(config.get("discord_webhook_url", ""))
        )

        self.email_enabled.setChecked(
            bool(config.get("email_enabled", False))
        )
        self.smtp_host.setText(
            str(config.get("smtp_host", ""))
        )
        self.smtp_port.setValue(
            int(config.get("smtp_port", 587))
        )
        self.smtp_tls.setChecked(
            bool(config.get("smtp_use_tls", True))
        )
        self.smtp_username.setText(
            str(config.get("smtp_username", ""))
        )
        self.smtp_password.setText(
            str(config.get("smtp_password", ""))
        )
        self.email_from.setText(
            str(config.get("email_from", ""))
        )
        self.email_to.setText(
            str(config.get("email_to", ""))
        )

        self.notify_source_changes.setChecked(
            bool(config.get("notify_source_changes", True))
        )
        self.notify_lottery_wins.setChecked(
            bool(config.get("notify_lottery_wins", True))
        )
        self.notify_errors.setChecked(
            bool(config.get("notify_errors", True))
        )

    def save_settings(self):
        config = {
            "discord_enabled": (
                self.discord_enabled.isChecked()
            ),
            "discord_webhook_url": (
                self.discord_webhook.text().strip()
            ),
            "email_enabled": (
                self.email_enabled.isChecked()
            ),
            "smtp_host": self.smtp_host.text().strip(),
            "smtp_port": self.smtp_port.value(),
            "smtp_use_tls": self.smtp_tls.isChecked(),
            "smtp_username": (
                self.smtp_username.text().strip()
            ),
            "smtp_password": self.smtp_password.text(),
            "email_from": self.email_from.text().strip(),
            "email_to": self.email_to.text().strip(),
            "notify_source_changes": (
                self.notify_source_changes.isChecked()
            ),
            "notify_lottery_wins": (
                self.notify_lottery_wins.isChecked()
            ),
            "notify_errors": (
                self.notify_errors.isChecked()
            ),
        }

        self.config_manager.save(config)

        QMessageBox.information(
            self,
            "保存完了",
            "外部通知設定を保存しました。",
        )

    def send_test(self):
        self.save_settings()
        self.status.setText(
            "テスト通知を送信しています…"
        )

        self.test_thread = TestNotificationThread(
            self
        )
        self.test_thread.completed.connect(
            self._test_completed
        )
        self.test_thread.failed.connect(
            self._test_failed
        )
        self.test_thread.start()

    def _test_completed(self, result: dict):
        self.status.setText(
            "テスト結果："
            f"Discord={result.get('discord')} / "
            f"メール={result.get('email')}"
        )

    def _test_failed(self, message: str):
        self.status.setText(
            f"テスト通知に失敗しました：{message}"
        )
