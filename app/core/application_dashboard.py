from collections import Counter
from typing import Any

from core.daily_task_manager import DailyTaskManager
from core.product_store import ProductStore


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
    ) -> dict[str, Any]:
        products = self.store.load_products()

        rows = []
        counts = Counter()

        for product in products:
            for site in product.get("sites", []):
                state = str(
                    site.get(
                        "application_state",
                        "未応募",
                    )
                )
                counts[state] += 1

                row = {
                    "product_id": product.get("id", ""),
                    "product_name": product.get(
                        "name",
                        "商品名未設定",
                    ),
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
                }
                rows.append(row)

        visible = [
            row
            for row in rows
            if self._matches_filter(
                row,
                state_filter,
                keyword,
            )
        ]

        visible.sort(
            key=self._sort_key(sort_mode)
        )

        return {
            "counts": {
                "未応募": counts["未応募"],
                "抽選受付完了": counts["抽選受付完了"],
                "抽選結果確認": counts["抽選結果確認"],
                "当選": counts["当選"],
                "落選": counts["落選"],
            },
            "rows": visible,
            "total_rows": len(rows),
        }

    @staticmethod
    def _matches_filter(
        row: dict[str, Any],
        state_filter: str,
        keyword: str,
    ) -> bool:
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
        ).lower()
        return normalized_keyword in target

    @staticmethod
    def _sort_key(sort_mode: str):
        state_order = {
            "抽選結果確認": 0,
            "当選": 1,
            "抽選受付完了": 2,
            "未応募": 3,
            "落選": 4,
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
