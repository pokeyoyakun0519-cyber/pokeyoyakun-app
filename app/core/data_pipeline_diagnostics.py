from __future__ import annotations

import json
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

from core.auto_monitor_manager import AutoMonitorManager
from core.config_manager import ConfigManager
from core.tcg_categories import categories, normalize_key


class DataPipelineDiagnostics:
    """公式取得からUI表示までのTCG別件数を副作用なしで集計する。"""

    def __init__(self, root: Path):
        self.root = Path(root)

    def build(
        self,
        *,
        visible_products: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        sources = self._load_list(self.root / "config" / "sources.json")
        candidates = self._load_list(self.root / "data" / "candidates.json")
        products = self._load_list(self.root / "data" / "products.json")
        visible = visible_products if visible_products is not None else products
        days = self._monitor_days()
        current = date.today()
        result = {item.key: self._empty_bucket() for item in categories()}

        for source in sources:
            key = normalize_key(source.get("tcg_key"), source.get("tcg"))[0]
            bucket = result.setdefault(key, self._empty_bucket())
            bucket["official_sources"] += 1
            bucket["official_acquired"] += int(
                source.get("last_detected_count", 0) or 0
            )
            check_state = str(source.get("check_state", ""))
            if check_state == "checked":
                bucket["official_checked"] += 1
            else:
                bucket["official_incomplete"] += 1
            if check_state == "error":
                bucket["official_failed"] += 1

        exclusion_counters: dict[str, Counter] = {}
        for candidate in candidates:
            key = normalize_key(
                candidate.get("tcg_key"), candidate.get("tcg")
            )[0]
            bucket = result.setdefault(key, self._empty_bucket())
            bucket["candidate_saved"] += 1
            retail_hits = candidate.get("retail_hits", [])
            bucket["shop_acquired"] += (
                len(retail_hits) if isinstance(retail_hits, list) else 0
            )
            _product, reason = AutoMonitorManager.classify_candidate(
                candidate, current, days
            )
            if reason == "eligible":
                bucket["promotion_eligible"] += 1
            else:
                exclusion_counters.setdefault(key, Counter())[reason] += 1

        for product in products:
            key = normalize_key(product.get("tcg_key"), product.get("tcg"))[0]
            bucket = result.setdefault(key, self._empty_bucket())
            bucket["product_saved"] += 1
            sites = product.get("sites", [])
            bucket["site_saved"] += len(sites) if isinstance(sites, list) else 0

        for product in visible:
            key = normalize_key(product.get("tcg_key"), product.get("tcg"))[0]
            result.setdefault(key, self._empty_bucket())["product_displayed"] += 1

        for key, counter in exclusion_counters.items():
            result[key]["promotion_excluded"] = dict(counter)

        return {
            "storage": {
                "products": str(self.root / "data" / "products.json"),
                "candidates": str(self.root / "data" / "candidates.json"),
                "sources": str(self.root / "config" / "sources.json"),
            },
            "monitor_days": days,
            "by_tcg": result,
        }

    @staticmethod
    def format_lines(snapshot: dict[str, Any]) -> list[str]:
        lines = [
            "TCG pipeline storage: "
            + " ".join(
                f"{key}={value}"
                for key, value in snapshot.get("storage", {}).items()
            ),
            f'TCG pipeline promotion window: {snapshot.get("monitor_days", 30)} days',
        ]
        for item in categories():
            values = snapshot.get("by_tcg", {}).get(item.key, {})
            exclusions = values.get("promotion_excluded", {})
            exclusion_text = (
                ",".join(
                    f"{key}:{value}" for key, value in sorted(exclusions.items())
                )
                or "none"
            )
            lines.append(
                f"TCG pipeline {item.key}: "
                f'official={values.get("official_acquired", 0)} '
                f'official_sources={values.get("official_sources", 0)} '
                f'official_checked={values.get("official_checked", 0)} '
                f'official_incomplete={values.get("official_incomplete", 0)} '
                f'official_failed={values.get("official_failed", 0)} '
                f'candidates={values.get("candidate_saved", 0)} '
                f'shop_hits={values.get("shop_acquired", 0)} '
                f'saved_products={values.get("product_saved", 0)} '
                f'saved_sites={values.get("site_saved", 0)} '
                f'displayed={values.get("product_displayed", 0)} '
                f'promotion_eligible={values.get("promotion_eligible", 0)} '
                f"promotion_excluded={exclusion_text}"
            )
        return lines

    def _monitor_days(self) -> int:
        try:
            value = int(
                ConfigManager(self.root).load().get("general", {}).get(
                    "auto_monitor_days_before", 30
                )
            )
        except (TypeError, ValueError):
            return 30
        return value if value in AutoMonitorManager.VALID_DAYS else 30

    @staticmethod
    def _load_list(path: Path) -> list[dict[str, Any]]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, dict)]

    @staticmethod
    def _empty_bucket() -> dict[str, Any]:
        return {
            "official_sources": 0,
            "official_checked": 0,
            "official_incomplete": 0,
            "official_acquired": 0,
            "official_failed": 0,
            "candidate_saved": 0,
            "shop_acquired": 0,
            "product_saved": 0,
            "site_saved": 0,
            "product_displayed": 0,
            "promotion_eligible": 0,
            "promotion_excluded": {},
        }
