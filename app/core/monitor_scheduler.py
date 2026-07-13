import threading
from datetime import datetime, timedelta

from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot

from core.candidate_auto_search import CandidateAutoSearch
from core.error_throttle import ErrorThrottle
from core.external_notification_config import ExternalNotificationConfig
from core.external_notifier import ExternalNotifier
from core.gmail_result_service import GmailResultService
from core.log_manager import LogManager
from core.lottery_manager import LotteryManager
from core.notification_store import NotificationStore
from core.product_store import ProductStore
from core.scheduler_config import SchedulerConfig
from core.source_manager import SourceManager


class MonitorWorker(QObject):
    completed = Signal(dict)
    failed = Signal(str)

    def __init__(
        self,
        check_sources: bool,
        check_lotteries: bool,
        check_candidate_retail: bool,
        candidate_interval_minutes: int,
        check_gmail_results: bool,
    ):
        super().__init__()
        self.check_sources = check_sources
        self.check_lotteries = check_lotteries
        self.check_candidate_retail = check_candidate_retail
        self.candidate_interval_minutes = candidate_interval_minutes
        self.check_gmail_results = check_gmail_results

    @Slot()
    def run(self):
        try:
            result = {
                "source_count": 0,
                "changed_sources": [],
                "lottery_count": 0,
                "newly_won": [],
                "candidate_search": {
                    "searched_count": 0,
                    "new_hit_candidates": [],
                },
                "due_results": [],
                "gmail_results": [],
            }

            if self.check_sources:
                sources, changed = SourceManager().check_all()
                result["source_count"] = len(sources)
                result["changed_sources"] = changed

            if self.check_lotteries:
                lotteries, newly_won = LotteryManager().check_all()
                result["lottery_count"] = len(lotteries)
                result["newly_won"] = newly_won

            if self.check_candidate_retail:
                result["candidate_search"] = (
                    CandidateAutoSearch().run_due(
                        self.candidate_interval_minutes
                    )
                )

            if self.check_gmail_results:
                result["gmail_results"] = (
                    GmailResultService()
                    .scan_all_enabled()
                )

            result["due_results"] = (
                ProductStore().get_due_result_sites()
            )

            self.completed.emit(result)
        except Exception as error:
            self.failed.emit(str(error))


