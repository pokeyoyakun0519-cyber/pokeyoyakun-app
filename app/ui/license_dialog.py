from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
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
from core.startup_diagnostics import StartupDiagnostics


class LicenseDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.manager = LicenseManager()
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
            "管理者から案内されたオンラインライセンスキーを入力してください。\n"
            "このPCコードとキーを認証サービスへ送信し、"
            "サーバーが返した判定結果だけで起動可否を決定します。"
        )
        explanation.setWordWrap(True)
        explanation.setObjectName("MutedText")
        layout.addWidget(explanation)

        device = QLabel(f"このPCコード：{get_device_id()}")
        device.setObjectName("SectionTitle")
        device.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(device)

        form = QFormLayout()
        self.online_key = QLineEdit()
        self.online_key.setPlaceholderText("例：PKY-XXXX-XXXX-XXXX-XXXX")
        self.online_key.setText(self.manager.load_online_key())
        form.addRow("オンラインキー", self.online_key)
        layout.addLayout(form)

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
        layout.addLayout(row)
        self.online_key.returnPressed.connect(self.authenticate_online)

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
