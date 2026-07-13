from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from core.device_id import get_device_id
from core.license_manager import LicenseManager
from core.online_license_config import OnlineLicenseConfig
from core.startup_diagnostics import StartupDiagnostics


class LicenseDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.manager = LicenseManager()
        self.online_config = OnlineLicenseConfig()
        self.diagnostics = StartupDiagnostics()
        self.authenticated = False
        self._authenticating = False

        self.setWindowTitle("ポケヨヤ君 ライセンス認証")
        self.setFixedWidth(520)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(14)

        title = QLabel("ライセンス認証")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        explanation = QLabel(
            "オンラインライセンスキー、または従来の"
            "ID・パスワード・ライセンスファイルを使用できます。\n"
            "オンライン認証では、このPCコードが自動的に端末へ紐付けられます。"
        )
        explanation.setWordWrap(True)
        explanation.setObjectName("MutedText")
        layout.addWidget(explanation)

        device = QLabel(f"このPCコード：{get_device_id()}")
        device.setObjectName("SectionTitle")
        device.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(device)

        online_form = QFormLayout()
        config = self.online_config.load()

        self.server_url = QLineEdit()
        self.server_url.setPlaceholderText(
            "例：http://example.ddns.net:8765"
        )
        self.server_url.setText(
            str(config.get("server_url", ""))
        )
        online_form.addRow(
            "サーバーURL",
            self.server_url,
        )

        self.online_key = QLineEdit()
        self.online_key.setPlaceholderText(
            "例：PKY-XXXX-XXXX-XXXX-XXXX"
        )
        self.online_key.setText(
            self.manager.load_online_key()
        )
        online_form.addRow(
            "オンラインキー",
            self.online_key,
        )
        layout.addLayout(online_form)

        online_row = QHBoxLayout()
        self.connection_button = QPushButton(
            "接続テスト"
        )
        self.connection_button.clicked.connect(
            self.test_online_connection
        )
        self.online_button = QPushButton(
            "オンライン認証して起動"
        )
        self.online_button.setObjectName(
            "AccentButton"
        )
        self.online_button.clicked.connect(
            self.authenticate_online
        )
        online_row.addWidget(self.connection_button)
        online_row.addStretch()
        online_row.addWidget(
            self.online_button
        )
        layout.addLayout(online_row)

        separator = QLabel(
            "―― 従来ライセンス ――"
        )
        separator.setAlignment(Qt.AlignCenter)
        separator.setObjectName("MutedText")
        layout.addWidget(separator)

        form = QFormLayout()

        self.user_id = QLineEdit()
        self.user_id.setPlaceholderText("IDを入力")

        self.password = QLineEdit()
        self.password.setPlaceholderText("パスワードを入力")
        self.password.setEchoMode(QLineEdit.Password)

        form.addRow("ID", self.user_id)
        form.addRow("パスワード", self.password)
        layout.addLayout(form)

        button_row = QHBoxLayout()

        import_button = QPushButton("ライセンスファイルを登録")
        import_button.clicked.connect(self.import_license)

        self.login_button = QPushButton("認証して起動")
        self.login_button.setObjectName("AccentButton")
        self.login_button.setDefault(True)
        self.login_button.setAutoDefault(True)
        self.login_button.clicked.connect(self.authenticate)

        button_row.addWidget(import_button)
        button_row.addStretch()
        button_row.addWidget(self.login_button)
        layout.addLayout(button_row)

        self.user_id.returnPressed.connect(self.password.setFocus)
        self.password.returnPressed.connect(self.authenticate)

    def _save_online_settings(self) -> tuple[bool, str]:
        url = self.server_url.text().strip()
        valid, message = self.online_config.validate_server_url(url)
        if not valid:
            return False, message

        current = self.online_config.load()
        current.update(
            {
                "enabled": True,
                "server_url": url,
            }
        )
        try:
            self.online_config.save(current)
        except (OSError, ValueError) as error:
            return False, f"設定を保存できませんでした: {error}"
        return True, "設定を保存しました。"

    def test_online_connection(self):
        self.connection_button.setEnabled(False)
        try:
            ok, message = self._save_online_settings()
            if ok:
                ok, message = self.manager.online_client.test_connection(
                    self.server_url.text().strip()
                )
        finally:
            self.connection_button.setEnabled(True)

        QMessageBox.information(
            self,
            "接続テスト成功" if ok else "接続テスト失敗",
            message,
        )

    def authenticate_online(self):
        if self._authenticating:
            return

        self._authenticating = True
        self.online_button.setEnabled(False)
        self.connection_button.setEnabled(False)

        try:
            settings_ok, settings_message = self._save_online_settings()
            if not settings_ok:
                QMessageBox.warning(
                    self,
                    "オンライン認証失敗",
                    settings_message,
                )
                return

            key = self.online_key.text().strip()
            ok, message = (
                self.manager.activate_online(key)
            )

            if not ok:
                self.diagnostics.write(
                    f"オンライン認証失敗: {message}"
                )
                QMessageBox.warning(
                    self,
                    "オンライン認証失敗",
                    message,
                )
                return

            self.authenticated = True
            self.diagnostics.write(
                "オンラインライセンス認証成功"
            )
            self.accept()
        except Exception as error:
            self.diagnostics.write_exception(
                "オンラインライセンス認証で例外",
                error,
            )
            QMessageBox.critical(
                self,
                "オンライン認証エラー",
                str(error),
            )
        finally:
            self._authenticating = False
            if not self.authenticated:
                self.online_button.setEnabled(True)
                self.connection_button.setEnabled(True)

    def import_license(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "ライセンスファイルを選択",
            "",
            "ポケヨヤ君ライセンス (*.pkylicense *.json)",
        )

        if not path:
            return

        try:
            self.manager.import_license(path)
            self.diagnostics.write(
                f"ライセンスファイルを登録: {self.manager.license_path}"
            )
        except Exception as error:
            self.diagnostics.write(
                f"ライセンスファイル登録失敗: {error}"
            )
            QMessageBox.critical(
                self,
                "登録失敗",
                f"登録できませんでした。\n\n{error}",
            )
            return

        QMessageBox.information(
            self,
            "登録完了",
            "ライセンスファイルを登録しました。",
        )
        self.user_id.setFocus()

    def authenticate(self):
        if self._authenticating:
            return

        self._authenticating = True
        self.login_button.setEnabled(False)

        try:
            ok, message = self.manager.verify(
                self.user_id.text(),
                self.password.text(),
            )

            if not ok:
                self.diagnostics.write(f"認証失敗: {message}")
                QMessageBox.warning(
                    self,
                    "認証失敗",
                    message,
                )
                self.password.selectAll()
                self.password.setFocus()
                return

            self.authenticated = True
            self.diagnostics.write("ライセンス認証成功")
            self.accept()

        except Exception as error:
            self.diagnostics.write_exception(
                "ライセンス認証処理で例外",
                error,
            )
            QMessageBox.critical(
                self,
                "認証エラー",
                f"認証処理中にエラーが発生しました。\n\n{error}",
            )
        finally:
            self._authenticating = False
            if not self.authenticated:
                self.login_button.setEnabled(True)

    def reject(self):
        self.diagnostics.write("認証画面をキャンセル")
        super().reject()
