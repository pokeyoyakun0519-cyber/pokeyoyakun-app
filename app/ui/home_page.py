from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QToolButton, QVBoxLayout, QWidget,
)

from core.phase3_dashboard import HomeDashboardService
from core.version import APP_CHANNEL, APP_VERSION


class StatusCard(QFrame):
    clicked = Signal(str)

    def __init__(self, title: str, target: str = ""):
        super().__init__()
        self.target = target
        self.setObjectName("DashboardCard")
        self.setCursor(Qt.PointingHandCursor if target else Qt.ArrowCursor)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        title_label = QLabel(title)
        title_label.setObjectName("DashboardCardTitle")
        self.value_label = QLabel("-")
        self.value_label.setObjectName("DashboardCardValue")
        self.detail_label = QLabel("")
        self.detail_label.setObjectName("MutedText")
        self.detail_label.setWordWrap(True)
        layout.addWidget(title_label)
        layout.addWidget(self.value_label)
        layout.addWidget(self.detail_label)

    def set_status(self, value: str, detail: str = "", level: str = "normal"):
        self.value_label.setText(value)
        self.detail_label.setText(detail)
        self.value_label.setProperty("statusLevel", level)
        self.value_label.style().unpolish(self.value_label)
        self.value_label.style().polish(self.value_label)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if self.target and event.button() == Qt.LeftButton:
            self.clicked.emit(self.target)


