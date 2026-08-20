from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from typing import Any

from core.application_status import JST, parse_jst_datetime
from core.config_manager import ConfigManager
from core.product_categories import normalize_product_category
from core.tcg_categories import normalize_key


class ApplicationNotificationService:
    """Build notification events from saved confirmed applications only."""

    FINAL_RESULTS = {"当選", "落選", "予約完了", "注文受付", "キャンセル"}
    BLOCKED_VERIFICATION = {"candidate", "pending", "confirming", "確認中", "rejected"}
    RECENT_WINDOW = timedelta(hours=48)

    def __init__(self, config_manager: ConfigManager | None = None):
        self.config_manager = config_manager or ConfigManager()

    def collect(
        self,
        products: list[dict[str, Any]],
        *,
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        current = self._as_jst(now or datetime.now(JST))
        settings = self.config_manager.load().get("notification", {})
        if not settings.get("application_events_enabled", True):
            return []
        events: list[dict[str, Any]] = []
        for product in products:
            category = normalize_product_category(product)
            tcg_key = normalize_key(product.get("tcg_key"), product.get("tcg"))[0]
            for site in product.get("sites", []):
                if not isinstance(site, dict) or not self._confirmed(product, site):
                    continue
                if self._suppressed(site, settings):
                    continue
                sales_mode = self._sales_mode(site)
                prefecture = str(site.get("prefecture", "")).strip() or "UNKNOWN"
                if not self._matches(settings, tcg_key, sales_mode, prefecture, category):
                    continue
                detected_at = self._event_time(product, site)
                if detected_at is None or current - detected_at > self.RECENT_WINDOW:
                    continue
                event_type = self._event_type(site)
                application_id = self._application_id(product, site)
                source_event_id = str(
                    site.get("source_event_id") or site.get("x_post_id") or site.get("id") or ""
                )
                dedupe_key = self._dedupe_key(
                    application_id,
                    event_type,
                    source_event_id,
                    str(site.get("application_end_at", "")),
                )
                events.append(
                    {
                        "application_id": application_id,
                        "event_type": event_type,
                        "dedupe_key": dedupe_key,
                        "product_name": str(product.get("name", "商品名未設定")),
                        "product_category": category,
                        "tcg_key": tcg_key,
                        "site_name": str(site.get("name", "店舗名未設定")),
                        "sales_mode": sales_mode,
                        "prefecture": prefecture,
                        "application_url": str(site.get("application_url") or site.get("url") or ""),
                        "detected_at": detected_at.isoformat(),
                    }
                )
        return events

    @classmethod
    def _confirmed(cls, product: dict[str, Any], site: dict[str, Any]) -> bool:
        verification = str(
            site.get("verification_status", product.get("verification_status", "confirmed"))
        ).strip().casefold()
        if verification in cls.BLOCKED_VERIFICATION:
            return False
        return site.get("confirmed") is not False and product.get("confirmed") is not False

    @classmethod
    def _suppressed(cls, site: dict[str, Any], settings: dict[str, Any]) -> bool:
        if str(site.get("result_status", "未確認")) in cls.FINAL_RESULTS:
            return True
        if str(site.get("application_state", "未応募")) != "未応募" and settings.get(
            "suppress_after_applied", True
        ):
            return True
        return False

    @staticmethod
    def _matches(
        settings: dict[str, Any],
        tcg_key: str,
        sales_mode: str,
        prefecture: str,
        category: str,
    ) -> bool:
        tcg_settings = settings.get("tcg", {})
        if isinstance(tcg_settings, dict) and not tcg_settings.get(tcg_key, True):
            return False
        sales_modes = settings.get("sales_modes", [])
        if sales_modes and sales_mode not in sales_modes:
            return False
        prefectures = settings.get("prefectures", [])
        if prefectures and prefecture not in prefectures:
            return False
        categories = settings.get("product_categories", [])
        return not categories or category in categories

    @staticmethod
    def _event_type(site: dict[str, Any]) -> str:
        text = " ".join(
            str(site.get(key, ""))
            for key in ("information_type", "status", "application_status", "text")
        )
        if any(term in text for term in ("再販", "再入荷", "RESTOCK")):
            return "RESTOCK"
        if "販売開始" in text:
            return "SALE_START"
        if "予約" in text:
            return "RESERVATION_START"
        if any(term in text for term in ("抽選", "応募", "受付開始")):
            return "APPLICATION_START"
        return "NEW_CONFIRMED"

    @staticmethod
    def _application_id(product: dict[str, Any], site: dict[str, Any]) -> str:
        explicit = str(site.get("application_id") or "").strip()
        if explicit:
            return explicit
        source = "|".join(
            (
                str(product.get("id") or product.get("product_id") or product.get("name") or ""),
                str(site.get("site_key") or site.get("name") or ""),
                str(site.get("application_url") or site.get("url") or ""),
            )
        )
        return hashlib.sha256(source.encode("utf-8")).hexdigest()[:24]

    @staticmethod
    def _dedupe_key(*parts: str) -> str:
        return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()

    @staticmethod
    def _event_time(product: dict[str, Any], site: dict[str, Any]) -> datetime | None:
        for value in (
            site.get("confirmed_at"),
            site.get("detected_at"),
            site.get("application_added_at"),
            site.get("created_at"),
            product.get("detected_at"),
            product.get("created_at"),
        ):
            parsed = parse_jst_datetime(value)
            if parsed is not None:
                return parsed.astimezone(JST)
        return None

    @staticmethod
    def _sales_mode(site: dict[str, Any]) -> str:
        value = str(site.get("sales_mode") or site.get("sales_method_hint") or "UNKNOWN").upper()
        return value if value in {"ONLINE", "STORE", "HYBRID", "UNKNOWN"} else "UNKNOWN"

    @staticmethod
    def _as_jst(value: datetime) -> datetime:
        return value.replace(tzinfo=JST) if value.tzinfo is None else value.astimezone(JST)
