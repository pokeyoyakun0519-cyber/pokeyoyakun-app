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
from core.release_config import ReleaseConfig


class OnlineLicensePage(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("ContentPanel")
        self.release_config = ReleaseConfig()
        self.config_manager = OnlineLicenseConfig(self.release_config)
        self.license_manager = LicenseManager()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 26)
        layout.setSpacing(14)

        title = QLabel("オンラインライセンス")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        description = QLabel(
            "登録済みキーをライセンスサーバーへ問い合わせ、"
            "サーバーが返した判定結果を確認します。"
            "ローカルキャッシュだけで起動を許可することはありません。"
        )
        description.setObjectName("MutedText")
        description.setWordWrap(True)
        layout.addWidget(description)

        card = QFrame()
        card.setObjectName("SettingsCard")
        form = QFormLayout(card)

        self.timeout = QSpinBox()
        self.timeout.setRange(3, 60)
        self.timeout.setSuffix(" 秒")
        form.addRow("接続タイムアウト", self.timeout)

        self.enabled = None
        self.server_url = None
        if self.release_config.is_development:
            self.enabled = QCheckBox("オンラインライセンスを有効にする")
            self.server_url = QLineEdit()
            self.server_url.setPlaceholderText("https://license.example.com")
            form.addRow(self.enabled)
            form.addRow("ライセンスサーバーURL（開発者モード）", self.server_url)

        layout.addWidget(card)

        button_row = QHBoxLayout()
        save_button = QPushButton("設定を保存")
        save_button.setObjectName("AccentButton")
        save_button.clicked.connect(self.save_settings)
        verify_button = QPushButton("登録済みキーを確認")
        verify_button.clicked.connect(self.verify_registered_key)
        button_row.addWidget(save_button)
        button_row.addWidget(verify_button)
        button_row.addStretch()
        layout.addLayout(button_row)

        self.status = QLabel("")
        self.status.setObjectName("SectionTitle")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        note = QLabel(
            "配布版では認証サーバーの接続先を固定しています。"
            "URLの表示・変更はdevチャネルの開発者モードだけで有効です。"
        )
        note.setObjectName("MutedText")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch()
        self.load_settings()

    def load_settings(self):
        config = self.config_manager.load()
        self.timeout.setValue(int(config.get("timeout_seconds", 10)))
        if self.enabled is not None:
            self.enabled.setChecked(bool(config.get("enabled", True)))
        if self.server_url is not None:
            self.server_url.setText(str(config.get("server_url", "")))
        key = self.license_manager.load_online_key()
        self.status.setText(
            "登録済みキー：" + (self._mask_key(key) if key else "なし")
        )

    def save_settings(self):
        current = self.config_manager.load()
        current["timeout_seconds"] = self.timeout.value()
        if self.enabled is not None:
            current["enabled"] = self.enabled.isChecked()
        if self.server_url is not None:
            current["server_url"] = self.server_url.text().strip()
        self.config_manager.save(current)
        QMessageBox.information(self, "保存完了", "オンラインライセンス設定を保存しました。")

    def verify_registered_key(self):
        ok, message = self.license_manager.verify_online()
        self.status.setText(message)
        QMessageBox.information(
            self, "ライセンス確認" if ok else "ライセンス確認失敗", message
        )

    @staticmethod
    def _mask_key(key: str) -> str:
        if len(key) <= 8:
            return "****"
        return key[:4] + "-****-****-" + key[-4:]
