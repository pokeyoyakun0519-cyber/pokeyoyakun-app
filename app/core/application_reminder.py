from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from core.application_period import ApplicationPeriodParser
from core.application_status import JST, evaluate_application_period, parse_jst_datetime
from core.config_manager import ConfigManager
from core.product_store import ProductStore
from core.runtime_paths import app_root
from core.tcg_categories import display_name, normalize_key


class ApplicationDeadlineReminder:
    """締切前の未応募案件を、設定済み時刻ごとに一度だけ通知する。"""

    FINAL_RESULTS = {"当選", "落選", "予約完了", "注文受付", "キャンセル"}

    def __init__(
        self,
        store: ProductStore | None = None,
        config_manager: ConfigManager | None = None,
        root: Path | None = None,
    ):
        self.store = store or ProductStore(root)
        self.config_manager = config_manager or ConfigManager(root)
        base = Path(root) if root is not None else getattr(self.store, "root", app_root())
        self.history_path = base / "data" / "application_reminder_history.json"

    def collect_due(self, *, now: datetime | None = None) -> list[dict[str, Any]]:
        current = self._as_jst(now or datetime.now(JST))
        assistant = self.config_manager.load().get("application_assistant", {})
        if not assistant.get("deadline_reminders_enabled", True):
            return []
        offsets = sorted(
            {
                int(item.get("minutes", 0))
                for item in assistant.get("reminders", [])
                if item.get("enabled", False) and int(item.get("minutes", 0)) > 0
            }
        )
        if not offsets:
            return []
        sent = set(self._load_history().get("sent_keys", []))
        due = []
        for product in self.store.load_products():
            for raw_site in product.get("sites", []):
                site = ApplicationPeriodParser().enrich_site(
                    dict(raw_site),
                    "\n".join(str(raw_site.get(key, "")) for key in (
                        "application_period", "order_period", "result_date", "notice", "text",
                    ) if raw_site.get(key)),
                    now=current,
                    release_date=str(product.get("release_date", "")),
                )
                verification = str(
                    site.get(
                        "verification_status",
                        product.get("verification_status", "confirmed"),
                    )
                ).strip().casefold()
                if verification in {"candidate", "pending", "confirming", "確認中", "rejected"}:
                    continue
                if site.get("confirmed") is False or product.get("confirmed") is False:
                    continue
                if str(site.get("application_state", "未応募")) != "未応募":
                    continue
                if str(site.get("result_status", "未確認")) in self.FINAL_RESULTS:
                    continue
                period = evaluate_application_period(site, now=current)
                if period["period_ended"] or period["period_status"] not in {"受付中", "本日締切"}:
                    continue
                end = parse_jst_datetime(site.get("application_end_at"))
                if end is None or end <= current:
                    continue
                remaining_minutes = max(1, int((end - current).total_seconds() // 60))
                eligible = [offset for offset in offsets if remaining_minutes <= offset]
                if not eligible:
                    continue
                offset = min(eligible)
                key = self._history_key(product, site, end, offset)
                if key in sent:
                    continue
                tcg_key = normalize_key(product.get("tcg_key"), product.get("tcg"))[0]
                due.append({
                    "history_key": key,
                    "offset_minutes": offset,
                    "tcg_key": tcg_key,
                    "tcg": display_name(tcg_key),
                    "product_id": str(product.get("id", "")),
                    "product_name": str(product.get("name", "商品名未設定")),
                    "site_key": str(site.get("site_key", "")),
                    "site_name": str(site.get("name", "店舗名未設定")),
                    "application_end_at": end.isoformat(),
                    "remaining_text": self._remaining_text(end - current),
                    "application_url": str(site.get("application_url", site.get("url", ""))),
                })
        return sorted(due, key=lambda item: item["application_end_at"])

    def run(self, dispatch: Callable[[dict[str, Any]], Any], *, now: datetime | None = None) -> list[dict[str, Any]]:
        sent_items = []
        for reminder in self.collect_due(now=now):
            if dispatch(reminder) is False:
                continue
            self.mark_sent(reminder)
            sent_items.append(reminder)
        return sent_items

    def mark_sent(self, reminder: dict[str, Any]) -> None:
        state = self._load_history()
        key = str(reminder["history_key"])
        if key in state["sent_keys"]:
            return
        state["sent_keys"].append(key)
        state["history"].insert(0, {
            **reminder,
            "notified_at": datetime.now(JST).isoformat(timespec="seconds"),
        })
        state["sent_keys"] = state["sent_keys"][-5000:]
        state["history"] = state["history"][:1000]
        self._save_history(state)

    @staticmethod
    def _history_key(product: dict[str, Any], site: dict[str, Any], end: datetime, offset: int) -> str:
        source = "|".join((
            str(product.get("id", "")), str(site.get("site_key", "")),
            str(site.get("url", site.get("application_url", ""))), end.isoformat(), str(offset),
        ))
        return hashlib.sha256(source.encode("utf-8")).hexdigest()

    @staticmethod
    def _remaining_text(remaining: timedelta) -> str:
        minutes = max(1, int(remaining.total_seconds() // 60))
        if minutes >= 1440:
            return f"約{minutes // 1440}日"
        if minutes >= 60:
            return f"約{minutes // 60}時間{minutes % 60}分"
        return f"約{minutes}分"

    @staticmethod
    def _as_jst(value: datetime) -> datetime:
        return value.replace(tzinfo=JST) if value.tzinfo is None else value.astimezone(JST)

    def _load_history(self) -> dict[str, Any]:
        if not self.history_path.exists():
            return {"sent_keys": [], "history": []}
        try:
            data = json.loads(self.history_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"sent_keys": [], "history": []}
        return data if isinstance(data, dict) else {"sent_keys": [], "history": []}

    def _save_history(self, state: dict[str, Any]) -> None:
        self.history_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.history_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.history_path)
