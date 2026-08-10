from __future__ import annotations

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal, Slot
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
)

from core.global_search import GROUP_LABELS, GROUP_ORDER, GlobalSearchService


class SearchTaskSignals(QObject):
    completed = Signal(int, object)
    failed = Signal(int, str)


class SearchTask(QRunnable):
    def __init__(self, request_id, service, query, mode):
        super().__init__()
        self.request_id = request_id
        self.service = service
        self.query = query
        self.mode = mode
        self.signals = SearchTaskSignals()

    @Slot()
    def run(self):
        try:
            result = self.service.search(self.query, mode=self.mode)
        except Exception as error:
            self.signals.failed.emit(
                self.request_id, f"{type(error).__name__}: {error}"
            )
            return
        self.signals.completed.emit(self.request_id, result)


class GlobalSearchWidget(QFrame):
    result_activated = Signal(str, str)

    def __init__(self, mode_provider, service=None, parent=None):
        super().__init__(parent)
        self.setObjectName("GlobalSearchBar")
        self.mode_provider = mode_provider
        self.service = service or GlobalSearchService()
        self.thread_pool = QThreadPool.globalInstance()
        self.request_id = 0
        self.last_results = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 10, 18, 10)
        layout.setSpacing(8)
        search_row = QHBoxLayout()
        title = QLabel("横断検索")
        title.setObjectName("GlobalSearchTitle")
        self.search_input = QLineEdit()
        self.search_input.setObjectName("GlobalSearchInput")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setPlaceholderText("商品名・店舗名・カテゴリ・キーワードで検索")
        self.status_label = QLabel("商品・応募・店舗・通知などを検索できます")
        self.status_label.setObjectName("GlobalSearchStatus")
        search_row.addWidget(title)
        search_row.addWidget(self.search_input, 1)
        search_row.addWidget(self.status_label)
        layout.addLayout(search_row)

        self.results_panel = QFrame()
        self.results_panel.setObjectName("GlobalSearchResults")
        result_layout = QVBoxLayout(self.results_panel)
        result_layout.setContentsMargins(10, 8, 10, 8)
        self.result_scroll = QScrollArea()
        self.result_scroll.setWidgetResizable(True)
        self.result_scroll.setFrameShape(QFrame.NoFrame)
        self.result_scroll.setMaximumHeight(330)
        result_layout.addWidget(self.result_scroll)
        layout.addWidget(self.results_panel)
        self.results_panel.hide()

        self.debounce = QTimer(self)
        self.debounce.setSingleShot(True)
        self.debounce.setInterval(250)
        self.debounce.timeout.connect(self._start_search)
        self.search_input.textChanged.connect(self._query_changed)

    def _query_changed(self, text):
        self.request_id += 1
        self.debounce.stop()
        query = text.strip()
        if not query:
            self.last_results = {}
            self.results_panel.hide()
            self._set_status("商品・応募・店舗・通知などを検索できます", "idle")
            return
        self.results_panel.show()
        self._render_message("検索中です…")
        self._set_status("検索中…", "loading")
        self.debounce.start()

    def refresh_for_mode_change(self):
        if self.search_input.text().strip():
            self._query_changed(self.search_input.text())

    def _start_search(self):
        query = self.search_input.text().strip()
        if not query:
            return
        current_id = self.request_id
        task = SearchTask(current_id, self.service, query, self.mode_provider())
        task.signals.completed.connect(self._search_completed)
        task.signals.failed.connect(self._search_failed)
        self.thread_pool.start(task)

    def search_now(self):
        self.debounce.stop()
        self._start_search()

    @Slot(int, object)
    def _search_completed(self, request_id, results):
        if request_id != self.request_id:
            return
        count = sum(len(items) for items in results.values())
        if count == 0:
            self._render_message("一致する結果はありません。\n別のキーワードをお試しください。")
            self._set_status("0件", "empty")
            self.last_results = results
            return
        if results == self.last_results:
            self._set_status(f"{count}件", "success")
            return
        self.last_results = results
        self._render_results(results)
        self._set_status(f"{count}件", "success")

    @Slot(int, str)
    def _search_failed(self, request_id, reason):
        if request_id != self.request_id:
            return
        self.last_results = {}
        self._render_message(f"検索できませんでした。\n原因: {reason}", error=True)
        self._set_status("検索エラー", "error")

    def _render_results(self, results):
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        for group in GROUP_ORDER:
            items = results.get(group, [])
            if not items:
                continue
            heading = QLabel(f"{GROUP_LABELS[group]}（{len(items)}件）")
            heading.setObjectName("GlobalSearchGroupTitle")
            layout.addWidget(heading)
            for item in items:
                button = QPushButton(
                    item.get("title", "検索結果")
                    + (f'\n{item.get("detail", "")}' if item.get("detail") else "")
                )
                button.setObjectName("GlobalSearchResultButton")
                button.clicked.connect(
                    lambda _checked=False, value=item: self._activate(value)
                )
                layout.addWidget(button)
        layout.addStretch()
        self.result_scroll.setWidget(container)

    def _render_message(self, text, *, error=False):
        container = QWidget()
        layout = QVBoxLayout(container)
        label = QLabel(text)
        label.setObjectName("GlobalSearchError" if error else "GlobalSearchEmpty")
        label.setWordWrap(True)
        label.setMinimumHeight(70)
        layout.addWidget(label)
        self.result_scroll.setWidget(container)

    def _activate(self, item):
        self.result_activated.emit(
            str(item.get("target", "")), str(item.get("item_id", ""))
        )
        self.search_input.clear()

    def _set_status(self, text, state):
        self.status_label.setText(text)
        self.status_label.setProperty("state", state)
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)
