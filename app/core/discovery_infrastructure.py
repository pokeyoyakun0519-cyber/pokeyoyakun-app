from __future__ import annotations

import json
import os
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

from core.runtime_paths import app_root, bundled_root
from core.trusted_x_accounts import TrustedXAccountRegistry
from core.x_recent_search import x_api_execution_allowed


JST_OFFSET = "+09:00"
DISCOVERY_SOURCE_TYPES = {
    "OFFICIAL_X", "OFFICIAL_APP_ONLY", "OFFICIAL_LINE_ONLY", "IN_STORE_QR",
    "COMMERCIAL_FACILITY", "OFFICIAL_RELEASE_CALENDAR", "PRODUCT_REVERSE_SEARCH",
}
DISCOVERY_METHODS = {
    "SEARCH_ENGINE", "OFFICIAL_X", "COMMERCIAL_FACILITY", "COMPETITOR_REFERENCE",
    "PRODUCT_REVERSE_SEARCH", "OFFICIAL_APP", "OFFICIAL_LINE", "IN_STORE_QR",
}
MISS_REASONS = {
    "OFFICIAL_PAGE_NOT_DISCOVERED", "QUERY_GAP", "SOURCE_ADAPTER_GAP",
    "JAVASCRIPT_DEPENDENCY", "APP_ONLY", "LOGIN_WALL", "OFFICIAL_X_ONLY",
    "STORE_LEVEL_ANNOUNCEMENT", "EXTERNAL_APPLICATION_PLATFORM",
    "URL_PATTERN_CHANGED", "PARSER_FAILURE", "LIFECYCLE_MISCLASSIFICATION",
    "DEDUPE_FALSE_POSITIVE", "FEED_INGESTION_FAILURE", "SCHEDULING_GAP", "OTHER",
}
BASE_SOURCE_SCORES = {
    "OFFICIAL_RETAILER_APPLICATION_NOTICE": 100,
    "OFFICIAL_APPLICATION_PAGE": 95,
    "OFFICIAL_X": 90,
    "COMMERCIAL_FACILITY": 80,
    "OFFICIAL_EC_PAGE": 65,
    "OFFICIAL_APP_ONLY": 55,
    "OFFICIAL_LINE_ONLY": 55,
    "IN_STORE_QR": 40,
    "TIER_B_DISCOVERY": 20,
    "TIER_C_REFERENCE": 5,
}


