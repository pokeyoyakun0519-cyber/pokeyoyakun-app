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

from core.license_manager import LicenseManager
from core.online_license_config import OnlineLicenseConfig


class OnlineLicensePage(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("ContentPanel")
        self.config_manager = OnlineLicenseConfig()
        self.license_manager = LicenseManager()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            28,
            26,
            28,
            26,
        )
        layout.setSpacing(14)

        title = QLabel("オンラインライセンス")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        description = QLabel(
            "ライセンスサーバーのURL、有効期限確認、"
            "端末紐付け、停止状態の確認を管理します。"
            "サーバーへ接続できない場合は、直近の正常認証から"
            "設定した時間だけオフライン起動できます。"
        )
        description.setObjectName("MutedText")
        description.setWordWrap(True)
        layout.addWidget(description)

        card = QFrame()
        card.setObjectName("SettingsCard")
        form = QFormLayout(card)

        self.enabled = QCheckBox(
            "オンラインライセンスを有効にする"
        )

        self.server_url = QLineEdit()
        self.server_url.setPlaceholderText(
            "https://license.example.com"
        )

        self.timeout = QSpinBox()
        self.timeout.setRange(3, 60)
        self.timeout.setSuffix(" 秒")

        self.grace = QSpinBox()
        self.grace.setRange(0, 720)
        self.grace.setSuffix(" 時間")

        form.addRow(self.enabled)
        form.addRow(
            "ライセンスサーバーURL",
            self.server_url,
        )
        form.addRow(
            "接続タイムアウト",
            self.timeout,
        )
        form.addRow(
            "オフライン猶予",
            self.grace,
        )
        layout.addWidget(card)

        button_row = QHBoxLayout()

        save_button = QPushButton("設定を保存")
        save_button.setObjectName(
            "AccentButton"
        )
        save_button.clicked.connect(
            self.save_settings
        )

        verify_button = QPushButton(
            "登録済みキーを確認"
        )
        verify_button.clicked.connect(
            self.verify_registered_key
        )

        button_row.addWidget(save_button)
        button_row.addWidget(verify_button)
        button_row.addStretch()
        layout.addLayout(button_row)

        self.status = QLabel("")
        self.status.setObjectName("SectionTitle")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        note = QLabel(
            "User Editionにはライセンスサーバーを同梱していません。"
            "管理者から案内された公開URLを指定してください。"
            "本番公開ではHTTPS・ドメイン・バックアップ・"
            "管理者認証の設定を推奨します。"
        )
        note.setObjectName("MutedText")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch()

        self.load_settings()

    def load_settings(self):
        config = self.config_manager.load()
        self.enabled.setChecked(
            bool(config.get("enabled", False))
        )
        self.server_url.setText(
            str(config.get("server_url", ""))
        )
        self.timeout.setValue(
            int(config.get("timeout_seconds", 10))
        )
        self.grace.setValue(
            int(config.get("offline_grace_hours", 72))
        )
        key = self.license_manager.load_online_key()
        self.status.setText(
            "登録済みキー："
            + (
                self._mask_key(key)
                if key
                else "なし"
            )
        )

    def save_settings(self):
        self.config_manager.save(
            {
                "enabled": self.enabled.isChecked(),
                "server_url": self.server_url.text().strip(),
                "timeout_seconds": self.timeout.value(),
                "offline_grace_hours": self.grace.value(),
            }
        )
        QMessageBox.information(
            self,
            "保存完了",
            "オンラインライセンス設定を保存しました。",
        )

    def verify_registered_key(self):
        ok, message = (
            self.license_manager.verify_online()
        )
        self.status.setText(message)
        QMessageBox.information(
            self,
            "ライセンス確認"
            if ok
            else "ライセンス確認失敗",
            message,
        )

    @staticmethod
    def _mask_key(key: str) -> str:
        if len(key) <= 8:
            return "****"
        return key[:4] + "-****-****-" + key[-4:]
