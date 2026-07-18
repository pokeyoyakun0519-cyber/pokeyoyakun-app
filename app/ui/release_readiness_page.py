from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from core.release_readiness import ReleaseReadiness
from ui.design_system import busy_button


class ReleaseReadinessPage(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("ContentPanel")
        self.manager = ReleaseReadiness()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 26)
        layout.setSpacing(14)

        title = QLabel("リリース準備状況")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        description = QLabel(
            "正式版へ進む前に、主要な設定と保存先をまとめて確認します。"
        )
        description.setObjectName("MutedText")
        description.setWordWrap(True)
        layout.addWidget(description)

        self.run_button = QPushButton("準備状況を確認")
        self.run_button.setObjectName("AccentButton")
        self.run_button.clicked.connect(self.run_check)
        layout.addWidget(self.run_button)

        self.summary = QLabel("まだ確認していません。")
        self.summary.setObjectName("SectionTitle")
        layout.addWidget(self.summary)

        self.list_widget = QListWidget()
        layout.addWidget(self.list_widget, 1)

    def run_check(self):
        with busy_button(self.run_button, "確認中…"):
            results = self.manager.run()
        self.list_widget.clear()

        required_success = 0
        required_total = 0

        for result in results:
            warning_only = bool(result.get("warning_only", False))
            success = bool(result.get("success", False))

            if not warning_only:
                required_total += 1
                if success:
                    required_success += 1

            if success:
                mark = "✅"
            elif warning_only:
                mark = "⚠️"
            else:
                mark = "❌"

            item = QListWidgetItem(
                f"{mark} {result.get('name', '項目')}\n"
                f"{result.get('message', '')}"
            )
            self.list_widget.addItem(item)

        if required_success == required_total:
            self.summary.setText(
                f"必須項目：{required_success}/{required_total}件 OK"
            )
        else:
            self.summary.setText(
                f"必須項目：{required_success}/{required_total}件 OK"
            )
        self.summary.setProperty(
            "state", "success" if required_success == required_total else "error"
        )
