from collections import Counter
from datetime import datetime, timedelta
from typing import Any

from core.application_period import ApplicationPeriodParser
from core.application_site import has_application_evidence, normalize_application_site
from core.application_change_tracker import ApplicationChangeTracker
from core.application_condition_detector import ApplicationConditionDetector
from core.application_status import JST, evaluate_application_period
from core.config_manager import ConfigManager
from core.daily_task_manager import DailyTaskManager
from core.product_store import ProductStore
from core.phase3_dashboard import is_new
from core.tcg_categories import categories, display_name, normalize_key


class ApplicationDashboard:
    def __init__(self, store: ProductStore | None = None, config_manager: ConfigManager | None = None):
        self.store = store or ProductStore()
        self.config_manager = config_manager or ConfigManager()
        self.task_manager = DailyTaskManager()
        self.task_manager.store = self.store
        self.change_tracker = ApplicationChangeTracker(getattr(self.store, "root", None))

    def build(
        self,
        *,
        state_filter: str = "すべて",
        sort_mode: str = "応募締切順",
        keyword: str = "",
        tcg_filter: str = "all",
        sales_mode_filter: str = "all",
        prefecture_filter: str = "all",
        period_filter: str = "all",
        show_ended: bool | None = None,
        now=None,
    ) -> dict[str, Any]:
        if show_ended is None:
            show_ended = bool(
                self.config_manager.load().get("general", {}).get(
                    "show_ended_applications", False
                )
            )
        products = self.store.load_products()

        rows = []
        recent_changes = self.change_tracker.latest_by_key()
        counts = Counter()
        tcg_counts = Counter()
        diagnostics = Counter()
        diagnostics_by_tcg: dict[str, Counter] = {}
        diagnostics["loaded_products"] = len(products)

        for product in products:
            product_tcg_key = normalize_key(
                product.get("tcg_key"), product.get("tcg")
            )[0]
            product_diagnostics = diagnostics_by_tcg.setdefault(
                product_tcg_key, Counter()
            )
            product_diagnostics["loaded_products"] += 1
            for site in product.get("sites", []):
                diagnostics["loaded_sites"] += 1
                product_diagnostics["loaded_sites"] += 1
                site = ApplicationPeriodParser().enrich_site(
                    dict(site),
                    "\n".join(
                        str(site.get(key, ""))
                        for key in ("application_period", "order_period", "result_date")
                        if site.get(key)
                    ),
                    release_date=str(product.get("release_date", "")),
                )
                site = normalize_application_site(site, product=product)
                if not has_application_evidence(site):
                    diagnostics["excluded_no_application_evidence"] += 1
                    product_diagnostics["excluded_no_application_evidence"] += 1
                    continue
                diagnostics["application_evidence"] += 1
                period = evaluate_application_period(site, now=now)
                state = self._display_state(str(
                    site.get(
                        "application_state",
                        "未応募",
                    )
                ))
                counts[state] += 1
                tcg_key = normalize_key(
                    site.get("tcg_key", product.get("tcg_key")),
                    site.get("tcg", product.get("tcg")),
                )[0]
                row_diagnostics = diagnostics_by_tcg.setdefault(
                    tcg_key, Counter()
                )
                row_diagnostics["application_evidence"] += 1
                tcg_counts[tcg_key] += 1
                dashboard_state = self._dashboard_state(state, site, period)
                item_key = ApplicationChangeTracker.item_key(product, site)

                row = {
                    "product_id": product.get("id", ""),
                    "product_name": product.get(
                        "name",
                        "商品名未設定",
                    ),
                    "tcg_key": tcg_key,
                    "tcg": display_name(tcg_key),
                    "release_date": product.get(
                        "release_date",
                        "",
                    ),
                    "site_key": site.get("site_key", ""),
                    "site_name": site.get(
                        "name",
                        "店舗名未設定",
                    ),
                    "site_url": site.get("url", ""),
                    "application_url": site.get("application_url", ""),
                    "product_url": site.get(
                        "product_url", product.get("official_url", "")
                    ),
                    "related_url": site.get("url", ""),
                    "status": site.get("status", ""),
                    "application_state": state,
                    "dashboard_state": dashboard_state,
                    "application_period": site.get(
                        "application_period",
                        "",
                    ),
                    "application_end": (
                        self._date_text(
                            self.task_manager.parse_period_end(
                                str(
                                    site.get(
                                        "application_period",
                                        "",
                                    )
                                )
                            )
                        )
                    ),
                    "result_date": site.get(
                        "result_date",
                        "",
                    ),
                    "result_sort_date": (
                        self._date_text(
                            self.task_manager.parse_date(
                                str(
                                    site.get(
                                        "result_date",
                                        "",
                                    )
                                )
                            )
                        )
                    ),
                    "order_period": site.get(
                        "order_period",
                        "",
                    ),
                    "order_end": (
                        self._date_text(
                            self.task_manager.parse_period_end(
                                str(
                                    site.get(
                                        "order_period",
                                        "",
                                    )
                                )
                            )
                        )
                    ),
                    "result_status": site.get(
                        "result_status",
                        "未確認",
                    ),
                    "application_datetime": site.get("applied_at", ""),
                    "result_checked_at": site.get("result_checked_at", ""),
                    "masked_reference": self._masked_reference(site),
                    "application_start_at": site.get("application_start_at", ""),
                    "is_new": is_new(
                        site.get("application_added_at")
                        or site.get("created_at")
                        or site.get("detected_at")
                        or site.get("application_start_at"),
                        now=now,
                    ),
                    "application_end_at": site.get("application_end_at", ""),
                    "result_announcement_at": site.get("result_announcement_at", ""),
                    "application_method": site.get("application_method", ""),
                    "application_conditions": site.get("application_conditions", ""),
                    "target_store": site.get("target_store", site.get("name", "")),
                    "period_evidence": site.get("period_evidence", ""),
                    "period_status": period["period_status"],
                    "period_ended": period["period_ended"],
                    "remaining_text": period["remaining_text"],
                    "end_reason": period["end_reason"],
                    "condition_warnings": ApplicationConditionDetector.detect(site),
                    "changes": recent_changes.get(item_key, {}).get("changes", {}),
                    "change_detected_at": recent_changes.get(item_key, {}).get("detected_at", ""),
                    "sales_mode": self._sales_mode(site),
                    "prefecture": str(site.get("prefecture", "")).strip() or "UNKNOWN",
                    "branch": site.get("branch", site.get("branch_name", "")),
                    "address": site.get("address", ""),
                    "chain": site.get("chain", site.get("store_group_id", "")),
                    "city": site.get("city", ""),
                    "location_source": site.get("location_source", ""),
                    "source_type": site.get("source_type", product.get("source_type", "")),
                    "evidence": site.get("evidence", product.get("evidence", [])),
                    "verification_status": site.get(
                        "verification_status", product.get("verification_status", "confirmed")
                    ),
                    "verification_details": site.get("verification_details", ""),
                }
                row["is_candidate"] = str(row["verification_status"]).casefold() in {
                    "candidate", "pending", "confirming", "確認中",
                } or ("confirmed" in site and site.get("confirmed") is False)
                rows.append(row)

        eligible_rows = []
        for row in rows:
            if row["period_ended"]:
                if not self._within_ended_retention(row, now):
                    diagnostics["excluded_ended_retention"] += 1
                    continue
                if not show_ended:
                    diagnostics["excluded_ended"] += 1
                    diagnostics_by_tcg.setdefault(
                        row["tcg_key"], Counter()
                    )["excluded_ended"] += 1
                    continue
            eligible_rows.append(row)
            diagnostics_by_tcg.setdefault(
                row["tcg_key"], Counter()
            )["eligible_rows"] += 1
        counts = Counter(row["application_state"] for row in eligible_rows)
        state_counts = Counter(row["dashboard_state"] for row in eligible_rows)
        tcg_counts = Counter(row["tcg_key"] for row in eligible_rows)
        visible = []
        for row in eligible_rows:
            if tcg_filter != "all" and row["tcg_key"] != tcg_filter:
                diagnostics["excluded_tcg_filter"] += 1
                diagnostics_by_tcg.setdefault(
                    row["tcg_key"], Counter()
                )["excluded_tcg_filter"] += 1
                continue
            if sales_mode_filter != "all" and row["sales_mode"] != sales_mode_filter:
                diagnostics["excluded_sales_mode_filter"] += 1
                continue
            if prefecture_filter != "all" and row["prefecture"] != prefecture_filter:
                diagnostics["excluded_prefecture_filter"] += 1
                continue
            if period_filter == "active" and row["period_ended"]:
                continue
            if period_filter == "ended" and not row["period_ended"]:
                continue
            if not self._matches_state(row, state_filter):
                diagnostics["excluded_state_filter"] += 1
                diagnostics_by_tcg.setdefault(
                    row["tcg_key"], Counter()
                )["excluded_state_filter"] += 1
                continue
            if not self._matches_keyword(row, keyword):
                diagnostics["excluded_keyword"] += 1
                diagnostics_by_tcg.setdefault(
                    row["tcg_key"], Counter()
                )["excluded_keyword"] += 1
                continue
            visible.append(row)
            diagnostics_by_tcg.setdefault(
                row["tcg_key"], Counter()
            )["displayed_rows"] += 1
        diagnostics["eligible_rows"] = len(eligible_rows)
        diagnostics["displayed_rows"] = len(visible)

        visible.sort(
            key=self._sort_key(sort_mode)
        )

        return {
            "counts": {
                "未応募": counts["未応募"],
                "応募済み": counts["応募済み"],
                "抽選結果待ち": counts["抽選結果待ち"],
                "当選": counts["当選"],
                "落選": counts["落選"],
                "予約完了": counts["予約完了"],
                "注文受付": counts["注文受付"],
                "キャンセル": counts["キャンセル"],
                "その他": counts["その他"],
            },
            "state_counts": {
                key: state_counts[key]
                for key in ("未応募", "応募済み", "本日締切", "結果待ち", "当選", "落選", "終了済み")
            },
            "tcg_counts": {
                item.key: tcg_counts[item.key] for item in categories()
            },
            "rows": visible,
            "groups": self._group_rows(visible),
            "total_rows": len(eligible_rows),
            "history_total_rows": len(rows),
            "ended_rows": sum(bool(row["period_ended"])
                              and self._within_ended_retention(row, now) for row in rows),
            "diagnostics": dict(diagnostics),
            "diagnostics_by_tcg": {
                item.key: dict(diagnostics_by_tcg.get(item.key, Counter()))
                for item in categories()
            },
        }

    @classmethod
    def filter_cached(
        cls, rows: list[dict[str, Any]], *, period_filter: str = "active",
        state_filter: str = "すべて", keyword: str = "", tcg_filter: str = "all",
        sales_mode_filter: str = "all", prefecture_filter: str = "all",
        sort_mode: str = "応募締切順",
    ) -> list[dict[str, Any]]:
        """Filter an already loaded snapshot; this performs no storage or network I/O."""
        visible = [row for row in rows if (
            (period_filter != "active" or not row.get("period_ended"))
            and (period_filter != "ended" or bool(row.get("period_ended")))
            and (tcg_filter == "all" or row.get("tcg_key") == tcg_filter)
            and (sales_mode_filter == "all" or row.get("sales_mode") == sales_mode_filter)
            and (prefecture_filter == "all" or row.get("prefecture") == prefecture_filter)
            and cls._matches_state(row, state_filter)
            and cls._matches_keyword(row, keyword)
        )]
        visible.sort(key=cls._sort_key(sort_mode))
        return visible

    @staticmethod
    def _sales_mode(site: dict[str, Any]) -> str:
        value = str(site.get("sales_mode") or site.get("sales_method_hint")
                    or site.get("channel") or "UNKNOWN").strip().upper()
        aliases = {"ONLINE": "ONLINE", "STORE": "STORE", "PHYSICAL": "STORE",
                   "HYBRID": "HYBRID", "CHAIN": "STORE", "UNKNOWN": "UNKNOWN"}
        return aliases.get(value, "UNKNOWN")

    @staticmethod
    def _within_ended_retention(row: dict[str, Any], now) -> bool:
        value = str(row.get("application_end_at") or row.get("application_end") or "").strip()
        if not value:
            return True
        try:
            ended_at = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return True
        if ended_at.tzinfo is None:
            ended_at = ended_at.replace(tzinfo=JST)
        current = now or datetime.now(JST)
        if current.tzinfo is None:
            current = current.replace(tzinfo=JST)
        return current.astimezone(JST) <= ended_at.astimezone(JST) + timedelta(days=14)

    @staticmethod
    def _matches_filter(
        row: dict[str, Any],
        state_filter: str,
        keyword: str,
        tcg_filter: str,
    ) -> bool:
        return (
            (tcg_filter == "all" or row["tcg_key"] == tcg_filter)
            and ApplicationDashboard._matches_state(row, state_filter)
            and ApplicationDashboard._matches_keyword(row, keyword)
        )

    @staticmethod
    def _matches_state(row: dict[str, Any], state_filter: str) -> bool:
        return not (
            state_filter != "すべて"
            and row["application_state"] != state_filter
            and row.get("period_status") != state_filter
            and row.get("dashboard_state") != state_filter
        )

    @staticmethod
    def _matches_keyword(row: dict[str, Any], keyword: str) -> bool:
        normalized_keyword = keyword.strip().lower()
        if not normalized_keyword:
            return True

        target = (
            str(row["product_name"])
            + " "
            + str(row["site_name"])
            + " "
            + str(row["tcg"])
        ).lower()
        return normalized_keyword in target

    @staticmethod
    def _sort_key(sort_mode: str):
        state_order = {
            "抽選結果待ち": 0,
            "当選": 1,
            "応募済み": 2,
            "予約完了": 2,
            "注文受付": 2,
            "未応募": 3,
            "落選": 4,
            "キャンセル": 5,
            "その他": 6,
            "受付前": 3,
            "受付中": 2,
            "本日締切": 0,
            "終了済み": 7,
        }

        if sort_mode == "応募締切順":
            return lambda row: (
                row["application_end_at"] or row["application_end"] or "9999-99-99",
                state_order.get(
                    row["application_state"],
                    9,
                ),
                row["product_name"],
            )

        if sort_mode == "結果発表順":
            return lambda row: (
                row["result_sort_date"] or "9999-99-99",
                state_order.get(
                    row["application_state"],
                    9,
                ),
                row["product_name"],
            )

        if sort_mode == "発売日順":
            return lambda row: (
                row["release_date"] or "9999-99-99",
                row["product_name"],
                row["site_name"],
            )

        if sort_mode == "店舗名順":
            return lambda row: (
                row["site_name"],
                row["product_name"],
            )

        return lambda row: (
            state_order.get(
                row["application_state"],
                9,
            ),
            row["result_sort_date"] or "9999-99-99",
            row["release_date"] or "9999-99-99",
            row["product_name"],
            row["site_name"],
        )

    @staticmethod
    def _dashboard_state(
        application_state: str,
        site: dict[str, Any],
        period: dict[str, Any],
    ) -> str:
        result = str(site.get("result_status", "未確認"))
        if application_state == "当選" or result == "当選":
            return "当選"
        if application_state == "落選" or result == "落選":
            return "落選"
        if period.get("period_ended"):
            return "終了済み"
        if application_state == "未応募":
            return "本日締切" if period.get("period_status") == "本日締切" else "未応募"
        if application_state == "抽選結果待ち":
            return "結果待ち"
        return "応募済み"

    @staticmethod
    def _group_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        groups: dict[str, dict[str, Any]] = {}
        order = []
        for row in rows:
            key = str(row.get("product_id") or row.get("product_name"))
            if key not in groups:
                groups[key] = {
                    "product_id": row.get("product_id", ""),
                    "product_name": row.get("product_name", "商品名未設定"),
                    "tcg_key": row.get("tcg_key", "other"),
                    "tcg": row.get("tcg", "その他"),
                    "rows": [],
                }
                order.append(key)
            groups[key]["rows"].append(row)
        return [groups[key] for key in order]

    @staticmethod
    def _date_text(value) -> str:
        return value.isoformat() if value else ""

    @staticmethod
    def _display_state(value: str) -> str:
        return {
            "抽選受付完了": "応募済み",
            "抽選結果確認": "抽選結果待ち",
            "結果待ち候補": "抽選結果待ち",
        }.get(value, value if value in {
            "未応募", "応募済み", "抽選結果待ち", "当選", "落選",
            "予約完了", "注文受付", "キャンセル", "その他",
        } else "その他")

    @staticmethod
    def _masked_reference(site: dict[str, Any]) -> str:
        for key in ("receipt_number", "reception_number", "order_number"):
            value = str(site.get(key, "")).strip()
            if value:
                if len(value) <= 4:
                    return "●" * len(value)
                return value[:2] + "●" * min(8, len(value) - 4) + value[-2:]
        return ""
