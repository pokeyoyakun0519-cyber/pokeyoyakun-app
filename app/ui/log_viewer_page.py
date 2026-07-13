import os
from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QVBoxLayout,
)

from core.runtime_paths import app_root


class LogViewerPage(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("ContentPanel")
        self.logs_dir = app_root() / "logs"
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.lines = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 26)
        layout.setSpacing(14)

        title = QLabel("ログビューア")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        controls = QHBoxLayout()

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("ログ内を検索")
        self.search_input.textChanged.connect(self.apply_filter)

        self.level_combo = QComboBox()
        self.level_combo.addItems(
            [
                "すべて",
                "ERROR",
                "WARNING",
                "INFO",
            ]
        )
        self.level_combo.currentTextChanged.connect(self.apply_filter)

        self.file_combo = QComboBox()
        self.file_combo.currentTextChanged.connect(self.reload_selected_file)

        reload_button = QPushButton("再読込")
        reload_button.clicked.connect(self.reload_logs)

        export_button = QPushButton("表示中をエクスポート")
        export_button.clicked.connect(self.export_logs)

        open_button = QPushButton("logsフォルダーを開く")
        open_button.clicked.connect(self.open_logs_folder)

        controls.addWidget(self.search_input, 1)
        controls.addWidget(self.level_combo)
        controls.addWidget(self.file_combo)
        controls.addWidget(reload_button)
        controls.addWidget(export_button)
        controls.addWidget(open_button)
        layout.addLayout(controls)

        self.status = QLabel("")
        self.status.setObjectName("MutedText")
        layout.addWidget(self.status)

        self.viewer = QPlainTextEdit()
        self.viewer.setReadOnly(True)
        self.viewer.setObjectName("LogView")
        layout.addWidget(self.viewer, 1)

        self.reload_logs()

    def reload_logs(self):
        files = sorted(
            self.logs_dir.glob("*.log"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )

        current = self.file_combo.currentText()

        self.file_combo.blockSignals(True)
        self.file_combo.clear()
        self.file_combo.addItem("すべてのログ")
        for path in files:
            self.file_combo.addItem(path.name)

        index = self.file_combo.findText(current)
        if index >= 0:
            self.file_combo.setCurrentIndex(index)
        self.file_combo.blockSignals(False)

        self.reload_selected_file()

    def reload_selected_file(self):
        selected = self.file_combo.currentText()
        files = sorted(
            self.logs_dir.glob("*.log"),
            key=lambda path: path.stat().st_mtime,
        )

        if selected and selected != "すべてのログ":
            files = [
                path
                for path in files
                if path.name == selected
            ]

        lines = []

        for path in files:
            try:
                content = path.read_text(
                    encoding="utf-8",
                    errors="replace",
                )
            except OSError:
                continue

            lines.append(
                {
                    "text": f"===== {path.name} =====",
                    "file": path.name,
                }
            )

            for line in content.splitlines():
                lines.append(
                    {
                        "text": line,
                        "file": path.name,
                    }
                )

        self.lines = lines
        self.status.setText(
            f"対象ログファイル：{len(files)}件"
        )
        self.apply_filter()

    def apply_filter(self):
        keyword = self.search_input.text().strip().lower()
        level = self.level_combo.currentText()

        output = []

        for row in self.lines:
            text = row["text"]

            if keyword and keyword not in text.lower():
                continue

            if level != "すべて":
                upper = text.upper()

                if level == "ERROR":
                    if "ERROR" not in upper and "TRACEBACK" not in upper:
                        continue
                elif level == "WARNING":
                    if "WARNING" not in upper and "WARN" not in upper:
                        continue
                elif level == "INFO":
                    if (
                        "INFO" not in upper
                        and "ERROR" in upper
                    ):
                        continue

            output.append(text)

        self.viewer.setPlainText("\n".join(output))
        self.status.setText(
            self.status.text().split("　表示行")[0]
            + f"　表示行：{len(output)}"
        )

    def export_logs(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            "表示中のログを書き出す",
            "PokeyoyaKun_filtered_logs.txt",
            "テキストファイル (*.txt)",
        )

        if not path:
            return

        try:
            Path(path).write_text(
                self.viewer.toPlainText(),
                encoding="utf-8",
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
            "表示中のログを書き出しました。",
        )

    def open_logs_folder(self):
        os.startfile(self.logs_dir)
