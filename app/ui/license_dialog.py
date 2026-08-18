from PySide6.QtCore import QRegularExpression, Qt, QTimer
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QWidget,
    QVBoxLayout,
)

from core.device_id import get_device_id
from core.license_manager import LicenseManager
from core.startup_diagnostics import StartupDiagnostics


class LicenseDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.manager = LicenseManager()
        self.diagnostics = StartupDiagnostics()
        self.authenticated = False
        self._authenticating = False
        self._resend_seconds = 0

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
            "購入時のメールアドレスへ6桁の認証コードを送信します。\n"
            "コード確認後に契約状態と端末数をサーバーで確認し、自動認証します。"
        )
        explanation.setWordWrap(True)
        explanation.setObjectName("MutedText")
        layout.addWidget(explanation)

        device = QLabel(f"このPCコード：{get_device_id()}")
        device.setObjectName("SectionTitle")
        device.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(device)

        form = QFormLayout()
        self.subscription_email = QLineEdit()
        self.subscription_email.setPlaceholderText("購入時のメールアドレス")
        form.addRow("メールアドレス", self.subscription_email)

        code_row = QHBoxLayout()
        self.subscription_code = QLineEdit()
        self.subscription_code.setPlaceholderText("6桁の認証コード")
        self.subscription_code.setMaxLength(6)
        self.subscription_code.setValidator(
            QRegularExpressionValidator(QRegularExpression(r"\d{0,6}"), self)
        )
        self.send_code_button = QPushButton("コードを送信")
        self.send_code_button.clicked.connect(self.send_subscription_code)
        code_row.addWidget(self.subscription_code)
        code_row.addWidget(self.send_code_button)
        form.addRow("認証コード", code_row)
        layout.addLayout(form)

        self.subscription_status = QLabel("コードの有効期限は10分です。再送は60秒後にできます。")
        self.subscription_status.setWordWrap(True)
        self.subscription_status.setObjectName("MutedText")
        layout.addWidget(self.subscription_status)

        self.subscription_button = QPushButton("契約を確認して起動")
        self.subscription_button.setObjectName("AccentButton")
        self.subscription_button.setDefault(True)
        self.subscription_button.clicked.connect(self.authenticate_subscription)
        layout.addWidget(self.subscription_button)
        self.subscription_code.returnPressed.connect(self.authenticate_subscription)

        self.legacy_toggle = QPushButton("既存のライセンスキーを使用")
        self.legacy_toggle.setCheckable(True)
        self.legacy_toggle.clicked.connect(self._toggle_legacy)
        layout.addWidget(self.legacy_toggle)

        self.legacy_panel = QWidget()
        legacy_layout = QVBoxLayout(self.legacy_panel)
        legacy_layout.setContentsMargins(0, 0, 0, 0)
        legacy_form = QFormLayout()
        self.online_key = QLineEdit()
        self.online_key.setPlaceholderText("例：PKY-XXXX-XXXX-XXXX-XXXX")
        self.online_key.setText(self.manager.load_online_key())
        self.online_key.setEchoMode(QLineEdit.Password)
        legacy_form.addRow("オンラインキー", self.online_key)
        legacy_layout.addLayout(legacy_form)

        row = QHBoxLayout()
        self.connection_button = QPushButton("接続テスト")
        self.connection_button.clicked.connect(self.test_online_connection)
        self.online_button = QPushButton("オンライン認証して起動")
        self.online_button.setObjectName("AccentButton")
        self.online_button.setDefault(True)
        self.online_button.clicked.connect(self.authenticate_online)
        row.addWidget(self.connection_button)
        row.addStretch()
        row.addWidget(self.online_button)
        legacy_layout.addLayout(row)
        self.legacy_panel.setVisible(False)
        layout.addWidget(self.legacy_panel)
        self.online_key.returnPressed.connect(self.authenticate_online)

        self.resend_timer = QTimer(self)
        self.resend_timer.setInterval(1000)
        self.resend_timer.timeout.connect(self._update_resend_cooldown)

    def _toggle_legacy(self, checked: bool) -> None:
        self.legacy_panel.setVisible(checked)
        self.legacy_toggle.setText(
            "既存キー入力を閉じる" if checked else "既存のライセンスキーを使用"
        )

    def send_subscription_code(self):
        if self._authenticating or self._resend_seconds > 0:
            return
        self._authenticating = True
        self.send_code_button.setEnabled(False)
        try:
            ok, message = self.manager.request_subscription_code(
                self.subscription_email.text()
            )
            self.subscription_status.setText(message)
            if not ok:
                QMessageBox.warning(self, "コード送信失敗", message)
                return
            self._resend_seconds = 60
            self.resend_timer.start()
            self.subscription_code.setFocus()
        except Exception as error:
            self.diagnostics.write(
                "認証コード送信で例外: " + type(error).__name__
            )
            QMessageBox.critical(
                self,
                "コード送信エラー",
                "認証コードを送信できませんでした。時間をおいて再度お試しください。",
            )
        finally:
            self._authenticating = False
            if self._resend_seconds == 0:
                self.send_code_button.setEnabled(True)

    def _update_resend_cooldown(self) -> None:
        self._resend_seconds = max(0, self._resend_seconds - 1)
        if self._resend_seconds:
            self.send_code_button.setText(f"再送まで {self._resend_seconds}秒")
            return
        self.resend_timer.stop()
        self.send_code_button.setText("コードを再送")
        self.send_code_button.setEnabled(True)

    def authenticate_subscription(self):
        if self._authenticating:
            return
        self._authenticating = True
        self.subscription_button.setEnabled(False)
        self.send_code_button.setEnabled(False)
        try:
            ok, message = self.manager.activate_subscription(
                self.subscription_email.text(),
                self.subscription_code.text(),
            )
            if not ok:
                self.diagnostics.write("サブスクリプション自動認証失敗")
                QMessageBox.warning(self, "自動認証失敗", message)
                return
            self.authenticated = True
            self.subscription_code.clear()
            self.diagnostics.write("サブスクリプション自動認証成功")
            self.accept()
        except Exception as error:
            self.diagnostics.write(
                "サブスクリプション自動認証で例外: " + type(error).__name__
            )
            QMessageBox.critical(
                self,
                "自動認証エラー",
                "自動認証を完了できませんでした。時間をおいて再度お試しください。",
            )
        finally:
            self._authenticating = False
            if not self.authenticated:
                self.subscription_button.setEnabled(True)
                if self._resend_seconds == 0:
                    self.send_code_button.setEnabled(True)

    def test_online_connection(self):
        self.connection_button.setEnabled(False)
        try:
            ok, message = self.manager.online_client.test_connection()
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
            ok, message = self.manager.activate_online(
                self.online_key.text().strip()
            )
            if not ok:
                self.diagnostics.write(f"オンライン認証失敗: {message}")
                QMessageBox.warning(self, "オンライン認証失敗", message)
                return

            self.authenticated = True
            self.diagnostics.write("オンラインライセンス認証成功")
            self.accept()
        except Exception as error:
            self.diagnostics.write_exception(
                "オンラインライセンス認証で例外", error
            )
            QMessageBox.critical(self, "オンライン認証エラー", str(error))
        finally:
            self._authenticating = False
            if not self.authenticated:
                self.online_button.setEnabled(True)
                self.connection_button.setEnabled(True)

    def reject(self):
        self.diagnostics.write("認証画面をキャンセル")
        super().reject()
