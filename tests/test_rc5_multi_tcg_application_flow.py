import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
sys.path.insert(0, str(APP_DIR))

from core.application_dashboard import ApplicationDashboard
from core.application_site import has_application_evidence, normalize_application_site
from core.candidate_manager import CandidateManager
from core.product_store import ProductStore
from core.retail_search_manager import RetailSearchManager
from core.tcg_categories import normalize_record


class MultiTcgApplicationFlowTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def _dashboard(self):
        store = ProductStore(self.root)
        dashboard = ApplicationDashboard(store=store)
        dashboard.change_tracker.root = self.root
        return dashboard

    def test_candidate_product_store_and_dashboard_share_all_supported_tcgs(self):
        manager = CandidateManager(self.root)
        cases = (
            ("ONE_PIECE", "ワンピース応募", {"application_url": "https://example.com/op/apply"}),
            ("gundam", "ガンダム予約", {"order_period": "2099/08/01 10:00～2099/08/10 23:59"}),
            ("Yu-Gi-Oh!", "遊戯王抽選", {"application_period": "2099/08/01 10:00～2099/08/10 23:59"}),
            ("ポケモンカードゲーム", "ポケモン抽選", {"status": "抽選受付中"}),
        )
        for index, (tcg, name, evidence) in enumerate(cases):
            manager.add_manual_candidate(name, tcg_key=tcg)
            candidate = next(item for item in manager.load_candidates() if item["name"] == name)
            hit = {
                "site_key": f"shop_{index}",
                "name": f"店舗{index}",
                "url": f"https://example.com/{index}",
                "retailer_verified": True,
                "seller": f"店舗{index}",
                **evidence,
            }
            manager.update_search_result(
                candidate["id"], hits=[hit], messages=["取得成功"]
            )

        products = ProductStore(self.root).load_products()
        self.assertEqual(4, len(products))
        self.assertTrue(all(product.get("sites") for product in products))
        self.assertEqual(
            {"pokemon", "onepiece", "gundam", "yugioh"},
            {product["tcg_key"] for product in products},
        )

        rows = self._dashboard().build(show_ended=True)["rows"]
        self.assertEqual(4, len(rows))
        self.assertEqual(
            {"pokemon", "onepiece", "gundam", "yugioh"},
            {row["tcg_key"] for row in rows},
        )
        self.assertTrue(all(row["application_url"] for row in rows))

    def test_candidate_or_product_page_without_application_evidence_is_hidden(self):
        manager = CandidateManager(self.root)
        manager.add_manual_candidate("候補止まり商品", tcg_key="one-piece")
        candidate = manager.load_candidates()[0]
        manager.update_search_result(
            candidate["id"], hits=[], messages=["販売・抽選情報は未検出"]
        )
        self.assertEqual([], ProductStore(self.root).load_products())

        store = ProductStore(self.root)
        store._save_product_file([{
            "id": "product-only",
            "name": "通常販売商品",
            "tcg_key": "gundam",
            "sites": [{
                "name": "通常店舗",
                "url": "https://example.com/product/1",
                "product_url": "https://example.com/product/1",
                "status": "商品掲載あり",
            }],
        }])
        self.assertEqual([], self._dashboard().build(show_ended=True)["rows"])

    def test_application_url_or_period_is_application_evidence(self):
        for site in (
            {"application_url": "https://example.com/apply"},
            {"application_period": "2099/08/01～2099/08/10", "url": "https://example.com/period"},
            {"order_period": "2099/08/01～2099/08/10", "url": "https://example.com/order"},
        ):
            with self.subTest(site=site):
                normalized = normalize_application_site(site)
                self.assertTrue(has_application_evidence(normalized))
                self.assertTrue(normalized.get("application_url"))

    def test_tcg_key_variants_are_normalized(self):
        cases = (
            ({"tcg_key": "ONE_PIECE"}, "onepiece"),
            ({"tcg": "Yu Gi Oh!"}, "yugioh"),
            ({"category": "ガンダムカードゲーム"}, "gundam"),
            ({"category": "Pokémon Card Game"}, "pokemon"),
        )
        for record, expected in cases:
            with self.subTest(record=record):
                self.assertEqual(expected, normalize_record(record)[0]["tcg_key"])

    def test_retail_search_normalizes_tcg_before_plugin_selection(self):
        manager = RetailSearchManager()
        manager._search_yodobashi = lambda _candidate: ([], "ok")
        manager.store_candidates.save_candidates = lambda: None
        with patch(
            "core.retail_search_manager.enabled_plugins_for_tcg",
            return_value=[],
        ) as enabled:
            manager.search_candidate({"name": "商品", "category": "ONE_PIECE"})
        enabled.assert_called_once_with("onepiece")


if __name__ == "__main__":
    unittest.main()
