from datetime import datetime, timedelta

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from core.daily_task_manager import DailyTaskManager
from core.external_notification_config import ExternalNotificationConfig
from core.lottery_manager import LotteryManager
from core.notification_store import NotificationStore
from core.scheduler_config import SchedulerConfig
from core.source_manager import SourceManager
from core.version import APP_CHANNEL, APP_VERSION


class StatusCard(QFrame):
    def __init__(self, title: str):
        super().__init__()
        self.setObjectName("DashboardCard")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(8)

        title_label = QLabel(title)
        title_label.setObjectName("DashboardCardTitle")

        self.value_label = QLabel("-")
        self.value_label.setObjectName("DashboardCardValue")
        self.value_label.setWordWrap(True)

        self.detail_label = QLabel("")
        self.detail_label.setObjectName("MutedText")
        self.detail_label.setWordWrap(True)

        layout.addWidget(title_label)
        layout.addWidget(self.value_label)
        layout.addWidget(self.detail_label)
        layout.addStretch()

    def set_status(
        self,
        value: str,
        detail: str = "",
        level: str = "normal",
    ):
        self.value_label.setText(value)
        self.detail_label.setText(detail)
        self.value_label.setProperty("statusLevel", level)
        self.value_label.style().unpolish(self.value_label)
        self.value_label.style().polish(self.value_label)


