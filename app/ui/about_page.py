import os

from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from core.runtime_paths import app_root, install_root
from core.version import APP_CHANNEL, APP_VERSION


class AboutPage(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("ContentPanel")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 26)
        layout.setSpacing(14)

        title = QLabel("アプリ情報")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        info = QLabel(
            f"ポケヨヤ君\n"
            f"バージョン：{APP_VERSION}\n"
            f"チャンネル：{APP_CHANNEL.upper()}\n\n"
            f"インストール先：\n{install_root()}\n\n"
            f"設定・データ保存先：\n{app_root()}"
        )
        info.setObjectName("PageText")
        info.setWordWrap(True)
        layout.addWidget(info)

        open_install = QPushButton("インストール先を開く")
        open_install.clicked.connect(
            lambda: os.startfile(install_root())
        )

        open_data = QPushButton("設定・データ保存先を開く")
        open_data.clicked.connect(
            lambda: os.startfile(app_root())
        )

        open_logs = QPushButton("ログフォルダーを開く")
        open_logs.clicked.connect(
            lambda: os.startfile(app_root() / "logs")
        )

        layout.addWidget(open_install)
        layout.addWidget(open_data)
        layout.addWidget(open_logs)
        layout.addStretch()
