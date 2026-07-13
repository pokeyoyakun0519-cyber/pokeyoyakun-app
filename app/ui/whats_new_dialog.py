from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from core.version import APP_VERSION
from core.whats_new_manager import WhatsNewManager


class WhatsNewDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.manager = WhatsNewManager()

        self.setWindowTitle("ポケヨヤ君 - 更新内容")
        self.resize(620, 480)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(14)

        title = QLabel(f"ポケヨヤ君 Ver.{APP_VERSION}")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        body = QTextEdit()
        body.setReadOnly(True)
        body.setPlainText(
            "正式版 Ver.1.0.0\n\n"
            "・Windowsインストーラー対応\n"
            "・デスクトップショートカット選択\n"
            "・ライセンス認証\n"
            "・自動監視\n"
            "・タスクトレイ常駐\n"
            "・Windows自動起動\n"
            "・Discord / メール通知\n"
            "・自動アップデートとロールバック\n"
            "・セルフテスト\n"
            "・回帰テスト\n"
            "・サポート診断ZIP\n"
            "・バックアップ世代管理\n"
            "・通知センター / ログビューア強化\n\n"
            "ご利用ありがとうございます。"
        )
        layout.addWidget(body, 1)

        close_button = QPushButton("確認して閉じる")
        close_button.setObjectName("AccentButton")
        close_button.clicked.connect(self.accept)
        layout.addWidget(close_button)

    def accept(self):
        self.manager.mark_seen()
        super().accept()
