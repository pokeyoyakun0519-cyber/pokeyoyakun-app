import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

from PySide6.QtWidgets import QApplication, QComboBox, QPushButton

from core.application_dashboard import ApplicationDashboard
from core.application_status import JST
from core.config_manager import ConfigManager
from core.product_store import ProductStore
from ui.application_dashboard_page import ApplicationDashboardPage, ApplicationRow


NOW = datetime(2026, 8, 19, 12, tzinfo=JST)


def site(key, *, mode="UNKNOWN", prefecture="UNKNOWN", state="未応募",
         end=None, verification="confirmed", name=None):
    return {
        "site_key": key, "name": name or f"{key}店",
        "url": f"https://example.com/{key}",
        "application_url": f"https://example.com/{key}/apply",
        "status": "抽選受付中", "application_state": state,
        "application_end_at": (end or NOW + timedelta(days=2)).isoformat(),
        "sales_mode": mode, "prefecture": prefecture,
        "verification_status": verification,
        "branch": "駅前支店", "address": "保存済み住所", "chain": "sample-chain",
        "city": "保存済み市", "location_source": "official_address",
        "source_type": "official_store_page", "evidence": [{"url": "https://example.com/evidence"}],
    }


class DashboardFilterTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = ProductStore(self.root)
        products = [{
            "id": "p1", "name": "商品A", "tcg_key": "pokemon",
            "sites": [
                site("online", mode="ONLINE", prefecture="東京都"),
                site("store", mode="STORE", prefecture="大阪府", state="応募済み"),
                site("hybrid", mode="HYBRID", prefecture="東京都", state="当選"),
                site("unknown", verification="pending"),
                site("ended", mode="STORE", end=NOW - timedelta(days=10)),
                site("expired-ui", mode="ONLINE", end=NOW - timedelta(days=15)),
            ],
        }, {
            "id": "p2", "name": "別商品", "tcg_key": "onepiece",
            "sites": [site("onepiece", mode="ONLINE", prefecture="福岡県")],
        }]
        self.store._save_product_file(products)
        self.store.save_site_application_state(
            "p1", "store", "https://example.com/store", True, "pokemon", "ポケモンカード")
        self.store.save_site_result(
            "p1", "hybrid", "https://example.com/hybrid", "当選")
        self.dashboard = ApplicationDashboard(self.store, ConfigManager(self.root))

    def tearDown(self):
        self.temp.cleanup()

    def build(self, **kwargs):
        return self.dashboard.build(now=NOW, show_ended=True, **kwargs)

    def test_active_and_ended_tabs_keep_only_fourteen_days(self):
        active = self.build(period_filter="active")["rows"]
        ended = self.build(period_filter="ended")["rows"]
        self.assertEqual(5, len(active))
        self.assertEqual(["ended"], [row["site_key"] for row in ended])
        self.assertNotIn("expired-ui", {row["site_key"] for row in self.build()["rows"]})

    def test_fourteen_day_boundary_is_visible_but_next_moment_is_hidden(self):
        boundary = site("boundary", end=NOW - timedelta(days=14))
        self.store._save_product_file([{"id": "p", "name": "境界商品", "tcg_key": "pokemon",
                                        "sites": [boundary]}])
        self.assertEqual(1, len(self.build(period_filter="ended")["rows"]))
        later = self.dashboard.build(now=NOW + timedelta(seconds=1), show_ended=True,
                                     period_filter="ended")
        self.assertEqual([], later["rows"])
        saved = json.loads((self.root / "data" / "products.json").read_text("utf-8"))
        self.assertEqual("boundary", saved[0]["sites"][0]["site_key"])

    def test_each_sales_mode_filter(self):
        expected = {"ONLINE": {"online", "onepiece"}, "STORE": {"store", "ended"},
                    "HYBRID": {"hybrid"}, "UNKNOWN": {"unknown"}}
        for mode, keys in expected.items():
            with self.subTest(mode=mode):
                rows = self.build(sales_mode_filter=mode)["rows"]
                self.assertEqual(keys, {row["site_key"] for row in rows})

    def test_prefecture_tcg_state_keyword_and_combined_filters(self):
        self.assertEqual({"online", "hybrid"}, {
            row["site_key"] for row in self.build(prefecture_filter="東京都")["rows"]})
        self.assertEqual({"onepiece"}, {
            row["site_key"] for row in self.build(tcg_filter="onepiece")["rows"]})
        self.assertEqual({"store"}, {
            row["site_key"] for row in self.build(state_filter="応募済み")["rows"]})
        self.assertEqual({"online"}, {
            row["site_key"] for row in self.build(keyword="online店")["rows"]})
        combined = self.build(tcg_filter="pokemon", sales_mode_filter="ONLINE",
                              prefecture_filter="東京都", state_filter="未応募",
                              keyword="商品A", period_filter="active")["rows"]
        self.assertEqual(["online"], [row["site_key"] for row in combined])

    def test_candidate_remains_pending_and_unknown_prefecture_is_not_inferred(self):
        candidate = next(row for row in self.build()["rows"] if row["site_key"] == "unknown")
        self.assertTrue(candidate["is_candidate"])
        self.assertEqual("UNKNOWN", candidate["prefecture"])

    def test_product_group_is_parent_with_store_children(self):
        data = self.build(period_filter="active", tcg_filter="pokemon")
        self.assertEqual(1, len(data["groups"]))
        self.assertEqual("商品A", data["groups"][0]["product_name"])
        self.assertEqual(4, len(data["groups"][0]["rows"]))


class DashboardUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_only_two_main_tabs_and_filters_do_not_reload_json(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {"POKEYOYA_DATA_ROOT": directory}, clear=False
        ):
            page = ApplicationDashboardPage()
            self.assertEqual(["active", "ended"], [
                page.period_tabs.tabData(index) for index in range(page.period_tabs.count())])
            page.dashboard.build = Mock(wraps=page.dashboard.build)
            page.sales_mode_filter.setCurrentIndex(1)
            page.tcg_filter.setCurrentIndex(1)
            page.keyword.setText("商品")
            page.period_tabs.setCurrentIndex(1)
            self.assertEqual(0, page.dashboard.build.call_count)
            self.assertEqual(4, page.filter_panel.layout().count())
            page.close()

    def test_candidate_card_disables_confirmed_actions_and_details_fold(self):
        row = {
            "product_name": "確認中商品", "site_name": "候補店", "is_candidate": True,
            "verification_status": "pending", "application_state": "未応募",
            "dashboard_state": "未応募", "sales_mode": "UNKNOWN", "prefecture": "UNKNOWN",
            "application_url": "https://example.com/apply", "product_url": "https://example.com/product",
            "evidence": [], "condition_warnings": [], "changes": {},
        }
        card = ApplicationRow(row, Mock(), Mock(), Mock())
        self.assertEqual("CandidateCard", card.objectName())
        buttons = {button.text(): button for button in card.findChildren(QPushButton)}
        self.assertFalse(buttons["応募ページを開く"].isEnabled())
        self.assertFalse(buttons["応募済みにする"].isEnabled())
        self.assertTrue(all(widget.isHidden() for widget in card.detail_widgets))
        buttons["詳細を表示"].click()
        self.assertFalse(card.detail_widgets[0].isHidden())
        self.assertFalse(card.findChildren(QComboBox)[0].isEnabled())
        card.close()


if __name__ == "__main__":
    unittest.main()