class MonitorScheduler(QObject):
    status_changed = Signal(str)
    run_completed = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.config_manager = SchedulerConfig()
        self.notification_store = NotificationStore()
        self.log_manager = LogManager()
        self.external_config = ExternalNotificationConfig()
        self.error_throttle = ErrorThrottle()

        self.timer = QTimer(self)
        self.timer.setInterval(60_000)
        self.timer.timeout.connect(self._check_due)

        self.thread = None
        self.worker = None
        self.running = False

        self.timer.start()
        QTimer.singleShot(1500, self._check_due)

    def reload_config(self):
        self._check_due()

    def run_now(self):
        self._start_run(self.config_manager.load())

    def _check_due(self):
        config = self.config_manager.load()

        if not config.get("enabled", False):
            self.status_changed.emit("自動監視：OFF")
            return

        if self.running:
            self.status_changed.emit("自動監視：確認中")
            return

        last_run_text = str(config.get("last_run", "")).strip()
        last_run = None

        if last_run_text:
            try:
                last_run = datetime.fromisoformat(last_run_text)
            except ValueError:
                last_run = None

        interval = timedelta(
            minutes=int(config.get("interval_minutes", 30))
        )

        if last_run is None or datetime.now() - last_run >= interval:
            self._start_run(config)
            return

        next_run = last_run + interval
        self.status_changed.emit(
            "次回自動確認："
            + next_run.strftime("%Y/%m/%d %H:%M")
        )

    def _start_run(self, config: dict):
        if self.running:
            return

        check_sources = bool(config.get("check_sources", True))
        check_lotteries = bool(config.get("check_lotteries", True))
        check_candidate_retail = bool(
            config.get("check_candidate_retail", True)
        )
        candidate_interval_minutes = int(
            config.get(
                "candidate_retail_interval_minutes",
                30,
            )
        )
        check_gmail_results = bool(
            config.get(
                "check_gmail_results",
                True,
            )
        )

        if (
            not check_sources
            and not check_lotteries
            and not check_candidate_retail
            and not check_gmail_results
        ):
            self.status_changed.emit("監視対象が選択されていません")
            return

        self.running = True
        self.status_changed.emit("自動監視：確認中")

        self.thread = QThread(self)
        self.worker = MonitorWorker(
            check_sources,
            check_lotteries,
            check_candidate_retail,
            candidate_interval_minutes,
            check_gmail_results,
        )
        self.worker.moveToThread(self.thread)

        self.thread.started.connect(self.worker.run)
        self.worker.completed.connect(self._on_completed)
        self.worker.failed.connect(self._on_failed)
        self.worker.completed.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self.thread.finished.connect(self._cleanup_thread)
        self.thread.start()

    @Slot(dict)
    def _on_completed(self, result: dict):
        config = self.config_manager.load()
        config["last_run"] = datetime.now().isoformat(
            timespec="seconds"
        )
        self.config_manager.save(config)

        changed_sources = result.get("changed_sources", [])
        newly_won = result.get("newly_won", [])
        candidate_search = result.get("candidate_search", {})
        due_results = result.get("due_results", [])
        gmail_results = result.get(
            "gmail_results",
            [],
        )

        if changed_sources:
            self._notify_source_changes(changed_sources)

        if newly_won:
            self._notify_lottery_wins(newly_won)

        new_hit_candidates = candidate_search.get(
            "new_hit_candidates",
            [],
        )
        if new_hit_candidates:
            self._notify_new_retail_hits(
                new_hit_candidates
            )

        if gmail_results:
            self._notify_gmail_results(
                gmail_results
            )

        if due_results:
            self._notify_due_results(due_results)

        self.log_manager.write(
            "自動監視完了: "
            f"情報ソース{result.get('source_count', 0)}件 / "
            f"抽選{result.get('lottery_count', 0)}件 / "
            f"変更{len(changed_sources)}件 / "
            f"当選候補{len(newly_won)}件 / "
            f"販売情報検索"
            f"{candidate_search.get('searched_count', 0)}件 / "
            f"結果確認待ち{len(due_results)}件 / "
            f"Gmail結果{len(gmail_results)}件"
        )

        self.running = False
        self.run_completed.emit(result)
        self.status_changed.emit(
            "最終自動確認："
            + datetime.now().strftime(
                "%Y/%m/%d %H:%M:%S"
            )
        )

    def _notify_source_changes(self, items: list[dict]):
        first = items[0]
        name = first.get("name", "名称未設定")
        url = first.get("url", "")
        page_title = first.get("last_title", "")

        title = "公式情報の変更を検知"
        message = f"{len(items)}件の変更候補があります。"

        self.notification_store.add(
            title,
            f"{message} {name}",
            "自動監視",
        )

        if not self.external_config.load().get(
            "notify_source_changes",
            True,
        ):
            return

        fields = [
            {
                "name": "情報ソース",
                "value": name,
                "inline": False,
            },
            {
                "name": "ページタイトル",
                "value": page_title or "取得なし",
                "inline": False,
            },
        ]

        official_changes = first.get(
            "official_changes",
            [],
        )
        if official_changes:
            detail_lines = []

            for change in official_changes[:5]:
                for field in change.get(
                    "changes",
                    {},
                ).values():
                    detail_lines.append(
                        f'{field.get("label", "変更")}: '
                        f'{field.get("before", "")} → '
                        f'{field.get("after", "")}'
                    )

            if detail_lines:
                fields.append(
                    {
                        "name": "公式情報の変更内容",
                        "value": "\n".join(
                            detail_lines
                        ),
                        "inline": False,
                    }
                )

        if len(items) > 1:
            fields.append(
                {
                    "name": "ほかの変更候補",
                    "value": "、".join(
                        item.get("name", "名称未設定")
                        for item in items[1:5]
                    ),
                    "inline": False,
                }
            )

        self._send_external_async(
            title,
            message,
            "公式情報",
            url=url,
            fields=fields,
        )

    def _notify_lottery_wins(self, items: list[dict]):
        first = items[0]
        product_name = first.get(
            "product_name",
            "商品名未設定",
        )
        site_name = first.get(
            "site_name",
            "サイト名未設定",
        )
        url = first.get("url", "")
        keyword = first.get(
            "matched_keyword",
            "",
        )

        title = "当選候補を検知"
        message = (
            f"{len(items)}件の当選候補があります。"
        )

        self.notification_store.add(
            title,
            f"{message} {product_name} / {site_name}",
            "自動監視",
        )

        if not self.external_config.load().get(
            "notify_lottery_wins",
            True,
        ):
            return

        fields = [
            {
                "name": "商品",
                "value": product_name,
                "inline": False,
            },
            {
                "name": "店舗・サイト",
                "value": site_name,
                "inline": True,
            },
            {
                "name": "検知キーワード",
                "value": keyword or "当選関連語",
                "inline": True,
            },
        ]

        if len(items) > 1:
            fields.append(
                {
                    "name": "ほかの当選候補",
                    "value": "\n".join(
                        "• "
                        + item.get(
                            "product_name",
                            "商品名未設定",
                        )
                        + " / "
                        + item.get(
                            "site_name",
                            "サイト名未設定",
                        )
                        for item in items[1:5]
                    ),
                    "inline": False,
                }
            )

        self._send_external_async(
            title,
            message,
            "抽選",
            url=url,
            fields=fields,
        )

    def _notify_new_retail_hits(
        self,
        items: list[dict],
    ):
        first = items[0]
        candidate = first.get("candidate", {})
        hits = first.get("new_hits", [])
        title = "新しい販売・抽選情報を検出"
        message = (
            f"{candidate.get('name', '商品名未設定')} / "
            f"{len(hits)}件"
        )

        self.notification_store.add(
            title,
            message,
            "販売情報",
        )

        self._send_external_async(
            title,
            message,
            "販売情報",
            url=(
                hits[0].get("url", "")
                if hits
                else ""
            ),
            fields=[
                {
                    "name": "店舗",
                    "value": "、".join(
                        hit.get("name", "店舗")
                        for hit in hits[:5]
                    ),
                    "inline": False,
                }
            ],
        )


    def _notify_gmail_results(
        self,
        items: list[dict],
    ):
        valid = [
            item
            for item in items
            if item.get("status")
            in {"当選", "落選", "要確認"}
        ]

        if not valid:
            return

        wins = [
            item
            for item in valid
            if item.get("status") == "当選"
        ]
        losses = [
            item
            for item in valid
            if item.get("status") == "落選"
        ]
        reviews = [
            item
            for item in valid
            if item.get("status") == "要確認"
        ]

        title = "抽選結果メールを検出"
        message = (
            f"当選{len(wins)}件 / "
            f"落選{len(losses)}件 / "
            f"要確認{len(reviews)}件"
        )

        self.notification_store.add(
            title,
            message,
            "Gmail",
        )

        first = valid[0]
        fields = []

        for item in valid[:5]:
            fields.append(
                {
                    "name": (
                        str(
                            item.get(
                                "status",
                                "要確認",
                            )
                        )
                        + " / "
                        + str(
                            item.get(
                                "site_name",
                                "店舗未特定",
                            )
                        )
                    ),
                    "value": (
                        str(
                            item.get(
                                "product_name",
                                "商品未特定",
                            )
                        )
                        + "\n"
                        + str(
                            item.get(
                                "account_email",
                                "",
                            )
                        )
                    ),
                    "inline": False,
                }
            )

        self._send_external_async(
            title,
            message,
            "Gmail",
            url=str(
                first.get(
                    "gmail_url",
                    "",
                )
            ),
            fields=fields,
        )

    def _notify_due_results(
        self,
        sites: list[dict],
    ):
        title = "抽選結果の確認日です"
        names = "、".join(
            site.get("name", "店舗")
            for site in sites[:5]
        )
        app_only = [
            site
            for site in sites
            if site.get("result_mode")
            in {"manual_app", "manual_store"}
        ]
        message = (
            f"{len(sites)}件の抽選結果を確認してください。"
        )

        self.notification_store.add(
            title,
            message + " " + names,
            "抽選結果",
        )

        self._send_external_async(
            title,
            message,
            "抽選結果",
            url=(
                sites[0].get("url", "")
                if sites
                else ""
            ),
            fields=[
                {
                    "name": "確認先",
                    "value": names,
                    "inline": False,
                },
                {
                    "name": "注意",
                    "value": (
                        "アプリ限定・店頭確認の店舗は自動判定できません。"
                        "対象アプリや店舗で確認後、当選・落選を"
                        "手動で登録してください。"
                        + (
                            "\n手動確認対象: "
                            + "、".join(
                                item.get("name", "店舗")
                                for item in app_only[:5]
                            )
                            if app_only
                            else ""
                        )
                    ),
                    "inline": False,
                },
            ],
        )

    @Slot(str)
    def _on_failed(self, message: str):
        self.log_manager.write(
            f"自動監視失敗: {message}",
            level="ERROR",
        )
        self.notification_store.add(
            "自動監視に失敗",
            message,
            "エラー",
        )

        error_key = "monitor:" + message.strip()
        should_notify, count = (
            self.error_throttle.should_notify(
                error_key,
                cooldown_minutes=10,
            )
        )

        if (
            should_notify
            and self.external_config.load().get(
                "notify_errors",
                True,
            )
        ):
            fields = [
                {
                    "name": "対応",
                    "value": (
                        "ログビューアで詳細を確認してください。"
                    ),
                    "inline": False,
                }
            ]
            if count > 1:
                fields.append(
                    {
                        "name": "発生回数",
                        "value": f"{count}回",
                        "inline": True,
                    }
                )

            self._send_external_async(
                "自動監視に失敗",
                message,
                "エラー",
                fields=fields,
            )

        self.running = False
        self.status_changed.emit(
            "自動監視：エラー"
        )

    def _send_external_async(
        self,
        title: str,
        message: str,
        category: str,
        *,
        url: str = "",
        fields: list[dict] | None = None,
    ):
        def send():
            ExternalNotifier().send(
                title,
                message,
                category,
                url=url,
                fields=fields or [],
            )

        threading.Thread(
            target=send,
            daemon=True,
        ).start()

    def _cleanup_thread(self):
        if self.worker is not None:
            self.worker.deleteLater()
        if self.thread is not None:
            self.thread.deleteLater()

        self.worker = None
        self.thread = None
