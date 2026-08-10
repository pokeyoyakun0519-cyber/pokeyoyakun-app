from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QToolButton, QVBoxLayout, QWidget,
)

from core.application_status import JST
from core.phase3_dashboard import HomeDashboardService, parse_datetime
from core.version import APP_CHANNEL, APP_VERSION


WEEKDAYS = "月火水木金土日"


class DashboardSectionCard(QFrame):
    """ホーム内で共通利用する、見出しと本文を持つカード。"""

    requested = Signal(str)

    def __init__(self, title: str, target: str = ""):
        super().__init__()
        self.setObjectName("HomeSectionCard")
        self.setMinimumWidth(240)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        header = QHBoxLayout()
        heading = QLabel(title)
        heading.setObjectName("SectionTitle")
        header.addWidget(heading)
        header.addStretch()
        if target:
            more = QPushButton("すべて見る")
            more.setObjectName("SmallButton")
            more.clicked.connect(lambda: self.requested.emit(target))
            header.addWidget(more)
        layout.addLayout(header)

        self.body = QVBoxLayout()
        self.body.setSpacing(8)
        layout.addLayout(self.body)
        layout.addStretch()

    def clear(self):
        while self.body.count():
            item = self.body.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def placeholder(self, text: str):
        label = QLabel(text)
        label.setObjectName("HomePlaceholder")
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignCenter)
        label.setMinimumHeight(64)
        self.body.addWidget(label)


class ResponsiveColumns(QWidget):
    """利用可能な幅に応じて左右カラムを縦積みへ切り替える。"""

    BREAKPOINT = 850

    def __init__(self, left: QWidget, right: QWidget):
        super().__init__()
        self.left = left
        self.right = right
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(16)
        self.grid.setVerticalSpacing(16)
        self._stacked = None
        self._reflow(self.width())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reflow(event.size().width())

    def _reflow(self, width: int):
        stacked = width < self.BREAKPOINT
        if stacked == self._stacked:
            return
        self._stacked = stacked
        self.grid.removeWidget(self.left)
        self.grid.removeWidget(self.right)
        if stacked:
            self.grid.addWidget(self.left, 0, 0)
            self.grid.addWidget(self.right, 1, 0)
            self.grid.setColumnStretch(0, 1)
            self.grid.setColumnStretch(1, 0)
        else:
            self.grid.addWidget(self.left, 0, 0)
            self.grid.addWidget(self.right, 0, 1)
            self.grid.setColumnStretch(0, 3)
            self.grid.setColumnStretch(1, 2)


