from __future__ import annotations

from datetime import date, datetime, timedelta

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtWidgets import (
    QCalendarWidget, QComboBox, QFrame, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QVBoxLayout, QWidget,
)

from core.phase3_dashboard import CalendarService
from core.product_store import ProductStore
from core.safe_product_url import can_open_product_url, open_product_url
from core.site_master_manager import SiteMasterManager


class CalendarPage(QFrame):
    navigate_requested = Signal(str, str)

    def __init__(self):
        super().__init__()
        self.setObjectName("ContentPanel")
        self.store = ProductStore()
        self.site_manager = SiteMasterManager()
        self.events = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 26)
        layout.setSpacing(14)
        header = QHBoxLayout()
        title = QLabel("カレンダー")
        title.setObjectName("PageTitle")
        self.view_mode = QComboBox()
        self.view_mode.addItems(["月表示", "週表示", "リスト表示"])
        self.view_mode.currentTextChanged.connect(self.reload)
        refresh = QPushButton("予定を更新")
        refresh.setObjectName("AccentButton")
        refresh.clicked.connect(self.reload)
        header.addWidget(title)
        header.addStretch()
        header.addWidget(self.view_mode)
        header.addWidget(refresh)
        layout.addLayout(header)

        self.calendar = QCalendarWidget()
        self.calendar.setGridVisible(True)
        self.calendar.selectionChanged.connect(self._render_events)
        layout.addWidget(self.calendar)

        self.summary = QLabel("")
        self.summary.setObjectName("MutedText")
        layout.addWidget(self.summary)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        layout.addWidget(self.scroll, 1)
        self.reload()

    def reload(self, *_args):
        self.events = CalendarService().build_events(
            self.store.load_products(), self.site_manager.load_sites()
        )
        self.calendar.setVisible(self.view_mode.currentText() != "リスト表示")
        self._render_events()

    def _selected_events(self):
        selected = self.calendar.selectedDate().toPython()
        mode = self.view_mode.currentText()
        if mode == "月表示":
            return [event for event in self.events if datetime.fromisoformat(event["starts_at"]).date().replace(day=1) == selected.replace(day=1)]
        if mode == "週表示":
            start = selected - timedelta(days=selected.weekday())
            return [event for event in self.events if start <= date.fromisoformat(event["date"]) <= start + timedelta(days=6)]
        return self.events

    def _render_events(self):
        events = self._selected_events()
        self.summary.setText(f"予定 {len(events)}件　色だけに依存せず、種類アイコンを併記しています。")
        container = QWidget()
        items = QVBoxLayout(container)
        items.setContentsMargins(0, 0, 0, 0)
        for event in events:
            card = QFrame()
            card.setObjectName("SettingsCard")
            row = QHBoxLayout(card)
            starts = datetime.fromisoformat(event["starts_at"])
            label = QLabel(
                f'{event["icon"]} {starts.strftime("%Y/%m/%d %H:%M")} '
                f'[{event["event_type"]}] {event["title"]}'
                + (f' / {event["site_name"]}' if event.get("site_name") else "")
            )
            label.setWordWrap(True)
            row.addWidget(label, 1)
            if event.get("product_id"):
                detail = QPushButton("商品詳細")
                detail.setObjectName("SmallButton")
                detail.clicked.connect(lambda _=False, value=event["product_id"]: self.navigate_requested.emit("product", value))
                row.addWidget(detail)
            if event.get("site_id"):
                application = QPushButton("応募詳細")
                application.setObjectName("SmallButton")
                application.clicked.connect(lambda _=False, value=event["product_id"]: self.navigate_requested.emit("application", value))
                row.addWidget(application)
            for text, key in (("商品ページ", "product_url"), ("応募ページ", "application_url")):
                url = str(event.get(key, ""))
                button = QPushButton(text)
                button.setObjectName("SmallButton")
                button.setEnabled(can_open_product_url(url))
                button.clicked.connect(lambda _=False, value=url: open_product_url(value))
                row.addWidget(button)
            items.addWidget(card)
        if not events:
            empty = QLabel("選択期間に予定はありません。")
            empty.setAlignment(Qt.AlignCenter)
            items.addWidget(empty)
        items.addStretch()
        self.scroll.setWidget(container)