class DiscoveryInfrastructure:
    """Build a server-side discovery plan without fetching restricted sources.

    Release dates only trigger searches. They never become application periods,
    and no candidate emitted by this layer is considered confirmed.
    """

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root is not None else app_root()

    @staticmethod
    def x_source_status(bearer_token: str | None = None) -> dict[str, Any]:
        configured = bool(
            (bearer_token if bearer_token is not None else os.environ.get(
                "POKEYOYA_X_BEARER_TOKEN", ""
            )).strip()
        )
        allowed = x_api_execution_allowed()
        return {
            "source_type": "OFFICIAL_X",
            "source_status": (
                "ENABLED_SERVER_SIDE" if configured and allowed
                else "DISABLED_CLIENT_RUNTIME" if not allowed
                else "DISABLED_NO_CREDENTIAL"
            ),
            "execution_scope": "ADMIN_SERVER_SIDE_ONLY",
            "web_scraping": False,
        }

    def official_x_accounts(self) -> list[dict[str, Any]]:
        return TrustedXAccountRegistry(self.root).load_with_observations()

    def sources(self) -> list[dict[str, Any]]:
        return list(self._load_json("phase10_discovery_sources.json").get("sources", []))

    def known_source_memory(self) -> list[dict[str, Any]]:
        payload = self._load_json("phase10_discovery_sources.json")
        return [dict(item) for item in payload.get("known_source_memory", [])]

    def classify_known_source_miss(self, source_id: str, reason: str) -> dict[str, Any]:
        if reason not in MISS_REASONS:
            reason = "OTHER"
        source = next(
            (item for item in self.known_source_memory() if item.get("source_id") == source_id),
            None,
        )
        known = source is not None
        return {
            "source_id": source_id,
            "reason": reason,
            "known_source": known,
            "event_type": "SECOND_MISS" if known else "FIRST_MISS",
            "severity": "HIGH" if known else "MEDIUM",
            "confirmed": False,
            "required_cycle": [
                "CLASSIFY", "IMPROVE_RULE", "REDISCOVER", "REGRESSION_TEST", "UPDATE_KNOWN_SOURCE",
            ],
        }

    def release_calendar(self) -> dict[str, Any]:
        return self._load_json("tcg_release_calendar.json")

    def evidence_submission_schema(self) -> dict[str, Any]:
        return self._load_json("evidence_submission.schema.json")

    def closed_source_candidate(
        self, source_id: str, extracted: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        source = next((item for item in self.sources() if item.get("id") == source_id), None)
        if source is None or source.get("source_type") not in {
            "OFFICIAL_APP_ONLY", "OFFICIAL_LINE_ONLY", "IN_STORE_QR",
        }:
            raise ValueError("App/LINE/店頭QR sourceが未登録です。")
        values = dict(extracted or {})
        return {
            "source_id": source_id,
            "source_type": source["source_type"],
            "app_name": str(source.get("app_name", "")),
            "line_account": str(source.get("line_account", "")),
            "how_discovered": source["how_discovered"],
            "product_text": str(values.get("product_text", "")),
            "store_text": str(values.get("store_text", "")),
            "missing_fields": list(values.get("missing_fields", [])),
            "verification_status": "candidate",
            "confirmed": False,
            "ui_hint": "公式アプリ限定" if source["source_type"] == "OFFICIAL_APP_ONLY" else (
                "公式LINE限定" if source["source_type"] == "OFFICIAL_LINE_ONLY" else "店頭QR限定"
            ),
        }

    @staticmethod
    def facility_to_store_candidate(article: dict[str, Any]) -> dict[str, Any]:
        required = ("facility_name", "store_name", "branch_name", "tcg", "product_text")
        missing = [field for field in required if not str(article.get(field, "")).strip()]
        return {
            "source_type": "COMMERCIAL_FACILITY",
            "how_discovered": "COMMERCIAL_FACILITY",
            "facility_name": str(article.get("facility_name", "")),
            "store_text": str(article.get("store_name", "")),
            "branch_text": str(article.get("branch_name", "")),
            "tcg": str(article.get("tcg", "")),
            "product_text": str(article.get("product_text", "")),
            "application_start_at": str(article.get("application_start_at", "")),
            "application_end_at": str(article.get("application_end_at", "")),
            "source_url": str(article.get("source_url", "")),
            "missing_fields": missing,
            "verification_status": "candidate",
            "confirmed": False,
        }

    def release_triggers(
        self, now: datetime, *, before_days: int = 30, after_days: int = 7,
    ) -> list[dict[str, Any]]:
        current = self._aware(now)
        output = []
        for tcg in self.release_calendar().get("tcgs", []):
            for product in tcg.get("products", []):
                release = datetime.fromisoformat(str(product["release_at"]))
                if release - timedelta(days=before_days) <= current <= release + timedelta(days=after_days):
                    output.append({
                        **product,
                        "tcg": tcg["tcg"],
                        "calendar_source_url": tcg["official_calendar_url"],
                        "trigger_reason": "PRODUCT_RELEASE_WINDOW",
                    })
        return output

    def product_first_queries(
        self, now: datetime, store_names: Iterable[str] = (),
    ) -> list[dict[str, str]]:
        queries: list[dict[str, str]] = []
        stores = [str(value).strip() for value in store_names if str(value).strip()]
        memory = self.known_source_memory()
        for product in self.release_triggers(now):
            name = str(product["product_name"])
            values = [f'"{name}" 抽選', f'"{name}" 予約', f'"{name}" LivePocket']
            values.extend(f'"{name}" "{store}"' for store in stores)
            for query in values:
                queries.append({
                    "tcg": str(product["tcg"]),
                    "product_name": name,
                    "query": query,
                    "how_discovered": "PRODUCT_REVERSE_SEARCH",
                    "verification_required": "true",
                })
            for source in memory:
                for template in source.get("discovery_queries", []):
                    query = str(template).replace("{product}", f'"{name}"')
                    queries.append({
                        "tcg": str(product["tcg"]), "product_name": name,
                        "query": query, "how_discovered": "KNOWN_SOURCE_REDISCOVERY",
                        "source_id": str(source.get("source_id", "")),
                        "verification_required": "true",
                    })
        output: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for item in queries:
            key = (item["product_name"], item["query"])
            if key not in seen:
                seen.add(key)
                output.append(item)
        return output

    def prioritized_backlog(
        self,
        candidates: Iterable[dict[str, Any]],
        effectiveness: dict[str, dict[str, Any]],
        now: datetime,
    ) -> list[dict[str, Any]]:
        current = self._aware(now)
        releases = self.release_triggers(current)
        release_names = [str(item.get("product_name", "")).casefold() for item in releases]
        output = []
        for raw in candidates:
            item = self.age_candidate(raw, current)
            source_type = str(item.get("source_type", ""))
            score = self.source_priority(source_type, effectiveness.get(source_type, {}))
            checked_products = " ".join(item.get("products_checked", [])).casefold()
            release_boost = any(
                name in checked_products or checked_products in name
                for name in release_names if name and checked_products
            )
            next_check = self._parse_time(item.get("next_check_at"))
            due = bool(next_check and next_check <= current)
            output.append({
                **item,
                "rediscovery_due": due,
                "release_window_priority": release_boost,
                "discovery_priority_score": score + (20 if release_boost else 0),
            })
        return sorted(
            output,
            key=lambda item: (
                not item["rediscovery_due"],
                -int(item["discovery_priority_score"]),
                str(item.get("next_check_at", "")),
            ),
        )

    @staticmethod
    def source_priority(
        source_type: str, effectiveness: dict[str, Any] | None = None,
    ) -> int:
        values = effectiveness or {}
        discovered = max(0, int(values.get("candidate_discovered_count", 0) or 0))
        confirmed = max(0, int(values.get("confirmed_promoted_count", 0) or 0))
        current = max(0, int(values.get("active_upcoming_count", 0) or 0))
        duplicate_rate = max(0.0, min(1.0, float(values.get("duplicate_rate", 0) or 0)))
        conversion = confirmed / discovered if discovered else 0.0
        return max(0, min(120, round(
            BASE_SOURCE_SCORES.get(str(source_type), 10)
            + conversion * 15 + min(current, 10) - duplicate_rate * 20
        )))

    @classmethod
    def age_candidate(
        cls, candidate: dict[str, Any], now: datetime, *, stale_after_days: int = 30,
    ) -> dict[str, Any]:
        output = dict(candidate)
        if output.get("status") in {"PROMOTED_CONFIRMED", "REJECTED"}:
            return output
        checked = cls._parse_time(output.get("last_checked_at"))
        if checked and cls._aware(now) - checked >= timedelta(days=stale_after_days):
            output["status"] = "STALE_CANDIDATE"
            output["stale_reason"] = "EVIDENCE_MISSING_OVER_LIMIT"
        return output

    @staticmethod
    def method_analytics(candidates: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        values: dict[str, Counter[str]] = {}
        for item in candidates:
            method = str(item.get("how_discovered") or "UNKNOWN")
            counter = values.setdefault(method, Counter())
            counter["candidates"] += 1
            if item.get("status") == "PROMOTED_CONFIRMED":
                counter["confirmed"] += 1
            if item.get("application_status") in {"ACTIVE", "UPCOMING"}:
                counter["active_upcoming"] += 1
        return {
            method: {
                "candidates": value["candidates"],
                "confirmed": value["confirmed"],
                "active_upcoming": value["active_upcoming"],
                "conversion_rate": round(value["confirmed"] / value["candidates"], 3),
            }
            for method, value in sorted(values.items())
        }

    def _load_json(self, filename: str) -> dict[str, Any]:
        candidates = (
            self.root / "app" / "resources" / filename,
            self.root / "resources" / filename,
            bundled_root() / "resources" / filename,
            bundled_root() / "app" / "resources" / filename,
        )
        path = next((value for value in candidates if value.is_file()), None)
        if path is None:
            return {}
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _aware(value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Discovery時刻にはtimezoneが必要です。")
        return value

    @staticmethod
    def _parse_time(value: Any) -> datetime | None:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else None
        except (TypeError, ValueError):
            return None