class HomePage(QFrame):
    navigate_requested = Signal(str, str)

    def __init__(self, scheduler):
        super().__init__()
        self.setObjectName("ContentPanel")
        self.scheduler = scheduler
        self.service = HomeDashboardService()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        self.layout = QVBoxLayout(content)
        self.layout.setContentsMargins(28, 26, 28, 26)
        self.layout.setSpacing(16)
        scroll.setWidget(content)
        outer.addWidget(scroll)

        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("ホーム")
        title.setObjectName("PageTitle")
        subtitle = QLabel(f"今日やることが一目で分かります　Ver.{APP_VERSION} {APP_CHANNEL.upper()}")
        subtitle.setObjectName("MutedText")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
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

        heading = QLabel("今日やること")
        heading.setObjectName("SectionTitle")
        self.layout.addWidget(heading)
        self.action_container = QVBoxLayout()
        self.layout.addLayout(self.action_container)

        metric_title = QLabel("ホームダッシュボード")
        metric_title.setObjectName("SectionTitle")
        self.layout.addWidget(metric_title)
        self.metric_grid = QGridLayout()
        definitions = (
            ("today_deadlines", "今日締切", "application"),
            ("open_applications", "応募受付中", "application"),
            ("waiting_results", "結果待ち", "application"),
            ("new_products", "新商品", "product"),
            ("new_stores", "新店舗", "site_master"),
            ("monitored_stores", "監視中店舗", "site_master"),
            ("monitor_errors", "監視エラー", "log"),
            ("sources", "公式情報ソース", "sources"),
            ("notifications", "通知センター", "notifications"),
            ("update", "アップデート確認", "update"),
        )
        self.metric_cards = {}
        for index, (key, title_text, target) in enumerate(definitions):
            card = StatusCard(title_text, target)
            card.clicked.connect(lambda value: self.navigate_requested.emit(value, ""))
            self.metric_cards[key] = card
            self.metric_grid.addWidget(card, index // 5, index % 5)
        self.layout.addLayout(self.metric_grid)

        columns = QHBoxLayout()
        self.favorite_box = self._section_box("お気に入り商品")
        self.timeline_box = self._section_box("最近追加された情報")
        self.monitoring_box = self._section_box("監視状況")
        columns.addWidget(self.favorite_box[0], 1)
        columns.addWidget(self.timeline_box[0], 1)
        columns.addWidget(self.monitoring_box[0], 1)
        self.layout.addLayout(columns)
        self.layout.addStretch()

        self.scheduler.status_changed.connect(self._on_scheduler_status)
        self.scheduler.run_completed.connect(self._on_run_completed)
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(30_000)
        self.refresh_timer.timeout.connect(self.refresh_dashboard)
        self.refresh_timer.start()
        self.refresh_dashboard()

    @staticmethod
    def _section_box(title: str):
        frame = QFrame()
        frame.setObjectName("SettingsCard")
        layout = QVBoxLayout(frame)
        heading = QLabel(title)
        heading.setObjectName("SectionTitle")
        body = QLabel("")
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(heading)
        layout.addWidget(body)
        layout.addStretch()
        return frame, body

    def refresh_dashboard(self):
        data = self.service.build()
        self._render_actions(data["actions"])
        metrics = data["metrics"]
        for key, card in self.metric_cards.items():
            if key == "update":
                card.set_status("確認", "クリックして更新画面へ")
            elif key == "sources":
                card.set_status(f'{metrics[key]}件', f'エラー {metrics["source_errors"]}件')
            else:
                card.set_status(f'{metrics.get(key, 0)}件', "クリックして詳細へ", "warning" if key in {"today_deadlines", "monitor_errors"} and metrics.get(key) else "normal")

        favorites = data["favorite_products"]
        favorite_lines = [
            f'★ {item.get("canonical_name", item.get("name", "商品"))}' for item in favorites
        ] + [f'★ 店舗: {item.get("name", "店舗")}' for item in data.get("favorite_stores", [])]
        self.favorite_box[1].setText("\n".join(favorite_lines) or "お気に入りはありません。")
        self.timeline_box[1].setText("\n".join(
            f'{str(item.get("occurred_at", ""))[:10].replace("-", "/")}　{item.get("title", "")}'
            for item in data["timeline"][:20]
        ) or "最近追加された情報はありません。")
        monitoring = data["monitoring"]
        last = self._relative_time(monitoring.get("last_updated", ""))
        self.monitoring_box[1].setText(
            f'監視中　{monitoring["stores"]}店舗\n予約　{monitoring["reservations"]}件\n'
            f'抽選　{monitoring["lotteries"]}件\n取得失敗　{monitoring["errors"]}件\n最終更新　{last}'
        )

    def _render_actions(self, actions):
        while self.action_container.count():
            item = self.action_container.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        active = [item for item in actions if not item.get("completed")]
        completed = [item for item in actions if item.get("completed")]
        for action in active:
            self.action_container.addWidget(self._action_button(action))
        if not active:
            empty = QLabel("今日対応が必要な項目はありません。")
            empty.setObjectName("DashboardStatusBar")
            self.action_container.addWidget(empty)
        completed_toggle = QToolButton()
        completed_toggle.setText(f"完了済み（{len(completed)}件）")
        completed_toggle.setCheckable(True)
        completed_toggle.setChecked(False)
        completed_widget = QWidget()
        completed_layout = QVBoxLayout(completed_widget)
        completed_layout.setContentsMargins(18, 0, 0, 0)
        for action in completed:
            completed_layout.addWidget(self._action_button(action))
        completed_widget.setVisible(False)
        completed_toggle.toggled.connect(completed_widget.setVisible)
        self.action_container.addWidget(completed_toggle)
        self.action_container.addWidget(completed_widget)

    def _action_button(self, action):
        button = QPushButton(f'{action.get("lead", "")}\n{action.get("title", "") }')
        button.setObjectName("DashboardStatusBar")
        button.setMinimumHeight(48)
        button.clicked.connect(lambda _=False, item=action: self._open_action(item))
        return button

    def _open_action(self, action):
        target = "application" if action.get("product_id") else "site_master" if action.get("store_id") else "notifications"
        self.navigate_requested.emit(target, str(action.get("product_id") or action.get("store_id") or ""))

    @staticmethod
    def _relative_time(value):
        try:
            elapsed = datetime.now().astimezone() - datetime.fromisoformat(str(value)).astimezone()
        except (ValueError, TypeError):
            return "未実行"
        minutes = max(0, int(elapsed.total_seconds() // 60))
        return f"{minutes}分前" if minutes < 60 else f"{minutes // 60}時間前"

    def _on_scheduler_status(self, text: str):
        self.scheduler_status.setText(text)
        self.refresh_dashboard()

    def _on_run_completed(self, result: dict):
        self.scheduler_status.setText(
            f'監視完了：変更候補{len(result.get("changed_sources", []))}件 / '
            f'当選候補{len(result.get("newly_won", []))}件'
        )
        self.refresh_dashboard()
