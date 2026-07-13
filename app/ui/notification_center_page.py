from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core.notification_store import NotificationStore


class NotificationCenterPage(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("ContentPanel")
        self.store = NotificationStore()
        self.all_items = []
        self.filtered_items = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 26)
        layout.setSpacing(14)

        header = QHBoxLayout()

        title = QLabel("通知センター")
        title.setObjectName("PageTitle")

        refresh_button = QPushButton("再読込")
        refresh_button.clicked.connect(self.reload_items)

        read_button = QPushButton("表示中を既読")
        read_button.clicked.connect(self.mark_filtered_read)

        export_button = QPushButton("CSV出力")
        export_button.clicked.connect(self.export_csv)

        clear_button = QPushButton("通知をすべて削除")
        clear_button.setObjectName("DangerButton")
        clear_button.clicked.connect(self.clear_items)

        header.addWidget(title)
        header.addStretch()
        header.addWidget(refresh_button)
        header.addWidget(read_button)
        header.addWidget(export_button)
        header.addWidget(clear_button)
        layout.addLayout(header)

        filters = QHBoxLayout()

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(
            "タイトル・メッセージを検索"
        )
        self.search_input.textChanged.connect(self.apply_filters)

        self.category_combo = QComboBox()
        self.category_combo.addItem("すべてのカテゴリ")
        self.category_combo.currentTextChanged.connect(
            self.apply_filters
        )

        self.read_combo = QComboBox()
        self.read_combo.addItems(
            [
                "すべて",
                "未読のみ",
                "既読のみ",
            ]
        )
        self.read_combo.currentTextChanged.connect(
            self.apply_filters
        )

        self.date_enabled = QComboBox()
        self.date_enabled.addItems(
            [
                "全期間",
                "指定日",
            ]
        )
        self.date_enabled.currentTextChanged.connect(
            self.apply_filters
        )

        self.date_edit = QDateEdit(QDate.currentDate())
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy/MM/dd")
        self.date_edit.dateChanged.connect(self.apply_filters)

        filters.addWidget(self.search_input, 1)
        filters.addWidget(self.category_combo)
        filters.addWidget(self.read_combo)
        filters.addWidget(self.date_enabled)
        filters.addWidget(self.date_edit)
        layout.addLayout(filters)

        self.summary = QLabel("")
        self.summary.setObjectName("MutedText")
        layout.addWidget(self.summary)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        layout.addWidget(self.scroll, 1)

        self.reload_items()

    def reload_items(self):
        self.all_items = self.store.load()

        current_category = self.category_combo.currentText()
        categories = sorted(
            {
                str(item.get("category", "情報"))
                for item in self.all_items
            }
        )

        self.category_combo.blockSignals(True)
        self.category_combo.clear()
        self.category_combo.addItem("すべてのカテゴリ")
        for category in categories:
            self.category_combo.addItem(category)

        index = self.category_combo.findText(current_category)
        if index >= 0:
            self.category_combo.setCurrentIndex(index)
        self.category_combo.blockSignals(False)

        self.apply_filters()

    def apply_filters(self):
        keyword = self.search_input.text().strip().lower()
        category = self.category_combo.currentText()
        read_mode = self.read_combo.currentText()
        use_date = self.date_enabled.currentText() == "指定日"
        target_date = self.date_edit.date().toString("yyyy/MM/dd")

        filtered = []

        for source_index, item in enumerate(self.all_items):
            title = str(item.get("title", ""))
            message = str(item.get("message", ""))
            item_category = str(item.get("category", "情報"))
            created_at = str(item.get("created_at", ""))
            is_read = bool(item.get("read", False))

            if keyword and keyword not in (
                title + "\n" + message
            ).lower():
                continue

            if (
                category != "すべてのカテゴリ"
                and item_category != category
            ):
                continue

            if read_mode == "未読のみ" and is_read:
                continue

            if read_mode == "既読のみ" and not is_read:
                continue

            if use_date and not created_at.startswith(target_date):
                continue

            filtered.append((source_index, item))

        self.filtered_items = filtered
        self.render_items()

    def render_items(self):
        unread = sum(
            1
            for _, item in self.filtered_items
            if not item.get("read", False)
        )

        self.summary.setText(
            f"表示：{len(self.filtered_items)}件　"
            f"未読：{unread}件　"
            f"全通知：{len(self.all_items)}件"
        )

        container = QWidget()
        list_layout = QVBoxLayout(container)
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.setSpacing(10)

        if not self.filtered_items:
            empty = QLabel("条件に一致する通知はありません。")
            empty.setAlignment(Qt.AlignCenter)
            empty.setObjectName("PageText")
            list_layout.addWidget(empty)
        else:
            for _, item in self.filtered_items:
                card = QFrame()
                card.setObjectName("ProductCard")

                card_layout = QVBoxLayout(card)
                card_layout.setContentsMargins(16, 14, 16, 14)
                card_layout.setSpacing(6)

                title = QLabel(
                    ("● " if not item.get("read", False) else "")
                    + item.get("title", "タイトルなし")
                )
                title.setObjectName("ProductName")

                meta = QLabel(
                    f'{item.get("category", "情報")}  ｜  '
                    f'{item.get("created_at", "")}'
                )
                meta.setObjectName("MutedText")

                message = QLabel(item.get("message", ""))
                message.setWordWrap(True)

                card_layout.addWidget(title)
                card_layout.addWidget(meta)
                card_layout.addWidget(message)
                list_layout.addWidget(card)

        list_layout.addStretch()
        self.scroll.setWidget(container)

    def mark_filtered_read(self):
        indexes = [
            source_index
            for source_index, _ in self.filtered_items
        ]
        self.store.mark_filtered_read(indexes)
        self.reload_items()

    def export_csv(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            "通知をCSVへ書き出す",
            "PokeyoyaKun_notifications.csv",
            "CSVファイル (*.csv)",
        )

        if not path:
            return

        if not path.lower().endswith(".csv"):
            path += ".csv"

        try:
            self.store.export_csv(
                Path(path),
                [
                    item
                    for _, item in self.filtered_items
                ],
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
            "表示中の通知をCSVへ書き出しました。",
        )

    def clear_items(self):
        answer = QMessageBox.question(
            self,
            "通知削除",
            "保存されている通知をすべて削除しますか？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if answer == QMessageBox.Yes:
            self.store.clear()
            self.reload_items()
