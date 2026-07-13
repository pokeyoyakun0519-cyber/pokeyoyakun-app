from pathlib import Path

from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from core.support_bundle import SupportBundle


class SupportPage(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("ContentPanel")
        self.bundle = SupportBundle()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 26)
        layout.setSpacing(16)

        title = QLabel("サポート")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        description = QLabel(
            "不具合調査に必要な情報を、"
            "1つの診断ZIPへまとめます。\n"
            "ライセンス、パスワード、Discord Webhook、"
            "SMTPパスワードは含めません。"
        )
        description.setObjectName("MutedText")
        description.setWordWrap(True)
        layout.addWidget(description)

        card = QFrame()
        card.setObjectName("SettingsCard")
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(10)

        contents = QLabel(
            "診断ZIPに含まれるもの\n"
            "・アプリとWindowsのバージョン\n"
            "・セルフテスト結果\n"
            "・最新ログ（最大20件）\n"
            "・機密情報を除いた一部設定\n"
            "・README"
        )
        contents.setWordWrap(True)

        create_button = QPushButton("サポート診断ZIPを作成")
        create_button.setObjectName("AccentButton")
        create_button.clicked.connect(self.create_bundle)

        card_layout.addWidget(contents)
        card_layout.addWidget(create_button)
        layout.addWidget(card)

        warning = QLabel(
            "作成後は、送信前にZIPの内容を確認してください。"
        )
        warning.setObjectName("MutedText")
        warning.setWordWrap(True)
        layout.addWidget(warning)
        layout.addStretch()

    def create_bundle(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            "サポート診断ZIPを保存",
            "PokeyoyaKun_SupportBundle.zip",
            "ZIPファイル (*.zip)",
        )

        if not path:
            return

        if not path.lower().endswith(".zip"):
            path += ".zip"

        try:
            result = self.bundle.create(Path(path))
        except Exception as error:
            QMessageBox.critical(
                self,
                "作成失敗",
                str(error),
            )
            return

        QMessageBox.information(
            self,
            "作成完了",
            f"サポート診断ZIPを作成しました。\n\n{result}",
        )
