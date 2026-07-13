import os

from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from core.runtime_paths import app_root, install_root, is_frozen


class StoragePage(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("ContentPanel")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 26)
        layout.setSpacing(16)

        title = QLabel("データ保存場所")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        description = QLabel(
            "EXE版では設定やログをProgram Filesへ保存せず、"
            "Windowsのユーザー専用LocalAppDataへ保存します。\n"
            "これにより、管理者権限なしでも安全に設定を保存できます。"
        )
        description.setObjectName("MutedText")
        description.setWordWrap(True)
        layout.addWidget(description)

        data_card = QFrame()
        data_card.setObjectName("SettingsCard")
        data_layout = QVBoxLayout(data_card)

        data_title = QLabel("ユーザーデータ")
        data_title.setObjectName("SectionTitle")

        self.data_path = QLabel(str(app_root()))
        self.data_path.setWordWrap(True)
        self.data_path.setTextInteractionFlags(
            self.data_path.textInteractionFlags()
        )

        open_data_button = QPushButton(
            "ユーザーデータフォルダーを開く"
        )
        open_data_button.setObjectName("AccentButton")
        open_data_button.clicked.connect(self.open_data_folder)

        data_layout.addWidget(data_title)
        data_layout.addWidget(self.data_path)
        data_layout.addWidget(open_data_button)

        install_card = QFrame()
        install_card.setObjectName("SettingsCard")
        install_layout = QVBoxLayout(install_card)

        install_title = QLabel("アプリ本体")
        install_title.setObjectName("SectionTitle")

        install_path = QLabel(str(install_root()))
        install_path.setWordWrap(True)

        open_install_button = QPushButton(
            "アプリ本体のフォルダーを開く"
        )
        open_install_button.clicked.connect(
            self.open_install_folder
        )

        mode = QLabel(
            "実行モード："
            + ("EXE版" if is_frozen() else "Pythonソース版")
        )
        mode.setObjectName("MutedText")

        install_layout.addWidget(install_title)
        install_layout.addWidget(install_path)
        install_layout.addWidget(mode)
        install_layout.addWidget(open_install_button)

        layout.addWidget(data_card)
        layout.addWidget(install_card)
        layout.addStretch()

    def open_data_folder(self):
        path = app_root()
        path.mkdir(parents=True, exist_ok=True)

        try:
            os.startfile(path)
        except OSError as error:
            QMessageBox.critical(
                self,
                "フォルダーを開けません",
                str(error),
            )

    def open_install_folder(self):
        try:
            os.startfile(install_root())
        except OSError as error:
            QMessageBox.critical(
                self,
                "フォルダーを開けません",
                str(error),
            )