class HomePage(QFrame):
    navigate_requested = Signal(str, str)

    def __init__(self, scheduler):
        super().__init__()
        self.setObjectName("ContentPanel")
        self.scheduler = scheduler
        self.service = HomeDashboardService()
        self._last_dashboard_signature = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        self.layout = QVBoxLayout(content)
        self.layout.setContentsMargins(28, 26, 28, 26)
        self.layout.setSpacing(16)
        self.scroll.setWidget(content)
        outer.addWidget(self.scroll)

        self._build_header()
        self._build_summary()
        self._build_main_area()
        self._build_footer()

        self.scheduler.status_changed.connect(self._on_scheduler_status)
        self.scheduler.run_completed.connect(self._on_run_completed)
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(30_000)
        self.refresh_timer.timeout.connect(self.refresh_dashboard)
        self.refresh_timer.start()
        self.refresh_dashboard()

    def _build_header(self):
        header = QHBoxLayout()
        title_box = QVBoxLayout()
        self.greeting_label = QLabel("")
        self.greeting_label.setObjectName("HomeGreeting")
        self.date_label = QLabel("")
        self.date_label.setObjectName("MutedText")
        title_box.addWidget(self.greeting_label)
        title_box.addWidget(self.date_label)

        run_button = QPushButton("今すぐ監視")
        run_button.clicked.connect(self.scheduler.run_now)
        refresh_button = QPushButton("状態を更新")
        refresh_button.setObjectName("AccentButton")
        refresh_button.clicked.connect(self.refresh_dashboard)
        header.addLayout(title_box)
        header.addStretch()
        header.addWidget(run_button)
        header.addWidget(refresh_button)
        self.layout.addLayout(header)

        self.scheduler_status = QLabel("自動監視：状態確認中")
        self.scheduler_status.setObjectName("DashboardStatusBar")
        self.layout.addWidget(self.scheduler_status)

    def _build_summary(self):
        summary = QFrame()
        summary.setObjectName("HomeSummaryCard")
        summary_layout = QVBoxLayout(summary)
        summary_layout.setContentsMargins(18, 16, 18, 16)
        summary_layout.setSpacing(10)
        heading = QLabel("今日やること")
        heading.setObjectName("SectionTitle")
        summary_layout.addWidget(heading)
        counts = QHBoxLayout()
        counts.setSpacing(12)
        self.summary_values = {}
        for key, title in (
            ("deadlines", "締切"), ("releases", "発売日"), ("new_items", "新着"),
        ):
            box = QFrame()
            box.setObjectName("HomeSummaryItem")
            box_layout = QVBoxLayout(box)
            box_layout.setContentsMargins(12, 8, 12, 8)
            label = QLabel(title)
            label.setObjectName("DashboardCardTitle")
            value = QLabel("0件")
            value.setObjectName("DashboardCardValue")
            box_layout.addWidget(label)
            box_layout.addWidget(value)
            counts.addWidget(box, 1)
            self.summary_values[key] = value
        summary_layout.addLayout(counts)
        self.layout.addWidget(summary)

    def _build_main_area(self):
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(16)
        self.actions_card = DashboardSectionCard("今日やること", "application")
        self.calendar_card = DashboardSectionCard("応募カレンダー", "calendar")
        self.timeline_card = DashboardSectionCard("タイムライン")
        left_layout.addWidget(self.actions_card)
        left_layout.addWidget(self.calendar_card)
        left_layout.addWidget(self.timeline_card)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(16)
        self.notifications_card = DashboardSectionCard("通知センター（最新5件）", "notifications")
        self.favorites_card = DashboardSectionCard("お気に入り商品", "product")
        self.new_products_card = DashboardSectionCard("新着商品", "product")
        right_layout.addWidget(self.notifications_card)
        right_layout.addWidget(self.favorites_card)
        right_layout.addWidget(self.new_products_card)

        for card in (
            self.actions_card, self.calendar_card, self.timeline_card,
            self.notifications_card, self.favorites_card, self.new_products_card,
        ):
            card.requested.connect(lambda target: self.navigate_requested.emit(target, ""))
        self.responsive_columns = ResponsiveColumns(left, right)
        self.layout.addWidget(self.responsive_columns)

    def _build_footer(self):
        footer = QHBoxLayout()
        self.changes_card = DashboardSectionCard("最近の変更履歴", "history")
        version_card = DashboardSectionCard("バージョン情報", "about")
        self.version_label = QLabel(
            f"ポケヨヤ君 Ver.{APP_VERSION} {APP_CHANNEL.upper()}\n"
            "アップデート情報はアプリ情報から確認できます。"
        )
        self.version_label.setObjectName("HomeListText")
        self.version_label.setWordWrap(True)
        version_card.body.addWidget(self.version_label)
        self.changes_card.requested.connect(lambda target: self.navigate_requested.emit(target, ""))
        version_card.requested.connect(lambda target: self.navigate_requested.emit(target, ""))
        footer.addWidget(self.changes_card, 3)
        footer.addWidget(version_card, 2)
        self.layout.addLayout(footer)

    def refresh_dashboard(self):
        now = datetime.now(JST)
        self.greeting_label.setText(self._greeting(now.hour))
        self.date_label.setText(
            f"{now.year}年{now.month}月{now.day}日（{WEEKDAYS[now.weekday()]}）"
        )
        data = self.service.build(now=now)
        signature = repr(data)
        if signature == self._last_dashboard_signature:
            return
        self._last_dashboard_signature = signature
        actions = data["actions"]
        self.summary_values["deadlines"].setText(
            f'{sum(item.get("kind") in {"today_deadline", "within_24h"} and not item.get("completed") for item in actions)}件'
        )
        self.summary_values["releases"].setText(
            f'{sum(item.get("kind") == "release" for item in actions)}件'
        )
        self.summary_values["new_items"].setText(
            f'{data["metrics"].get("new_products", 0) + data["metrics"].get("new_stores", 0)}件'
        )

        self._render_actions(actions)
        self._render_calendar(data.get("events", []), now)
        self._render_timeline(data.get("timeline", []))
        self._render_notifications(data.get("notifications", []))
        self._render_products(self.favorites_card, data.get("favorite_products", []), "お気に入り商品はありません。")
        self._render_products(self.new_products_card, data.get("new_products", []), "直近7日間の新着商品はありません。")
        self._render_changes(data.get("timeline", []))

    def _render_actions(self, actions):
        self.actions_card.clear()
        active = [item for item in actions if not item.get("completed")]
        completed = [item for item in actions if item.get("completed")]
        for action in active[:8]:
            self.actions_card.body.addWidget(self._action_button(action))
        if not active:
            self.actions_card.placeholder("今日対応が必要な項目はありません。\n新しい予定が入るとここに表示されます。")
        if completed:
            completed_toggle = QToolButton()
            completed_toggle.setText(f"完了済み（{len(completed)}件）")
            completed_toggle.setCheckable(True)
            completed_widget = QWidget()
            completed_layout = QVBoxLayout(completed_widget)
            completed_layout.setContentsMargins(12, 0, 0, 0)
            for action in completed[:5]:
                completed_layout.addWidget(self._action_button(action))
            completed_widget.setVisible(False)
            completed_toggle.toggled.connect(completed_widget.setVisible)
            self.actions_card.body.addWidget(completed_toggle)
            self.actions_card.body.addWidget(completed_widget)

    def _render_calendar(self, events, now):
        self.calendar_card.clear()
        upcoming = [event for event in events if (parse_datetime(event.get("starts_at")) or now) >= now][:5]
        for event in upcoming:
            starts = parse_datetime(event.get("starts_at"))
            date_text = starts.strftime("%m/%d %H:%M") if starts else "日時未定"
            text = f'{event.get("icon", "・")} {date_text}　{event.get("title", "予定")}\n{event.get("event_type", "")} {event.get("site_name", "")}'.strip()
            self.calendar_card.body.addWidget(self._row_button(text, "calendar", str(event.get("product_id", ""))))
        if not upcoming:
            self.calendar_card.placeholder("今後の応募・発売予定はありません。")

    def _render_timeline(self, items):
        self.timeline_card.clear()
        for item in items[:6]:
            date_text = str(item.get("occurred_at", ""))[:10].replace("-", "/") or "日時不明"
            target = "product" if item.get("product_id") else "site_master" if item.get("store_id") else "notifications"
            item_id = str(item.get("product_id") or item.get("store_id") or "")
            self.timeline_card.body.addWidget(self._row_button(
                f'{date_text}　{item.get("title", "更新情報")}', target, item_id
            ))
        if not items:
            self.timeline_card.placeholder("最近追加された情報はありません。")

    def _render_notifications(self, items):
        self.notifications_card.clear()
        for item in items[:5]:
            unread = "● " if not item.get("read") else ""
            text = f'{unread}{item.get("title", "通知")}\n{item.get("category", "情報")}　{item.get("created_at", "")}'
            self.notifications_card.body.addWidget(self._row_button(text, "notifications", ""))
        if not items:
            self.notifications_card.placeholder("通知はまだありません。\n重要なお知らせが届くとここに表示されます。")

    def _render_products(self, card, products, placeholder):
        card.clear()
        for product in products[:6]:
            product_id = str(product.get("product_id", product.get("id", "")))
            name = str(product.get("canonical_name", product.get("name", "商品名未設定")))
            tcg = str(product.get("tcg_key", "")).upper()
            card.body.addWidget(self._row_button(f"★ {name}\n{tcg}", "product", product_id))
        if not products:
            card.placeholder(placeholder)

    def _render_changes(self, items):
        self.changes_card.clear()
        for item in items[:5]:
            date_text = str(item.get("occurred_at", ""))[:16].replace("T", " ").replace("-", "/")
            label = QLabel(f'{date_text}　{item.get("event_type", "更新")}\n{item.get("title", "変更がありました")}')
            label.setObjectName("HomeListText")
            label.setWordWrap(True)
            self.changes_card.body.addWidget(label)
        if not items:
            self.changes_card.placeholder("最近の変更履歴はありません。")

    def _action_button(self, action):
        return self._row_button(
            f'{action.get("lead", "")}\n{action.get("title", "")}',
            "application" if action.get("product_id") else "site_master" if action.get("store_id") else "notifications",
            str(action.get("product_id") or action.get("store_id") or ""),
        )

    def _row_button(self, text, target, item_id):
        button = QPushButton(text)
        button.setObjectName("HomeListButton")
        button.setMinimumHeight(46)
        button.clicked.connect(
            lambda _checked=False, destination=target, value=item_id:
            self.navigate_requested.emit(destination, value)
        )
        return button

    @staticmethod
    def _greeting(hour: int):
        if hour < 11:
            return "おはようございます"
        if hour < 18:
            return "こんにちは"
        return "こんばんは"

    def _on_scheduler_status(self, text: str):
        self.scheduler_status.setText(text)
        self.refresh_dashboard()

    def _on_run_completed(self, result: dict):
        self.scheduler_status.setText(
            f'監視完了：変更候補{len(result.get("changed_sources", []))}件 / '
            f'当選候補{len(result.get("newly_won", []))}件'
        )
        self.refresh_dashboard()
