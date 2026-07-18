from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from typing import Any

from core.activity_timeline import ActivityTimeline
from core.application_status import JST, evaluate_application_period
from core.favorites_manager import FavoritesManager
from core.notification_store import NotificationStore
from core.product_store import ProductStore
from core.scheduler_config import SchedulerConfig
from core.site_master_manager import SiteMasterManager
from core.source_manager import SourceManager


EVENT_ICONS = {
    "応募開始": "▶", "応募締切": "⏰", "結果発表": "✓", "発売日": "◆",
    "予約開始": "▣", "店頭受取期限": "⌂", "支払期限": "¥", "新店舗追加": "＋",
}


def parse_datetime(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=JST)
    except ValueError:
        pass
    for pattern in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
        try:
            return datetime.strptime(text[:10], pattern).replace(tzinfo=JST)
        except ValueError:
            continue
    return None


def is_new(value: object, *, now: datetime | None = None, days: int = 7) -> bool:
    parsed = parse_datetime(value)
    current = now or datetime.now(JST)
    return bool(parsed and timedelta(0) <= current - parsed <= timedelta(days=days))


def product_priority(product: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    current = now or datetime.now(JST)
    for site in product.get("sites", []):
        period = evaluate_application_period(site, now=current)
        if not site.get("applied") and period.get("period_status") == "本日締切":
            return {"level": 5, "stars": "★★★★★", "label": "本日締切"}
    if any(not site.get("applied") and evaluate_application_period(site, now=current).get("period_status") == "受付中" for site in product.get("sites", [])):
        return {"level": 4, "stars": "★★★★☆", "label": "応募中"}
    release = parse_datetime(product.get("release_date"))
    if release and current <= release <= current + timedelta(days=30):
        return {"level": 3, "stars": "★★★☆☆", "label": "発売30日前"}
    if release and release > current:
        return {"level": 2, "stars": "★★☆☆☆", "label": "発売予定"}
    return {"level": 1, "stars": "★☆☆☆☆", "label": "発売済み"}


class CalendarService:
    def build_events(self, products: list[dict[str, Any]], sites: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        fields = (
            ("application_start_at", "応募開始"), ("application_end_at", "応募締切"),
            ("result_announcement_at", "結果発表"), ("reservation_start_at", "予約開始"),
            ("pickup_deadline_at", "店頭受取期限"), ("payment_deadline_at", "支払期限"),
        )
        for product in products:
            self._append(events, product.get("release_date"), "発売日", product, None)
            for site in product.get("sites", []):
                for key, event_type in fields:
                    value = site.get(key)
                    if not value and key == "result_announcement_at":
                        value = site.get("result_date")
                    self._append(events, value, event_type, product, site)
        for site in sites or []:
            if is_new(site.get("created_at")):
                self._append(events, site.get("created_at"), "新店舗追加", {}, site)
        return sorted(events, key=lambda event: (event["starts_at"], event["event_type"], event["title"]))

    @staticmethod
    def _append(events: list[dict[str, Any]], value: object, event_type: str, product: dict[str, Any], site: dict[str, Any] | None) -> None:
        starts = parse_datetime(value)
        if starts is None:
            return
        site = site or {}
        events.append({
            "event_type": event_type, "icon": EVENT_ICONS[event_type], "starts_at": starts.isoformat(),
            "date": starts.date().isoformat(), "title": str(product.get("canonical_name") or product.get("name") or site.get("name") or "名称未設定"),
            "product_id": str(product.get("product_id", product.get("id", ""))),
            "site_id": str(site.get("site_key", site.get("id", ""))), "site_name": str(site.get("name", "")),
            "product_url": str(product.get("official_url", "")),
            "application_url": str(site.get("application_url", site.get("url", ""))),
        })


class ApplicationStatistics:
    def build(self, products: list[dict[str, Any]]) -> dict[str, Any]:
        rows = []
        for product in products:
            for site in product.get("sites", []):
                if not site.get("applied") and site.get("result_status", "未確認") == "未確認":
                    continue
                result = str(site.get("result_status", "未確認"))
                rows.append({
                    "result": result, "store": str(site.get("name", "店舗未設定")),
                    "tcg": str(product.get("tcg_key", "other")),
                    "product": str(product.get("canonical_name", product.get("name", "商品未設定"))),
                    "month": str(site.get("applied_at", ""))[:7] or "不明",
                })
        wins = sum(row["result"] == "当選" for row in rows)
        losses = sum(row["result"] == "落選" for row in rows)
        waiting = len(rows) - wins - losses
        decided = wins + losses
        return {
            "total": len(rows), "wins": wins, "losses": losses, "waiting": waiting,
            "win_rate": (wins / decided * 100) if decided else None,
            "reference": decided < 10,
            "by_store": self._counts(rows, "store"), "by_tcg": self._counts(rows, "tcg"),
            "by_product": self._counts(rows, "product"), "by_month": self._counts(rows, "month"),
        }

    @staticmethod
    def _counts(rows: list[dict[str, str]], key: str) -> list[dict[str, Any]]:
        grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in rows:
            grouped[row[key]].append(row)
        output = []
        for label, values in grouped.items():
            wins = sum(value["result"] == "当選" for value in values)
            losses = sum(value["result"] == "落選" for value in values)
            output.append({"label": label, "total": len(values), "wins": wins, "losses": losses})
        return sorted(output, key=lambda item: (-item["total"], item["label"]))


class HomeDashboardService:
    def __init__(self, root=None):
        self.store = ProductStore(root)
        self.root = self.store.root
        self.site_manager = SiteMasterManager(root)
        self.favorites = FavoritesManager(root)
        self.timeline = ActivityTimeline(root)

    def build(self, *, now: datetime | None = None) -> dict[str, Any]:
        current = now or datetime.now(JST)
        products = self.store.load_products()
        sites = self.site_manager.load_sites()
        events = CalendarService().build_events(products, sites)
        notifications = NotificationStore(self.store.root).load()
        sources = self._load_sources()
        scheduler = self._load_scheduler()
        actions = self._actions(products, sites, notifications, current)
        states = Counter(
            str(site.get("application_state", "未応募"))
            for product in products for site in product.get("sites", [])
        )
        monitor_errors = sum(
            str(source.get("check_state", "")) == "error" for source in sources
        ) + sum(str(item.get("category", "")) == "エラー" and not item.get("read") for item in notifications)
        favorites = self.favorites.load()
        favorite_products = [product for product in products if str(product.get("product_id", product.get("id", ""))) in favorites["products"]]
        favorite_stores = [site for site in sites if str(site.get("id", "")) in favorites["stores"]]
        new_products = sorted(
            (product for product in products if is_new(product.get("created_at"), now=current)),
            key=lambda product: str(product.get("created_at", "")),
            reverse=True,
        )
        enabled_sites = [site for site in sites if site.get("enabled") and site.get("active", True)]
        return {
            "actions": actions, "events": events,
            "metrics": {
                "today_deadlines": sum(action["kind"] == "today_deadline" for action in actions),
                "open_applications": states["未応募"], "waiting_results": states["抽選受付完了"] + states["抽選結果確認"],
                "new_products": sum(is_new(product.get("created_at"), now=current) for product in products),
                "new_stores": sum(is_new(site.get("created_at"), now=current) for site in sites),
                "monitored_stores": len(enabled_sites), "monitor_errors": monitor_errors,
                "sources": len(sources), "source_errors": sum(str(source.get("check_state")) == "error" for source in sources),
                "notifications": sum(not item.get("read") for item in notifications),
            },
            "monitoring": {
                "stores": len(enabled_sites),
                "reservations": sum("予約" in str(site.get("status", "")) for product in products for site in product.get("sites", [])),
                "lotteries": sum("抽選" in str(site.get("status", "")) for product in products for site in product.get("sites", [])),
                "errors": monitor_errors, "last_updated": str(scheduler.get("last_run", "")),
            },
            "favorite_products": favorite_products[:6], "favorite_stores": favorite_stores[:6],
            "notifications": notifications[:5], "new_products": new_products[:6],
            "timeline": self.timeline.load(),
        }

    def _load_sources(self):
        if self.root == ProductStore().root:
            return SourceManager().load_sources()
        path = self.root / "config" / "sources.json"
        try:
            import json
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        return data if isinstance(data, list) else []

    def _load_scheduler(self):
        if self.root == ProductStore().root:
            return SchedulerConfig().load()
        path = self.root / "config" / "scheduler_settings.json"
        try:
            import json
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _actions(self, products, sites, notifications, now):
        actions = []
        today = now.date()
        for product in products:
            product_id = str(product.get("product_id", product.get("id", "")))
            release = parse_datetime(product.get("release_date"))
            if release and today <= release.date() <= today + timedelta(days=7):
                actions.append(self._action(5, "release", f"発売まで{(release.date()-today).days}日", product.get("canonical_name", product.get("name", "商品")), product_id=product_id))
            for site in product.get("sites", []):
                end = parse_datetime(site.get("application_end_at"))
                result = parse_datetime(site.get("result_announcement_at") or site.get("result_date"))
                start = parse_datetime(site.get("application_start_at"))
                if not site.get("applied") and end and now <= end:
                    remaining = end - now
                    if end.date() == today:
                        actions.append(self._action(1, "today_deadline", f"あと{max(0, int(remaining.total_seconds()//3600))}時間", f'{site.get("name", "店舗")}応募締切', product_id, site))
                    elif remaining <= timedelta(hours=24):
                        actions.append(self._action(2, "within_24h", "24時間以内", f'{site.get("name", "店舗")}応募締切', product_id, site))
                elif site.get("applied") and end and end.date() == today:
                    completed = self._action(1, "today_deadline", "完了", f'{site.get("name", "店舗")}応募済み', product_id, site)
                    completed["completed"] = True
                    actions.append(completed)
                if result and result.date() == today:
                    actions.append(self._action(3, "result", "結果発表", str(site.get("name", "店舗")), product_id, site))
                if start and start.date() == today:
                    actions.append(self._action(4, "start", "本日受付開始", str(site.get("name", "店舗")), product_id, site))
        for site in sites:
            if is_new(site.get("created_at"), now=now):
                actions.append(self._action(6, "new_store", "新店舗", str(site.get("name", "店舗")), store_id=str(site.get("id", ""))))
        for item in notifications:
            if item.get("read"):
                continue
            category = str(item.get("category", ""))
            if category == "応募情報変更":
                actions.append(self._action(7, "change", "情報変更", str(item.get("title", "応募情報変更"))))
            elif category == "エラー":
                actions.append(self._action(8, "error", "監視エラー", str(item.get("message", "確認が必要です"))))
        return sorted(actions, key=lambda item: (item["priority"], item["title"]))

    @staticmethod
    def _action(priority, kind, lead, title, product_id="", site=None, store_id=""):
        site = site or {}
        return {
            "priority": priority, "kind": kind, "lead": lead, "title": title,
            "product_id": product_id, "store_id": store_id or str(site.get("site_key", "")),
            "url": str(site.get("application_url", site.get("url", ""))),
            "completed": bool(site.get("applied")) or str(site.get("result_status", "")) in {"当選", "落選"},
        }
