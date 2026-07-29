from __future__ import annotations

import hashlib
import re
from collections import Counter
from datetime import date, datetime
from typing import Any
from urllib.parse import urlsplit

from core.config_manager import ConfigManager
from core.product_store import ProductStore
from core.tcg_categories import display_name, normalize_key


class AutoMonitorManager:
    VALID_DAYS = {7, 14, 30, 60}
    EXCLUDED_WORDS = (
        "イベント", "ルール", "カードリスト", "スリーブ", "プレイマット",
        "デッキケース", "アクセサリー", "event", "rule", "cardlist",
        "sleeve", "playmat", "海外版", "英語版",
    )

    def __init__(
        self,
        config_manager: ConfigManager | None = None,
        product_store: ProductStore | None = None,
    ) -> None:
        self.config_manager = config_manager or ConfigManager()
        self.store = product_store or ProductStore()

    def add_due_candidates(
        self, candidates: list[dict[str, Any]], *, today: date | None = None
    ) -> dict[str, Any]:
        config = self.config_manager.load()
        general = config.get("general", {})
        if not bool(general.get("auto_monitor_new_releases", True)):
            return {"added": 0, "skipped": len(candidates), "products": []}
        days = int(general.get("auto_monitor_days_before", 30) or 30)
        if days not in self.VALID_DAYS:
            days = 30
        current = today or date.today()
        products = self.store._load_product_file()
        state = self.store._load_user_state()
        excluded = set(state.get("auto_monitor_excluded_keys", []))
        existing = {self.product_key(item) for item in products}
        added_items: list[dict[str, Any]] = []
        reasons_by_tcg: dict[str, Counter] = {}

        for candidate in candidates:
            tcg = normalize_key(candidate.get("tcg_key"), candidate.get("tcg"))[0]
            reasons = reasons_by_tcg.setdefault(tcg, Counter())
            item, reason = self.classify_candidate(candidate, current, days)
            if not item:
                reasons[reason] += 1
                continue
            key = self.product_key(item)
            if key in existing:
                reasons["already_saved"] += 1
                continue
            if key in excluded:
                reasons["user_excluded"] += 1
                continue
            products.append(item)
            existing.add(key)
            added_items.append(item)
            reasons["added"] += 1

        if added_items:
            products.sort(key=lambda item: (str(item.get("release_date", "")), str(item.get("name", ""))))
            self.store._save_product_file(products)
        return {
            "added": len(added_items),
            "skipped": len(candidates) - len(added_items),
            "products": added_items,
            "days": days,
            "reasons_by_tcg": {
                key: dict(value) for key, value in reasons_by_tcg.items()
            },
        }

    @classmethod
    def product_key(cls, item: dict[str, Any]) -> str:
        tcg = normalize_key(item.get("tcg_key"), item.get("tcg"))[0]
        name = re.sub(r"[\s「」『』・･_\-&＆]", "", str(item.get("name", ""))).casefold()
        return f"{tcg}|{name}|{str(item.get('release_date', ''))}"

    def _build_product(
        self, candidate: dict[str, Any], current: date, days: int
    ) -> dict[str, Any] | None:
        return self.classify_candidate(candidate, current, days)[0]

    @classmethod
    def classify_candidate(
        cls, candidate: dict[str, Any], current: date, days: int
    ) -> tuple[dict[str, Any] | None, str]:
        name = str(candidate.get("name", "")).strip()
        if not name:
            return None, "missing_name"
        if any(word in name.casefold() for word in cls.EXCLUDED_WORDS):
            return None, "excluded_name"
        try:
            release = datetime.strptime(str(candidate.get("release_date", "")), "%Y-%m-%d").date()
        except ValueError:
            return None, "invalid_release_date"
        until = (release - current).days
        if until < 0:
            return None, "already_released"
        if until > days:
            return None, "beyond_monitor_window"
        tcg = normalize_key(candidate.get("tcg_key"), candidate.get("tcg"))[0]
        url = str(candidate.get("official_url") or candidate.get("source_url") or "").strip()
        parsed = urlsplit(url)
        if url and (parsed.scheme != "https" or not parsed.hostname):
            return None, "unsafe_official_url"
        kind = str(candidate.get("product_kind", "その他"))
        if any(word in kind.casefold() for word in cls.EXCLUDED_WORDS):
            return None, "excluded_product_kind"
        digest = hashlib.sha256(cls.product_key(candidate).encode("utf-8")).hexdigest()[:20]
        return {
            "id": f"auto_{digest}",
            "tcg_key": tcg,
            "tcg": display_name(tcg),
            "name": name,
            "release_date": release.isoformat(),
            "product_kind": kind,
            "official_url": url,
            "source_name": str(candidate.get("source_name", "公式情報ソース")),
            "source_type": "auto_monitor",
            "auto_monitored": True,
            "auto_added_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "status": "自動監視中",
            "sites": [],
        }, "eligible"