class HomePage(QFrame):
    def __init__(self, scheduler):
        super().__init__()
        self.setObjectName("ContentPanel")

        self.scheduler = scheduler
        self.scheduler_config = SchedulerConfig()
        self.external_config = ExternalNotificationConfig()
        self.notification_store = NotificationStore()
        self.source_manager = SourceManager()
        self.lottery_manager = LotteryManager()
        self.daily_task_manager = DailyTaskManager()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 26)
        layout.setSpacing(16)

        header = QHBoxLayout()

        title_box = QVBoxLayout()
        title = QLabel("ダッシュボード")
        title.setObjectName("PageTitle")

        subtitle = QLabel(
            f"ポケヨヤ君 Ver.{APP_VERSION} {APP_CHANNEL.upper()}"
        )
        subtitle.setObjectName("MutedText")

        title_box.addWidget(title)
        title_box.addWidget(subtitle)

        refresh_button = QPushButton("状態を更新")
        refresh_button.setObjectName("AccentButton")
        refresh_button.clicked.connect(self.refresh_dashboard)

        run_button = QPushButton("今すぐ監視")
        run_button.clicked.connect(self.scheduler.run_now)

        header.addLayout(title_box)
        header.addStretch()
        header.addWidget(run_button)
        header.addWidget(refresh_button)
        layout.addLayout(header)

        self.scheduler_status = QLabel("自動監視：状態確認中")
        self.scheduler_status.setObjectName("DashboardStatusBar")
        self.scheduler_status.setWordWrap(True)
        layout.addWidget(self.scheduler_status)

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(14)

        self.monitor_card = StatusCard("監視状態")
        self.sources_card = StatusCard("公式情報ソース")
        self.lotteries_card = StatusCard("抽選結果ページ")
        self.notifications_card = StatusCard("通知センター")
        self.discord_card = StatusCard("Discord通知")
        self.email_card = StatusCard("メール通知")
        self.last_run_card = StatusCard("最終監視")
        self.next_run_card = StatusCard("次回監視")

        cards = [
            self.monitor_card,
            self.sources_card,
            self.lotteries_card,
            self.notifications_card,
            self.discord_card,
            self.email_card,
            self.last_run_card,
            self.next_run_card,
        ]

        for index, card in enumerate(cards):
            grid.addWidget(card, index // 4, index % 4)

        layout.addLayout(grid)

        task_header = QHBoxLayout()
        task_title = QLabel("今日・明日の予定")
        task_title.setObjectName("SectionTitle")
        self.task_count = QLabel("")
        self.task_count.setObjectName("MutedText")
        task_header.addWidget(task_title)
        task_header.addStretch()
        task_header.addWidget(self.task_count)
        layout.addLayout(task_header)

        self.task_list = QLabel("")
        self.task_list.setObjectName("DashboardStatusBar")
        self.task_list.setWordWrap(True)
        self.task_list.setTextInteractionFlags(
            Qt.TextSelectableByMouse
        )
        layout.addWidget(self.task_list)

        layout.addStretch()

        self.scheduler.status_changed.connect(
            self._on_scheduler_status
        )
        self.scheduler.run_completed.connect(
            self._on_run_completed
        )

        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(30_000)
        self.refresh_timer.timeout.connect(
            self.refresh_dashboard
        )
        self.refresh_timer.start()

        self.refresh_dashboard()

    def refresh_dashboard(self):
        scheduler = self.scheduler_config.load()
        external = self.external_config.load()
        sources = self.source_manager.load_sources()
        lotteries = self.lottery_manager.load_items()
        notifications = self.notification_store.load()
        unread = self.notification_store.unread_count()

        enabled = bool(scheduler.get("enabled", False))
        running = bool(getattr(self.scheduler, "running", False))

        if running:
            self.monitor_card.set_status(
                "確認中",
                "バックグラウンドで監視しています。",
                "warning",
            )
        elif enabled:
            self.monitor_card.set_status(
                "動作中",
                f'{scheduler.get("interval_minutes", 30)}分間隔',
                "success",
            )
        else:
            self.monitor_card.set_status(
                "停止中",
                "自動監視はOFFです。",
                "muted",
            )

        changed_count = sum(
            1 for item in sources
            if item.get("changed", False)
        )
        self.sources_card.set_status(
            f"{len(sources)}件",
            f"変更候補：{changed_count}件",
            "warning" if changed_count else "normal",
        )

        won_count = sum(
            1 for item in lotteries
            if item.get("status") == "当選候補"
        )
        self.lotteries_card.set_status(
            f"{len(lotteries)}件",
            f"当選候補：{won_count}件",
            "success" if won_count else "normal",
        )

        self.notifications_card.set_status(
            f"未読 {unread}件",
            f"保存済み：{len(notifications)}件",
            "warning" if unread else "normal",
        )

        discord_enabled = bool(
            external.get("discord_enabled", False)
            and external.get("discord_webhook_url", "")
        )
        self.discord_card.set_status(
            "有効" if discord_enabled else "無効",
            "Webhook設定済み" if discord_enabled else "外部通知で設定できます。",
            "success" if discord_enabled else "muted",
        )

        email_enabled = bool(
            external.get("email_enabled", False)
            and external.get("smtp_host", "")
            and external.get("email_to", "")
        )
        self.email_card.set_status(
            "有効" if email_enabled else "無効",
            "SMTP設定済み" if email_enabled else "外部通知で設定できます。",
            "success" if email_enabled else "muted",
        )

        last_run_text = str(
            scheduler.get("last_run", "")
        ).strip()

        if last_run_text:
            try:
                last_run = datetime.fromisoformat(last_run_text)
                last_display = last_run.strftime("%Y/%m/%d %H:%M")
            except ValueError:
                last_run = None
                last_display = last_run_text
        else:
            last_run = None
            last_display = "未実行"

        self.last_run_card.set_status(
            last_display,
            "最後に監視した時刻",
            "normal",
        )

        if enabled and last_run is not None:
            next_run = last_run + timedelta(
                minutes=int(
                    scheduler.get("interval_minutes", 30)
                )
            )
            next_display = next_run.strftime("%Y/%m/%d %H:%M")
        elif enabled:
            next_display = "まもなく実行"
        else:
            next_display = "自動監視OFF"

        self.next_run_card.set_status(
            next_display,
            "予定時刻",
            "normal" if enabled else "muted",
        )

        tasks = self.daily_task_manager.build_tasks(
            days_ahead=1
        )
        self.task_count.setText(
            f"{len(tasks)}件"
        )

        if tasks:
            task_lines = []
            for task in tasks[:8]:
                site = (
                    f' / {task["site_name"]}'
                    if task["site_name"]
                    else ""
                )
                task_lines.append(
                    f'・{task["due_date"]} '
                    f'[{task["task_type"]}] '
                    f'{task["product_name"]}{site}'
                )

            if len(tasks) > 8:
                task_lines.append(
                    f"・ほか{len(tasks) - 8}件"
                )

            self.task_list.setText(
                "\n".join(task_lines)
            )
        else:
            self.task_list.setText(
                "今日・明日に必要な応募、結果確認、"
                "購入、発売予定はありません。"
            )


    def _on_scheduler_status(self, text: str):
        self.scheduler_status.setText(text)
        self.refresh_dashboard()


    def _on_run_completed(self, result: dict):
        changes = len(
            result.get(
                "changed_sources",
                [],
            )
        )
        wins = len(
            result.get(
                "newly_won",
                [],
            )
        )
        searched = int(
            result.get(
                "candidate_search",
                {},
            ).get(
                "searched_count",
                0,
            )
        )

        self.scheduler_status.setText(
            "監視完了："
            f"変更候補{changes}件 / "
            f"当選候補{wins}件 / "
            f"販売情報検索{searched}件"
        )
        self.refresh_dashboard()
