from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from core.application_dashboard import ApplicationDashboard
from core.application_period import ApplicationPeriodParser, JST
from core.application_status import evaluate_application_period
from core.config_manager import ConfigManager
from core.product_store import ProductStore
from ui.application_dashboard_page import ApplicationRow


NOW = datetime(2026, 8, 22, 12, 0, tzinfo=JST)


class Test5ApplicationDeadlineTest(unittest.TestCase):
    def parse_deadline(self, value: str):
        return ApplicationPeriodParser.parse(
            "応募締切 " + value, now=NOW, release_date="2026-07-10"
        )

    def test_date_only_formats_use_end_of_day_jst(self):
        for value in (
            "2026-06-29", "2026/06/29", "2026年6月29日",
            "6月29日", "6/29", "6月29日まで", "6月29日締切",
            "6月29日(日)",
        ):
            with self.subTest(value=value):
                parsed = self.parse_deadline(value)
                self.assertEqual(
                    "2026-06-29T23:59:59+09:00", parsed["application_end_at"]
                )
                self.assertFalse(parsed["application_end_time_confirmed"])

    def test_datetime_and_japanese_time_are_confirmed(self):
        for value in (
            "6月29日 23:59まで", "2026年6月29日 23時59分",
            "6/29 23:59", "6月29日(日) 23:59",
        ):
            with self.subTest(value=value):
                parsed = self.parse_deadline(value)
                self.assertEqual(
                    "2026-06-29T23:59:59+09:00", parsed["application_end_at"]
                )
                self.assertTrue(parsed["application_end_time_confirmed"])

    def test_ranges_with_and_without_time(self):
        timed = ApplicationPeriodParser.parse(
            "応募期間：6月28日10:00～6月29日23:59", now=NOW,
            release_date="2026-07-10",
        )
        date_only = ApplicationPeriodParser.parse(
            "応募期間：6月28日～6月29日", now=NOW,
            release_date="2026-07-10",
        )
        self.assertTrue(timed["application_end_time_confirmed"])
        self.assertFalse(date_only["application_end_time_confirmed"])
        self.assertEqual("2026-06-29T23:59:59+09:00", date_only["application_end_at"])

    def test_end_without_start_is_ended(self):
        result = evaluate_application_period(
            {"application_end": "2026-06-29"}, now=NOW
        )
        self.assertTrue(result["period_ended"])
        self.assertEqual("終了済み", result["period_status"])

    def test_enrich_promotes_semantic_application_end_only(self):
        result = ApplicationPeriodParser.enrich_site(
            {"application_end": "2026-06-29"}, "", now=NOW
        )
        self.assertEqual("2026-06-29T23:59:59+09:00", result["application_end_at"])
        self.assertFalse(result["application_end_time_confirmed"])
        release_only = ApplicationPeriodParser.parse("発売日 2026-06-29", now=NOW)
        self.assertFalse(release_only["application_end_at"])

    def test_explicit_cancellation_is_ended(self):
        for status in ("中止", "キャンセル", "受付中止", "抽選中止", "予約中止"):
            with self.subTest(status=status):
                self.assertTrue(evaluate_application_period({"status": status}, now=NOW)["period_ended"])
        self.assertFalse(evaluate_application_period(
            {"status": "商品販売終了予定"}, now=NOW
        )["period_ended"])

    def test_13_day_retention_and_15_day_exclusion_without_storage_delete(self):
        product = {
            "id": "storm-emerald", "name": "拡張パック「ストームエメラルダ」",
            "tcg_key": "pokemon", "release_date": "2026-07-01",
            "sites": [{
                "site_key": "official", "name": "公式店", "url": "https://example.jp/app",
                "application_end": "2026-08-09", "status": "抽選受付",
            }],
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = ProductStore(root)
            store._save_product_file([product])
            dashboard = ApplicationDashboard(store, ConfigManager(root))
            day_13 = dashboard.build(show_ended=True, now=NOW)
            day_15 = dashboard.build(
                show_ended=True, now=datetime(2026, 8, 24, 12, tzinfo=JST)
            )
            persisted = store._load_product_file()
        self.assertEqual(1, len(day_13["rows"]))
        self.assertTrue(day_13["rows"][0]["period_ended"])
        self.assertEqual([], day_15["rows"])
        self.assertEqual(1, len(persisted))

    def test_ui_marks_unconfirmed_time(self):
        self.assertEqual(
            "2026/06/29（時刻未確認）",
            ApplicationRow._deadline_label({
                "application_end_at": "2026-06-29T23:59:59+09:00",
                "application_end_time_confirmed": False,
            }),
        )
        self.assertEqual(
            "2026/06/29 18:00",
            ApplicationRow._deadline_label({
                "application_end_at": "2026-06-29T18:00:00+09:00",
                "application_end_time_confirmed": True,
            }),
        )


if __name__ == "__main__":
    unittest.main()
