from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from core.application_dashboard import ApplicationDashboard
from core.application_period import JST, normalize_saved_application_period
from core.config_manager import ConfigManager
from core.product_store import ProductStore


NOW = datetime(2026, 8, 22, 12, 0, tzinfo=JST)


class Test6SavedApplicationNormalizationTest(unittest.TestCase):
    @staticmethod
    def product(site: dict, *, product_id: str = "storm-emerald") -> dict:
        return {
            "id": product_id,
            "name": (
                "拡張パック「ストームエメラルダ」"
                if product_id == "storm-emerald"
                else f"テスト商品 {product_id}"
            ),
            "tcg_key": "pokemon",
            "release_date": "2026-07-10",
            "sites": [{
                "site_key": "official-store",
                "name": "公式店",
                "url": "https://official.example/apply",
                "status": "抽選受付中",
                **site,
            }],
        }

    def test_saved_application_end_is_normalized_on_load_without_persistence(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ProductStore(Path(directory))
            store._save_product_file([self.product({
                "application_end": "2026-06-29",
                "application_end_at": "",
            })])
            first = store.load_products()[0]["sites"][0]
            second = store.load_products()[0]["sites"][0]
            persisted = store._load_product_file()[0]["sites"][0]

        self.assertEqual("2026-06-29T23:59:59+09:00", first["application_end_at"])
        self.assertFalse(first["application_end_time_confirmed"])
        self.assertEqual(first["application_end_at"], second["application_end_at"])
        self.assertEqual("2026-06-29", persisted["application_end"])
        self.assertEqual("", persisted["application_end_at"])

    def test_storm_emerald_is_outside_retention_and_hidden(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = ProductStore(root)
            store._save_product_file([self.product({
                "application_end": "2026/06/29",
                "application_end_at": "",
            })])
            dashboard = ApplicationDashboard(store, ConfigManager(root))
            result = dashboard.build(show_ended=True, now=NOW)

        self.assertEqual([], result["rows"])
        self.assertEqual(1, result["diagnostics"]["excluded_ended_retention"])

    def test_ended_five_days_ago_is_in_ended_tab(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = ProductStore(root)
            store._save_product_file([self.product({"application_end": "2026-08-17"})])
            result = ApplicationDashboard(store, ConfigManager(root)).build(
                show_ended=True, period_filter="ended", now=NOW
            )
        self.assertEqual(1, len(result["rows"]))
        self.assertTrue(result["rows"][0]["period_ended"])

    def test_future_deadline_is_active(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = ProductStore(root)
            store._save_product_file([self.product({"application_end": "2026-08-30"})])
            result = ApplicationDashboard(store, ConfigManager(root)).build(
                period_filter="active", now=NOW
            )
        self.assertEqual(1, len(result["rows"]))
        self.assertFalse(result["rows"][0]["period_ended"])

    def test_unknown_deadline_remains_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = ProductStore(root)
            store._save_product_file([self.product({})])
            result = ApplicationDashboard(store, ConfigManager(root)).build(now=NOW)
        self.assertEqual(1, len(result["rows"]))
        self.assertEqual("締切日時不明", result["rows"][0]["remaining_text"])

    def test_legacy_period_fields_and_formats_are_normalized_on_load(self):
        cases = (
            ({"application_end": "2026-08-29"}, "2026-08-29T23:59:59+09:00"),
            ({"application_end": "2026/08/29"}, "2026-08-29T23:59:59+09:00"),
            ({"application_end": "2026年8月29日"}, "2026-08-29T23:59:59+09:00"),
            ({"application_period": "2026年8/21（金）～8/23（日）"}, "2026-08-23T23:59:59+09:00"),
            ({"application_end": "8/29"}, "2026-08-29T23:59:59+09:00"),
            ({"application_end": "8月29日"}, "2026-08-29T23:59:59+09:00"),
            ({"application_period": "2026年8月1日～2026年8月29日"}, "2026-08-29T23:59:59+09:00"),
            ({"order_period": "2026/08/01～2026/08/29"}, "2026-08-29T23:59:59+09:00"),
            ({"application_end_at": "2026/08/29"}, "2026-08-29T23:59:59+09:00"),
        )
        with tempfile.TemporaryDirectory() as directory:
            store = ProductStore(Path(directory))
            store._save_product_file([
                self.product(value, product_id=f"legacy-{index}")
                for index, (value, _expected) in enumerate(cases)
            ])
            loaded = store.load_products()
        actual = [product["sites"][0]["application_end_at"] for product in loaded]
        self.assertEqual([expected for _value, expected in cases], actual)

    def test_release_date_alone_is_not_a_deadline(self):
        site = normalize_saved_application_period(
            {"status": "商品掲載あり", "notice": "発売日 2026年8月29日"},
            product={"release_date": "2026-08-29"},
            now=NOW,
        )
        self.assertFalse(site.get("application_end_at"))

    def test_real_legacy_pokemon_period_with_full_width_weekdays(self):
        site = normalize_saved_application_period(
            {"application_period": "6月26日（金）16時00分～6月29日（月）16時59分"},
            product={"release_date": "2026-07-31"},
            now=NOW,
        )
        self.assertEqual("2026-06-26T16:00:00+09:00", site["application_start_at"])
        self.assertEqual("2026-06-29T16:59:59+09:00", site["application_end_at"])
        self.assertTrue(site["application_end_time_confirmed"])


if __name__ == "__main__":
    unittest.main()
