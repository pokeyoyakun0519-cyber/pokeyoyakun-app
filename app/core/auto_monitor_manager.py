from __future__ import annotations

import hashlib
import re
from collections import Counter
from datetime import date, datetime
from typing import Any
from urllib.parse import urlsplit

from core.config_manager import ConfigManager
from core.product_master import ProductMasterManager
from core.product_store import ProductStore
from core.tcg_categories import display_name, normalize_key
from core.monitoring_scope import enabled_tcg_keys


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
        enabled_games = enabled_tcg_keys(config)
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
        added_items: list[dict[str, Any]] = []
        updated_items: list[dict[str, Any]] = []
        reasons_by_tcg: dict[str, Counter] = {}
        master = ProductMasterManager(self.store.root)
        master.last_conflicts = []

        for candidate in candidates:
            tcg = normalize_key(candidate.get("tcg_key"), candidate.get("tcg"))[0]
            reasons = reasons_by_tcg.setdefault(tcg, Counter())
            if tcg not in enabled_games:
                reasons["disabled_tcg"] += 1
                continue
            item, reason = self.classify_candidate(candidate, current, days)
            if not item:
                reasons[reason] += 1
                continue
            if self.is_user_excluded(item, excluded):
                reasons["user_excluded"] += 1
                continue
            match_index, match_method = master.find_match(products, item)
            if match_index is not None:
                merged, changes = master.reconcile_product(
                    products[match_index], item
                )
                products[match_index] = merged
                if "release_date" in changes:
                    updated_items.append(merged)
                    reasons["release_date_updated"] += 1
                elif changes:
                    updated_items.append(merged)
                    reasons["metadata_updated"] += 1
                else:
                    reasons["already_saved"] += 1
                continue
            if match_method.startswith("ambiguous_"):
                reasons["ambiguous_product"] += 1
            products.append(item)
            added_items.append(item)
            reasons["added"] += 1

        if added_items or updated_items:
            products.sort(key=lambda item: (str(item.get("release_date", "")), str(item.get("name", ""))))
            self.store._save_product_file(products)
        master.log_conflicts()
        return {
            "added": len(added_items),
            "updated": len(updated_items),
            "skipped": len(candidates) - len(added_items) - len(updated_items),
            "products": added_items,
            "updated_products": updated_items,
            "days": days,
            "reasons_by_tcg": {
                key: dict(value) for key, value in reasons_by_tcg.items()
            },
            "release_date_conflicts": list(master.last_conflicts),
        }

    @classmethod
    def product_key(cls, item: dict[str, Any]) -> str:
        return ProductMasterManager.identity_key(item)

    @classmethod
    def legacy_product_key(cls, item: dict[str, Any]) -> str:
        tcg = normalize_key(item.get("tcg_key"), item.get("tcg"))[0]
        name = re.sub(
            r"[\s「」『』・･_\-&＆]",
            "",
            str(item.get("name", "")),
        ).casefold()
        return f"{tcg}|{name}|{str(item.get('release_date', ''))}"

    @classmethod
    def is_user_excluded(
        cls,
        item: dict[str, Any],
        excluded: set[str],
    ) -> bool:
        stable = cls.product_key(item)
        legacy = cls.legacy_product_key(item)
        if stable in excluded or legacy in excluded:
            return True
        legacy_prefix = legacy.rsplit("|", 1)[0] + "|"
        return any(str(value).startswith(legacy_prefix) for value in excluded)

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
        has_application = bool(
            str(candidate.get("application_url", "")).strip()
            and str(candidate.get("application_end_at", "")).strip()
        )
        if until > days and not has_application:
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
        sites = []
        if has_application:
            sites.append({
                "site_key": "pokemon_official_application",
                "name": "ポケモンセンターオンライン",
                "status": str(candidate.get("application_status", "抽選受付")),
                "url": str(candidate.get("application_url", "")),
                "application_url": str(candidate.get("application_url", "")),
                "application_start_at": str(candidate.get("application_start_at", "")),
                "application_end_at": str(candidate.get("application_end_at", "")),
                "application_method": str(candidate.get("application_method", "Web抽選")),
                "application_status": str(candidate.get("application_status", "抽選受付")),
            })
        return {
            "id": f"auto_{digest}",
            "tcg_key": tcg,
            "tcg": display_name(tcg),
            "name": name,
            "release_date": release.isoformat(),
            "product_kind": kind,
            "product_code": str(candidate.get("product_code", "")),
            "jan_code": str(
                candidate.get("jan_code") or candidate.get("jan") or ""
            ),
            "official_product_id": str(
                candidate.get("official_product_id")
                or candidate.get("official_id")
                or ""
            ),
            "manufacturer": str(
                candidate.get("manufacturer")
                or candidate.get("maker")
                or candidate.get("brand")
                or ""
            ),
            "official_url": url,
            "source_name": str(candidate.get("source_name", "公式情報ソース")),
            "source_type": "auto_monitor",
            "auto_monitored": True,
            "auto_added_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "status": "自動監視中",
            "sites": sites,
        }, "eligible"
