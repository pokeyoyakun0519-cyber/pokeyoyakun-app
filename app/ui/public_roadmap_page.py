from __future__ import annotations

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from core.public_roadmap import (
    STATUS_LABELS,
    TCG_LABELS,
    PublicRoadmapClient,
    PublicRoadmapError,
    PublicRoadmapValidationError,
)


class PublicRoadmapPage(QFrame):
    def __init__(self, client=None):
        super().__init__()
        self.setObjectName("ContentPanel")
        self.client = client or PublicRoadmapClient()
        self._loading = False
        self._initial_load_started = False
        self._items: list[dict] = []
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 26)
        layout.setSpacing(14)

        title = QLabel("人気要望・開発状況")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        description = QLabel(
            "多く寄せられた要望と開発状況を公開しています。"
            "投稿者情報や管理用の情報は表示されません。"
        )
        description.setObjectName("MutedText")
        description.setWordWrap(True)
        layout.addWidget(description)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("対象TCG"))
        self.tcg_filter = QComboBox()
        self.tcg_filter.addItem("すべて", "")
        for key, label in TCG_LABELS.items():
            self.tcg_filter.addItem(label, key)
        filter_row.addWidget(self.tcg_filter)
        filter_row.addSpacing(12)
        filter_row.addWidget(QLabel("状態"))
        self.status_filter = QComboBox()
        self.status_filter.addItem("すべて", "")
        for key, label in STATUS_LABELS.items():
            self.status_filter.addItem(label, key)
        filter_row.addWidget(self.status_filter)
        filter_row.addStretch()
        self.reload_button = QPushButton("再読込")
        self.reload_button.setObjectName("AccentButton")
        filter_row.addWidget(self.reload_button)
        layout.addLayout(filter_row)

        self.notice = QLabel("表示時に公開情報を読み込みます。")
        self.notice.setObjectName("MutedText")
        self.notice.setWordWrap(True)
        layout.addWidget(self.notice)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["タイトル", "要約", "対象TCG", "要望件数", "状態", "更新日時"]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        for column in range(2, 6):
            header.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        layout.addWidget(self.table, 1)

        action_row = QHBoxLayout()
        action_row.addStretch()
        self.detail_button = QPushButton("選択した要望の詳細")
        self.detail_button.setEnabled(False)
        action_row.addWidget(self.detail_button)
        layout.addLayout(action_row)

        self.reload_button.clicked.connect(lambda: self.reload_data(force=True))
        self.tcg_filter.currentIndexChanged.connect(
            lambda: self.reload_data(force=False)
        )
        self.status_filter.currentIndexChanged.connect(
            lambda: self.reload_data(force=False)
        )
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.table.itemDoubleClicked.connect(lambda _item: self.show_selected_detail())
        self.detail_button.clicked.connect(self.show_selected_detail)

    def showEvent(self, event):
        super().showEvent(event)
        if not self._initial_load_started:
            self._initial_load_started = True
            QTimer.singleShot(0, lambda: self.reload_data(force=False))

    def reload_data(self, *, force: bool):
        if self._loading:
            return
        self._set_loading(True)
        try:
            result = self.client.list_roadmap(
                str(self.tcg_filter.currentData()),
                str(self.status_filter.currentData()),
                force=force,
            )
            self._items = list(result.payload.get("items", []))
            self._render_items()
            if not self._items:
                self.notice.setText(
                    "該当する人気要望はありません。条件を変更するか再読込してください。"
                )
            elif result.offline:
                self.notice.setText(
                    "オフラインのため、直近に取得したキャッシュを表示しています。"
                )
            elif result.from_cache:
                self.notice.setText("5分以内に取得したキャッシュを表示しています。")
            else:
                self.notice.setText("公開APIから最新情報を取得しました。")
        except (PublicRoadmapError, PublicRoadmapValidationError) as error:
            self.notice.setText(
                f"読み込めませんでした: {error} 画面の内容は保持されています。"
                "「再読込」で再試行できます。"
            )
        finally:
            self._set_loading(False)

    def _render_items(self):
        self.table.setRowCount(len(self._items))
        for row, item in enumerate(self._items):
            tcg_text = "、".join(
                TCG_LABELS[key] for key in item["tcg_keys"] if key in TCG_LABELS
            ) or "すべて"
            values = (
                item["title"],
                item["summary"],
                tcg_text,
                f'{item["message_count"]:,}',
                STATUS_LABELS.get(item["status"], item["status"]),
                self._format_datetime(item["updated_at"]),
            )
            for column, value in enumerate(values):
                cell = QTableWidgetItem(str(value))
                if column == 3:
                    cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(row, column, cell)
        self.table.clearSelection()
        self.detail_button.setEnabled(False)

    def _selection_changed(self):
        self.detail_button.setEnabled(
            not self._loading and 0 <= self.table.currentRow() < len(self._items)
        )

    def _set_loading(self, value: bool):
        self._loading = value
        self.reload_button.setEnabled(not value)
        self.reload_button.setText("読込中…" if value else "再読込")
        self.tcg_filter.setEnabled(not value)
        self.status_filter.setEnabled(not value)
        self._selection_changed()

    def show_selected_detail(self):
        row = self.table.currentRow()
        if self._loading or row < 0 or row >= len(self._items):
            return
        selected = self._items[row]
        item = selected
        offline = False
        try:
            result = self.client.roadmap_detail(selected["cluster_id"])
            item = result.payload
            offline = result.offline
        except (PublicRoadmapError, PublicRoadmapValidationError) as error:
            QMessageBox.warning(
                self,
                "詳細の再取得に失敗しました",
                f"{error}\n\n一覧で取得済みの公開情報を表示します。",
            )
        self._show_detail_dialog(item, offline)

    def _show_detail_dialog(self, item: dict, offline: bool):
        dialog = QDialog(self)
        dialog.setWindowTitle("人気要望・開発状況の詳細")
        dialog.setMinimumWidth(600)
        layout = QVBoxLayout(dialog)
        if offline:
            note = QLabel("オフラインのため、直近のキャッシュを表示しています。")
            note.setObjectName("MutedText")
            layout.addWidget(note)
        form = QFormLayout()
        values = (
            ("タイトル", item["title"]),
            ("要約", item["summary"]),
            (
                "対象TCG",
                "、".join(TCG_LABELS[key] for key in item["tcg_keys"])
                or "すべて",
            ),
            ("要望件数", f'{item["message_count"]:,}'),
            ("状態", STATUS_LABELS[item["status"]]),
            ("更新日時", self._format_datetime(item["updated_at"])),
        )
        for label, value in values:
            text = QLabel(str(value))
            text.setWordWrap(True)
            text.setTextInteractionFlags(Qt.TextSelectableByMouse)
            form.addRow(label, text)
        layout.addLayout(form)
        close_button = QPushButton("閉じる")
        close_button.clicked.connect(dialog.accept)
        layout.addWidget(close_button, 0, Qt.AlignRight)
        dialog.exec()

    @staticmethod
    def _format_datetime(value: str) -> str:
        return str(value).replace("T", " ").replace("Z", " UTC")
