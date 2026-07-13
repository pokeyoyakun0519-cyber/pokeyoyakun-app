from pathlib import Path

from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from core.self_test_manager import SelfTestManager


class SelfTestPage(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("ContentPanel")

        self.manager = SelfTestManager()
        self.results = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 26)
        layout.setSpacing(14)

        title = QLabel("セルフテスト")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        description = QLabel(
            "起動に必要なファイル、設定JSON、"
            "保存先、書き込み権限をまとめて確認します。"
        )
        description.setObjectName("MutedText")
        description.setWordWrap(True)
        layout.addWidget(description)

        buttons = QHBoxLayout()

        run_button = QPushButton("テストを実行")
        run_button.setObjectName("AccentButton")
        run_button.clicked.connect(self.run_tests)

        export_button = QPushButton("結果を書き出す")
        export_button.clicked.connect(self.export_results)

        buttons.addWidget(run_button)
        buttons.addWidget(export_button)
        buttons.addStretch()
        layout.addLayout(buttons)

        self.summary = QLabel("まだ実行していません。")
        self.summary.setObjectName("SectionTitle")
        layout.addWidget(self.summary)

        self.list_widget = QListWidget()
        layout.addWidget(self.list_widget, 1)

    def run_tests(self):
        self.results = self.manager.run_all()
        self.list_widget.clear()

        success_count = 0

        for result in self.results:
            success = bool(result.get("success"))
            if success:
                success_count += 1

            mark = "✅" if success else "❌"
            name = result.get("name", "項目")
            message = result.get("message", "")

            item = QListWidgetItem(
                f"{mark} {name}\n{message}"
            )
            self.list_widget.addItem(item)

        total = len(self.results)
        self.summary.setText(
            f"結果：{success_count}/{total}件 成功"
        )

        if success_count == total:
            QMessageBox.information(
                self,
                "セルフテスト完了",
                "すべての項目が正常でした。",
            )

    def export_results(self):
        if not self.results:
            QMessageBox.information(
                self,
                "未実行",
                "先にセルフテストを実行してください。",
            )
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            "セルフテスト結果を保存",
            "PokeyoyaKun_SelfTest.json",
            "JSONファイル (*.json)",
        )

        if not path:
            return

        if not path.lower().endswith(".json"):
            path += ".json"

        try:
            result_path = self.manager.export_report(
                Path(path),
                self.results,
            )
        except OSError as error:
            QMessageBox.critical(
                self,
                "保存失敗",
                str(error),
            )
            return

        QMessageBox.information(
            self,
            "保存完了",
            f"結果を書き出しました。\n\n{result_path}",
        )
