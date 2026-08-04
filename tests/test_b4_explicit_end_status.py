import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from core.application_dashboard import ApplicationDashboard
from core.application_status import JST, evaluate_application_period
from core.card_labo_parser import CardLaboParser
from core.config_manager import ConfigManager
from core.hobby_station_parser import HobbyStationParser
from core.product_store import ProductStore


NOW = datetime(2026, 8, 4, 12, tzinfo=JST)


class ExplicitEndStatusTest(unittest.TestCase):
    def evaluate(self, status=None, end=""):
        return evaluate_application_period(
            {"status": status, "application_end_at": end}, now=NOW
        )

    def test_explicit_ended_statuses_without_deadline(self):
        for status in (
            "終了済み", "受付終了", "応募終了", "予約終了", "抽選終了",
            "販売終了", "closed", "ended", "expired",
        ):
            with self.subTest(status=status):
                result = self.evaluate(status)
                self.assertTrue(result["period_ended"])
                self.assertEqual(result["period_status"], "終了済み")

    def test_open_and_unknown_status_without_deadline(self):
        self.assertEqual(self.evaluate("受付中")["period_status"], "受付中")
        for status in (None, "", "状態不明", 123, {}):
            with self.subTest(status=status):
                result = self.evaluate(status)
                self.assertFalse(result["period_ended"])
                self.assertEqual(result["period_status"], "締切日時不明")

    def test_past_and_future_deadlines_keep_jst_behavior(self):
        past = self.evaluate("受付中", "2026-08-04T11:59:00+09:00")
        future = self.evaluate(None, "2026-08-04T13:00:00+09:00")
        self.assertTrue(past["period_ended"])
        self.assertFalse(future["period_ended"])
        self.assertEqual(future["period_status"], "本日締切")

    def test_explicit_end_wins_over_future_deadline_and_logs_warning(self):
        with self.assertLogs("core.application_status", level="WARNING") as logs:
            result = self.evaluate("終了済み", "2026-08-05T23:59:00+09:00")
        self.assertTrue(result["period_ended"])
        self.assertIn("明示的終了状態", logs.output[0])

    def test_open_status_does_not_override_past_deadline(self):
        self.assertTrue(
            self.evaluate("受付中", "2026-08-03T23:59:00+09:00")["period_ended"]
        )

    def test_planned_end_is_not_treated_as_ended(self):
        result = self.evaluate("販売終了予定")
        self.assertFalse(result["period_ended"])
        self.assertEqual(result["period_status"], "締切日時不明")

    def test_natural_ended_phrase_is_supported(self):
        self.assertTrue(self.evaluate("応募受付は終了しました")["period_ended"])

    def test_flags_alternate_status_fields_and_history(self):
        cases = (
            {"application_ended": True},
            {"application_status": "受付終了"},
            {"reception_status": "closed"},
            {"source_status": "expired"},
            {"status_history": [{"status": "応募終了"}]},
        )
        for site in cases:
            with self.subTest(site=site):
                self.assertTrue(evaluate_application_period(site, now=NOW)["period_ended"])

    def test_card_labo_unknown_deadline_end_status_is_preserved(self):
        hit = CardLaboParser._build_hit({
            "article_type": "lottery",
            "article_url": "https://www.c-labo.jp/shop/test/blog/1/",
            "application_evidence": True,
            "status": "終了済み",
        })
        self.assertFalse(hit.get("application_end_at"))
        self.assertTrue(evaluate_application_period(hit, now=NOW)["period_ended"])

    def test_hobby_station_unknown_deadline_end_status_is_preserved(self):
        hit = HobbyStationParser._build_hit({
            "article_type": "application",
            "article_url": "https://www.hbst.net/?p=1",
            "status": "終了済み",
        })
        self.assertFalse(hit.get("application_end_at"))
        self.assertTrue(evaluate_application_period(hit, now=NOW)["period_ended"])


class DashboardEndRetentionTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = ProductStore(self.root)
        self.config = ConfigManager(self.root)
        self.site = {
            "site_key": "ended_shop",
            "name": "終了店舗",
            "url": "https://example.jp/article",
            "application_url": "https://example.jp/apply",
            "status": "終了済み",
            "application_end_at": "",
            "application_state": "当選",
            "result_status": "当選",
        }
        self.store._save_product_file([{
            "id": "p1", "name": "終了商品", "tcg_key": "pokemon",
            "release_date": "2026-08-10", "sites": [self.site],
        }])

    def tearDown(self):
        self.temporary.cleanup()

    def test_ended_item_is_hidden_normally_and_retained_in_history(self):
        dashboard = ApplicationDashboard(self.store, self.config)
        normal = dashboard.build(show_ended=False, now=NOW)
        history = dashboard.build(show_ended=True, now=NOW)
        self.assertEqual(normal["rows"], [])
        self.assertEqual(normal["history_total_rows"], 1)
        self.assertEqual(history["ended_rows"], 1)
        self.assertEqual(history["rows"][0]["dashboard_state"], "当選")

    def test_user_result_and_stored_site_are_not_deleted(self):
        ApplicationDashboard(self.store, self.config).build(show_ended=False, now=NOW)
        stored = self.store._load_product_file()[0]["sites"][0]
        self.assertEqual(stored["application_state"], "当選")
        self.assertEqual(stored["result_status"], "当選")
        self.assertEqual(stored["status"], "終了済み")

    def test_all_and_ended_filters(self):
        dashboard = ApplicationDashboard(self.store, self.config)
        self.assertEqual(
            dashboard.build(state_filter="すべて", show_ended=False, now=NOW)["rows"],
            [],
        )
        ended = dashboard.build(state_filter="終了済み", show_ended=True, now=NOW)
        self.assertEqual(len(ended["rows"]), 1)


if __name__ == "__main__":
    unittest.main()
