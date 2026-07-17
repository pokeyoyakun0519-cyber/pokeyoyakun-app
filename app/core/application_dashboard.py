from collections import Counter
from typing import Any

from core.daily_task_manager import DailyTaskManager
from core.product_store import ProductStore
from core.tcg_categories import categories, display_name, normalize_key


class ApplicationDashboard:
    def __init__(self):
        self.store = ProductStore()
        self.task_manager = DailyTaskManager()
        self.task_manager.store = self.store

    def build(
        self,
        *,
        state_filter: str = "すべて",
        sort_mode: str = "優先度順",
        keyword: str = "",
        tcg_filter: str = "all",
    ) -> dict[str, Any]:
        products = self.store.load_products()

        rows = []
        counts = Counter()
        tcg_counts = Counter()

        for product in products:
            for site in product.get("sites", []):
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
                tcg_counts[tcg_key] += 1

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
                    "related_url": site.get("url", ""),
                    "status": site.get("status", ""),
                    "application_state": state,
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
                }
                rows.append(row)

        visible = [
            row
            for row in rows
            if self._matches_filter(
                row,
                state_filter,
                keyword,
                tcg_filter,
            )
        ]

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
            "tcg_counts": {
                item.key: tcg_counts[item.key] for item in categories()
            },
            "rows": visible,
            "total_rows": len(rows),
        }

    @staticmethod
    def _matches_filter(
        row: dict[str, Any],
        state_filter: str,
        keyword: str,
        tcg_filter: str,
    ) -> bool:
        if tcg_filter != "all" and row["tcg_key"] != tcg_filter:
            return False
        if (
            state_filter != "すべて"
            and row["application_state"]
            != state_filter
        ):
            return False

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
        }

        if sort_mode == "応募締切順":
            return lambda row: (
                row["application_end"] or "9999-99-99",
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
