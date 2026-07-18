from __future__ import annotations

import hashlib
import re
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

        for candidate in candidates:
            item = self._build_product(candidate, current, days)
            if not item:
                continue
            key = self.product_key(item)
            if key in existing or key in excluded:
                continue
            products.append(item)
            existing.add(key)
            added_items.append(item)

        if added_items:
            products.sort(key=lambda item: (str(item.get("release_date", "")), str(item.get("name", ""))))
            self.store._save_product_file(products)
        return {"added": len(added_items), "skipped": len(candidates) - len(added_items), "products": added_items}

    @classmethod
    def product_key(cls, item: dict[str, Any]) -> str:
        tcg = normalize_key(item.get("tcg_key"), item.get("tcg"))[0]
        name = re.sub(r"[\s「」『』・･_\-&＆]", "", str(item.get("name", ""))).casefold()
        return f"{tcg}|{name}|{str(item.get('release_date', ''))}"

    def _build_product(
        self, candidate: dict[str, Any], current: date, days: int
    ) -> dict[str, Any] | None:
        name = str(candidate.get("name", "")).strip()
        if not name or any(word in name.casefold() for word in self.EXCLUDED_WORDS):
            return None
        try:
            release = datetime.strptime(str(candidate.get("release_date", "")), "%Y-%m-%d").date()
        except ValueError:
            return None
        until = (release - current).days
        if until < 0 or until > days:
            return None
        tcg = normalize_key(candidate.get("tcg_key"), candidate.get("tcg"))[0]
        url = str(candidate.get("official_url") or candidate.get("source_url") or "").strip()
        parsed = urlsplit(url)
        if url and (parsed.scheme != "https" or not parsed.hostname):
            return None
        kind = str(candidate.get("product_kind", "その他"))
        if any(word in kind.casefold() for word in self.EXCLUDED_WORDS):
            return None
        digest = hashlib.sha256(self.product_key(candidate).encode("utf-8")).hexdigest()[:20]
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
        }
