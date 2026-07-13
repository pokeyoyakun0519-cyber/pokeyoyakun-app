import re
from datetime import date, datetime, timedelta
from typing import Any

from core.product_store import ProductStore


class DailyTaskManager:
    """応募締切・結果発表・購入期限・発売日のタスクを生成する。"""

    def __init__(self):
        self.store = ProductStore()

    def build_tasks(
        self,
        *,
        days_ahead: int = 1,
    ) -> list[dict[str, Any]]:
        today = date.today()
        end_date = today + timedelta(
            days=max(0, days_ahead)
        )
        tasks: list[dict[str, Any]] = []

        for product in self.store.load_products():
            product_name = str(
                product.get(
                    "name",
                    "商品名未設定",
                )
            )
            release_date = self.parse_date(
                str(product.get("release_date", ""))
            )

            if (
                release_date is not None
                and today <= release_date <= end_date
            ):
                tasks.append(
                    self._make_task(
                        task_type="発売日",
                        due_date=release_date,
                        product=product,
                        site=None,
                        priority=4,
                    )
                )

            for site in product.get("sites", []):
                state = str(
                    site.get(
                        "application_state",
                        "未応募",
                    )
                )

                application_end = self.parse_period_end(
                    str(
                        site.get(
                            "application_period",
                            "",
                        )
                    )
                )
                result_date = self.parse_date(
                    str(site.get("result_date", ""))
                )
                order_end = self.parse_period_end(
                    str(site.get("order_period", ""))
                )

                if (
                    state == "未応募"
                    and application_end is not None
                    and today <= application_end <= end_date
                ):
                    tasks.append(
                        self._make_task(
                            task_type="応募締切",
                            due_date=application_end,
                            product=product,
                            site=site,
                            priority=1,
                        )
                    )

                if (
                    state == "抽選結果確認"
                    or (
                        state == "抽選受付完了"
                        and result_date is not None
                        and today <= result_date <= end_date
                    )
                ):
                    tasks.append(
                        self._make_task(
                            task_type="結果確認",
                            due_date=result_date or today,
                            product=product,
                            site=site,
                            priority=0,
                        )
                    )

                if (
                    state == "当選"
                    and order_end is not None
                    and today <= order_end <= end_date
                ):
                    tasks.append(
                        self._make_task(
                            task_type="購入期限",
                            due_date=order_end,
                            product=product,
                            site=site,
                            priority=2,
                        )
                    )

        tasks.sort(
            key=lambda task: (
                task["priority"],
                task["due_date"],
                task["product_name"],
                task["site_name"],
            )
        )
        return tasks

    @staticmethod
    def parse_period_end(value: str) -> date | None:
        dates = DailyTaskManager._extract_dates(value)
        return dates[-1] if dates else None

    @staticmethod
    def parse_date(value: str) -> date | None:
        dates = DailyTaskManager._extract_dates(value)
        return dates[0] if dates else None

    @staticmethod
    def _extract_dates(value: str) -> list[date]:
        if not value.strip():
            return []

        today = date.today()
        output: list[date] = []

        patterns = (
            re.compile(
                r"(?P<year>\d{4})[./年-]"
                r"\s*(?P<month>\d{1,2})[./月-]"
                r"\s*(?P<day>\d{1,2})日?"
            ),
            re.compile(
                r"(?P<month>\d{1,2})[./月]"
                r"\s*(?P<day>\d{1,2})日?"
            ),
        )

        for pattern in patterns:
            for match in pattern.finditer(value):
                try:
                    year_text = match.groupdict().get("year")
                    year = (
                        int(year_text)
                        if year_text
                        else today.year
                    )
                    month = int(match.group("month"))
                    day = int(match.group("day"))
                    candidate = date(
                        year,
                        month,
                        day,
                    )

                    if (
                        not year_text
                        and candidate
                        < today - timedelta(days=120)
                    ):
                        candidate = date(
                            today.year + 1,
                            month,
                            day,
                        )
                except (TypeError, ValueError):
                    continue

                if candidate not in output:
                    output.append(candidate)

            if output:
                break

        return sorted(output)

    @staticmethod
    def _make_task(
        *,
        task_type: str,
        due_date: date,
        product: dict[str, Any],
        site: dict[str, Any] | None,
        priority: int,
    ) -> dict[str, Any]:
        return {
            "task_type": task_type,
            "due_date": due_date.isoformat(),
            "product_id": str(product.get("id", "")),
            "product_name": str(
                product.get(
                    "name",
                    "商品名未設定",
                )
            ),
            "site_key": (
                str(site.get("site_key", ""))
                if site
                else ""
            ),
            "site_name": (
                str(site.get("name", ""))
                if site
                else ""
            ),
            "url": (
                str(site.get("url", ""))
                if site
                else str(
                    product.get(
                        "official_url",
                        "",
                    )
                )
            ),
            "priority": priority,
        }
