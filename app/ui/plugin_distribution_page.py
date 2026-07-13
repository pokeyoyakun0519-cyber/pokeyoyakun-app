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
    QTextEdit,
    QVBoxLayout,
)

from core.online_plugin_manager import (
    OnlinePluginManager,
)
from core.plugin_distribution_config import (
    PluginDistributionConfig,
)


class PluginDistributionPage(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("ContentPanel")
        self.config_manager = (
            PluginDistributionConfig()
        )
        self.manager = OnlinePluginManager()
        self.available = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            28,
            26,
            28,
            26,
        )
        layout.setSpacing(14)

        title = QLabel(
            "オンラインプラグイン配信"
        )
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        description = QLabel(
            "店舗プラグインをサーバーから取得し、"
            "アプリ本体を更新せずに追加・更新します。"
            "ダウンロード後はSHA-256とJSON構造を検証します。"
        )
        description.setObjectName("MutedText")
        description.setWordWrap(True)
        layout.addWidget(description)

        card = QFrame()
        card.setObjectName("SettingsCard")
        form = QFormLayout(card)

        self.enabled = QCheckBox(
            "オンライン配信を有効にする"
        )
        self.startup = QCheckBox(
            "起動時に更新確認"
        )
        self.manifest_url = QLineEdit()
        self.timeout = QSpinBox()
        self.timeout.setRange(3, 60)
        self.timeout.setSuffix(" 秒")

        form.addRow(self.enabled)
        form.addRow(self.startup)
        form.addRow(
            "マニフェストURL",
            self.manifest_url,
        )
        form.addRow(
            "接続タイムアウト",
            self.timeout,
        )
        layout.addWidget(card)

        buttons = QHBoxLayout()

        save = QPushButton("設定を保存")
        save.clicked.connect(
            self.save_settings
        )

        check = QPushButton("更新を確認")
        check.setObjectName(
            "AccentButton"
        )
        check.clicked.connect(
            self.check_updates
        )

        self.install = QPushButton(
            "すべてインストール"
        )
        self.install.setEnabled(False)
        self.install.clicked.connect(
            self.install_updates
        )

        buttons.addWidget(save)
        buttons.addWidget(check)
        buttons.addWidget(self.install)
        buttons.addStretch()
        layout.addLayout(buttons)

        self.status = QLabel("")
        self.status.setObjectName("SectionTitle")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        self.details = QTextEdit()
        self.details.setReadOnly(True)
        self.details.setObjectName("LogView")
        layout.addWidget(self.details, 1)

        self.load_settings()

    def load_settings(self):
        config = self.config_manager.load()
        self.enabled.setChecked(
            bool(config.get("enabled", False))
        )
        self.startup.setChecked(
            bool(
                config.get(
                    "check_on_startup",
                    True,
                )
            )
        )
        self.manifest_url.setText(
            str(
                config.get(
                    "manifest_url",
                    "",
                )
            )
        )
        self.timeout.setValue(
            int(
                config.get(
                    "timeout_seconds",
                    15,
                )
            )
        )

    def save_settings(self):
        self.config_manager.save(
            {
                "enabled": self.enabled.isChecked(),
                "check_on_startup": (
                    self.startup.isChecked()
                ),
                "manifest_url": (
                    self.manifest_url
                    .text()
                    .strip()
                ),
                "timeout_seconds": (
                    self.timeout.value()
                ),
            }
        )
        QMessageBox.information(
            self,
            "保存完了",
            "プラグイン配信設定を保存しました。",
        )

    def check_updates(self):
        try:
            result = self.manager.check()
        except Exception as error:
            self.status.setText(
                "確認失敗"
            )
            self.details.setPlainText(
                str(error)
            )
            self.install.setEnabled(False)
            return

        self.available = list(
            result.get(
                "available",
                [],
            )
        )
        self.status.setText(
            str(
                result.get(
                    "message",
                    "",
                )
            )
        )
        self.install.setEnabled(
            bool(self.available)
        )
        self.details.setPlainText(
            "\n".join(
                f"{item.get('name', item.get('id', ''))} "
                f"Ver.{item.get('version', '')}"
                for item in self.available
            )
            or "更新対象はありません。"
        )

    def install_updates(self):
        results = self.manager.install_all(
            self.available
        )
        success = sum(
            1
            for item in results
            if item.get("ok")
        )
        failed = len(results) - success

        self.status.setText(
            f"インストール完了：成功{success}件 / 失敗{failed}件"
        )
        self.details.setPlainText(
            "\n".join(
                (
                    "OK: "
                    + str(item.get("name", ""))
                    if item.get("ok")
                    else "NG: "
                    + str(item.get("name", ""))
                    + " / "
                    + str(item.get("error", ""))
                )
                for item in results
            )
        )
        self.install.setEnabled(False)

        QMessageBox.information(
            self,
            "プラグイン配信",
            self.status.text()
            + "\nプラグイン管理で再スキャンすると反映されます。",
        )
