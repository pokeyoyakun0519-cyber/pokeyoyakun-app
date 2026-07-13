from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core.regression_checklist import RegressionChecklist


class RegressionPage(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("ContentPanel")
        self.manager = RegressionChecklist()
        self.checkboxes = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 26)
        layout.setSpacing(14)

        title = QLabel("回帰テスト")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        description = QLabel(
            "普段の更新では、インストール確認の代わりに"
            "主要機能だけを短時間で確認します。"
        )
        description.setObjectName("MutedText")
        description.setWordWrap(True)
        layout.addWidget(description)

        buttons = QHBoxLayout()

        save_button = QPushButton("チェック状態を保存")
        save_button.setObjectName("AccentButton")
        save_button.clicked.connect(self.save_state)

        complete_button = QPushButton("すべてチェック")
        complete_button.clicked.connect(self.check_all)

        reset_button = QPushButton("リセット")
        reset_button.clicked.connect(self.reset_state)

        buttons.addWidget(save_button)
        buttons.addWidget(complete_button)
        buttons.addWidget(reset_button)
        buttons.addStretch()
        layout.addLayout(buttons)

        self.summary = QLabel("")
        self.summary.setObjectName("SectionTitle")
        layout.addWidget(self.summary)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)

        container = QWidget()
        self.list_layout = QVBoxLayout(container)
        self.list_layout.setSpacing(10)
        self.scroll.setWidget(container)

        layout.addWidget(self.scroll, 1)
        self.load_state()

    def load_state(self):
        data = self.manager.load()

        while self.list_layout.count():
            item = self.list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        self.checkboxes = {}

        for item in data["items"]:
            checkbox = QCheckBox(item["label"])
            checkbox.setChecked(bool(item["checked"]))
            checkbox.stateChanged.connect(self.update_summary)
            self.checkboxes[item["id"]] = checkbox
            self.list_layout.addWidget(checkbox)

        self.list_layout.addStretch()
        self.update_summary()

    def save_state(self):
        items = [
            {
                "id": item_id,
                "label": checkbox.text(),
                "checked": checkbox.isChecked(),
            }
            for item_id, checkbox in self.checkboxes.items()
        ]
        self.manager.save(items)
        self.update_summary()

        QMessageBox.information(
            self,
            "保存完了",
            "回帰テストのチェック状態を保存しました。",
        )

    def check_all(self):
        for checkbox in self.checkboxes.values():
            checkbox.setChecked(True)
        self.update_summary()

    def reset_state(self):
        answer = QMessageBox.question(
            self,
            "リセット",
            "すべて未チェックに戻しますか？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if answer == QMessageBox.Yes:
            self.manager.reset()
            self.load_state()

    def update_summary(self):
        total = len(self.checkboxes)
        checked = sum(
            1
            for checkbox in self.checkboxes.values()
            if checkbox.isChecked()
        )
        self.summary.setText(
            f"確認済み：{checked}/{total}件"
        )
