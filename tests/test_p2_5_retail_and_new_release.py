from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

from PySide6.QtWidgets import QApplication, QPushButton


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
sys.path.insert(0, str(APP_DIR))

from core.application_dashboard import ApplicationDashboard
from core.candidate_manager import CandidateManager
from core.retail_price_policy import RetailPricePolicy
from core.retail_search_manager import RetailSearchManager
from core.safe_product_url import can_open_product_url, validate_product_url
from core.store_candidate_manager import StoreCandidateManager
from core.product_store import ProductStore
from ui.application_dashboard_page import ApplicationRow


class RetailPricePolicyTest(unittest.TestCase):
    def setUp(self):
        self.candidate = {
            "name": "遊戯王 ブースターパック TEST",
            "product_kind": "ブースターパック",
            "reference_price": 5400,
        }
        self.offer = {
            "site_key": "biccamera",
            "site_name": "ビックカメラ",
            "retailer_verified": True,
            "seller": "ビックカメラ",
        }

    def test_regular_and_discount_prices_are_accepted(self):
        for price in (5400, 4980):
            with self.subTest(price=price):
                result = RetailPricePolicy.evaluate(
                    self.candidate, {**self.offer, "sale_price": price}
                )
                self.assertTrue(result["accepted"])
                self.assertTrue(result["usable_for_price"])

    def test_premium_price_is_rejected(self):
        result = RetailPricePolicy.evaluate(
            self.candidate, {**self.offer, "sale_price": 9800}
        )
        self.assertFalse(result["accepted"])
        self.assertIn("基準価格", result["exclusion_reason"])

    def test_amazon_third_party_is_rejected(self):
        result = RetailPricePolicy.evaluate(self.candidate, {
            "site_key": "amazon_jp", "retailer_verified": True,
            "seller": "第三者ショップ", "shipped_by": "Amazon.co.jp",
            "sale_price": 5400,
        })
        self.assertFalse(result["accepted"])
        self.assertIn("第三者", result["exclusion_reason"])

    def test_amazon_sold_and_shipped_by_amazon_is_accepted(self):
        result = RetailPricePolicy.evaluate(self.candidate, {
            "site_key": "amazon_jp", "retailer_verified": True,
            "seller": "Amazon.co.jp", "shipped_by": "Amazon.co.jp",
            "sale_price": 5400,
        })
        self.assertTrue(result["accepted"])

    def test_used_bundle_overseas_and_auction_are_rejected(self):
        for text in ("中古 開封済み", "3BOXセット販売", "海外版", "オークション入札"):
            with self.subTest(text=text):
                result = RetailPricePolicy.evaluate(
                    self.candidate, {**self.offer, "text": text, "sale_price": 4000}
                )
                self.assertFalse(result["accepted"])

    def test_unknown_reference_price_never_becomes_minimum_price(self):
        result = RetailPricePolicy.evaluate(
            {"product_kind": "その他"}, {**self.offer, "sale_price": 9800}
        )
        self.assertTrue(result["accepted"])
        self.assertEqual(result["price_status"], "価格未確認")
        self.assertFalse(result["usable_for_price"])

    def test_tax_exclusive_is_normalized_and_shipping_is_not_price(self):
        self.assertEqual(
            RetailPricePolicy.normalize_price("5,000円", tax_included=False), 5500
        )
        result = RetailPricePolicy.evaluate(
            self.candidate, {**self.offer, "text": "送料 550円"}
        )
        self.assertIsNone(result["sale_price"])


def _hit(site_key: str, name: str, url: str, status: str = "予約受付中") -> dict:
    return {
        "site_key": site_key, "name": name, "url": url, "status": status,
        "confidence": 0.95, "retailer_verified": True, "seller": name,
        "text": "予約受付中 販売価格 5,400円", "sale_price": 5400,
    }


class YugiohRetailSearchTest(unittest.TestCase):
    def test_multiple_non_amazon_stores_and_statuses(self):
        manager = RetailSearchManager()
        yodobashi = _hit("yodobashi_retail", "ヨドバシ", "https://www.yodobashi.com/product/a")
        bic = _hit("biccamera", "ビックカメラ", "https://www.biccamera.com/item/a")
        joshin = _hit("joshin", "ジョーシン", "https://joshinweb.jp/item/a", "抽選受付中")
        plugins = [
            {"id": "biccamera", "name": "ビックカメラ", "mode": "search_page", "source": "builtin"},
            {"id": "joshin", "name": "ジョーシン", "mode": "search_page", "source": "builtin"},
        ]
        with patch.object(manager, "_search_yodobashi", return_value=([yodobashi], "ヨドバシ: 1件")), patch(
            "core.retail_search_manager.enabled_plugins_for_tcg", return_value=plugins
        ), patch.object(manager, "_search_generic_plugin", side_effect=[([bic], "ビック: 1件"), ([joshin], "ジョーシン: 1件")]):
            hits, _ = manager.search_candidate({
                "name": "遊戯王 TEST", "tcg_key": "yugioh",
                "product_kind": "ブースターパック", "reference_price": 5400,
            })
        self.assertEqual({hit["site_key"] for hit in hits}, {"yodobashi_retail", "biccamera", "joshin"})
        self.assertEqual(manager.last_diagnostics["searched_store_count"], 3)

    def test_duplicate_same_store_and_url_is_removed(self):
        manager = RetailSearchManager()
        hit = _hit("biccamera", "ビックカメラ", "https://www.biccamera.com/item/a")
        with patch.object(manager, "_search_yodobashi", return_value=([], "なし")), patch(
            "core.retail_search_manager.enabled_plugins_for_tcg",
            return_value=[{"id": "biccamera", "name": "ビック", "mode": "search_page", "source": "builtin"}],
        ), patch.object(manager, "_search_generic_plugin", return_value=([hit, dict(hit)], "2件")):
            hits, _ = manager.search_candidate({"name": "遊戯王 TEST", "tcg_key": "yugioh"})
        self.assertEqual(len(hits), 1)

    def test_resale_is_excluded_and_reason_is_diagnostic(self):
        manager = RetailSearchManager()
        hit = _hit("biccamera", "ビック", "https://www.biccamera.com/item/a")
        hit["text"] = "中古 プレミア価格"
        with patch.object(manager, "_search_yodobashi", return_value=([hit], "1件")), patch(
            "core.retail_search_manager.enabled_plugins_for_tcg", return_value=[]
        ):
            hits, messages = manager.search_candidate({"name": "遊戯王 TEST", "tcg_key": "yugioh"})
        self.assertEqual(hits, [])
        self.assertTrue(any(message.startswith("除外:") for message in messages))

    def test_external_store_is_candidate_not_direct_hit(self):
        manager = RetailSearchManager()
        external = _hit("new_shop", "新店舗", "https://new-shop.example/item")
        manager.store_candidates = Mock()
        manager.store_candidates.add_candidate.return_value = True
        plugin = {"id": "new_shop", "name": "新店舗", "mode": "search_page", "source": "external"}
        with patch.object(manager, "_search_yodobashi", return_value=([], "なし")), patch(
            "core.retail_search_manager.enabled_plugins_for_tcg", return_value=[plugin]
        ), patch.object(manager, "_search_generic_plugin", return_value=([external], "1件")):
            hits, _ = manager.search_candidate({"name": "遊戯王 TEST", "tcg_key": "yugioh"})
        self.assertEqual(hits, [])
        self.assertEqual(manager.last_diagnostics["new_store_candidate_count"], 1)


class ExistingRetailProductFilterTest(unittest.TestCase):
    def test_legacy_resale_only_product_is_hidden(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("core.product_store.app_root", return_value=Path(directory)):
                store = ProductStore()
            store.products_path.parent.mkdir(parents=True)
            store.products_path.write_text(json.dumps([{
                "id": "legacy", "name": "商品", "tcg_key": "yugioh",
                "source_type": "retail_search", "reference_price": 5400,
                "sites": [{"site_key": "amazon_jp", "name": "Amazon", "seller": "第三者", "shipped_by": "Amazon.co.jp", "sale_price": 9800}],
            }], ensure_ascii=False), encoding="utf-8")
            self.assertEqual(store.load_products(), [])
            self.assertIn("第三者", store.last_excluded_retail_offers[0]["reason"])

    def test_legacy_verified_discount_remains(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("core.product_store.app_root", return_value=Path(directory)):
                store = ProductStore()
            store.products_path.parent.mkdir(parents=True)
            store.products_path.write_text(json.dumps([{
                "id": "legacy", "name": "商品", "tcg_key": "yugioh",
                "source_type": "retail_search", "reference_price": 5400,
                "sites": [{"site_key": "biccamera", "name": "ビック", "sale_price": 4980}],
            }], ensure_ascii=False), encoding="utf-8")
            products = store.load_products()
            self.assertEqual(products[0]["sites"][0]["sale_price"], 4980)


class StoreCandidateTest(unittest.TestCase):
    def test_candidate_is_metadata_only_and_deduplicated(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("core.store_candidate_manager.app_root", return_value=Path(directory)):
                manager = StoreCandidateManager()
            hit = {"name": "新店舗", "host": "shop.example", "url": "https://shop.example/item/1"}
            self.assertTrue(manager.add_candidate(hit))
            self.assertFalse(manager.add_candidate(hit))
            saved = manager.load()[0]
            self.assertEqual(saved["status"], "管理者確認待ち")
            self.assertNotIn("price", saved)


class NewReleasePropagationTest(unittest.TestCase):
    def _manager(self, directory: str) -> CandidateManager:
        with patch("core.candidate_manager.app_root", return_value=Path(directory)):
            return CandidateManager()

    def _official(self, tcg: str, kind: str, days: int = 30) -> dict:
        host = "www.onepiece-cardgame.com" if tcg == "onepiece" else "www.gundam-gcg.com"
        return {
            "name": f"{tcg} 新商品", "tcg_key": tcg,
            "release_date": (date.today() + timedelta(days=days)).isoformat(),
            "product_kind": kind, "official_url": f"https://{host}/products/new.html",
            "candidate_confidence": 1.0, "candidate_reasons": ["日本公式"],
            "source_type": f"{tcg}_official", "sites": [{"url": f"https://{host}/products/new.html"}],
        }

    def test_onepiece_and_gundam_flow_with_date_kind_and_tcg(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = self._manager(directory)
            products = [
                self._official("onepiece", "エクストラブースター"),
                self._official("gundam", "ブースターパック"),
            ]
            candidates, added = manager.merge_official_candidates(
                products, source_id="official", source_name="公式", source_url="https://example.com"
            )
            self.assertEqual(added, 2)
            self.assertEqual({item["tcg_key"] for item in candidates}, {"onepiece", "gundam"})
            self.assertTrue(all(item["release_date"] and item["product_kind"] for item in candidates))

    def test_old_event_invalid_date_and_existing_product_are_excluded(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = self._manager(directory)
            old = self._official("onepiece", "ブースターパック", days=-90)
            event = self._official("gundam", "その他")
            event["official_url"] = "https://www.gundam-gcg.com/jp/event/new.html"
            invalid = self._official("gundam", "ブースターパック")
            invalid["release_date"] = "未定"
            existing = self._official("onepiece", "ブースターパック")
            manager.products_path.parent.mkdir(parents=True, exist_ok=True)
            manager.products_path.write_text(json.dumps([existing], ensure_ascii=False), encoding="utf-8")
            _, added = manager.merge_official_candidates(
                [old, event, invalid, existing], source_id="official", source_name="公式", source_url="https://example.com"
            )
            self.assertEqual(added, 0)

    def test_accessories_are_not_new_card_releases(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = self._manager(directory)
            onepiece = self._official("onepiece", "その他")
            onepiece["name"] = "オフィシャルカードスリーブ"
            gundam = self._official("gundam", "その他")
            gundam["name"] = "オフィシャルプレイマット"
            _, added = manager.merge_official_candidates(
                [onepiece, gundam], source_id="official", source_name="公式", source_url="https://example.com"
            )
            self.assertEqual(added, 0)


class ApplicationUrlSafetyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_https_allowlist_and_unsafe_schemes(self):
        self.assertTrue(can_open_product_url("https://www.yodobashi.com/product/1"))
        for url in ("http://www.yodobashi.com/x", "file:///tmp/x", "javascript:alert(1)", "data:text/plain,x", "https://evil.example/x"):
            with self.subTest(url=url):
                self.assertFalse(can_open_product_url(url))
                with self.assertRaises(ValueError):
                    validate_product_url(url)

    def test_receipt_or_order_query_is_rejected(self):
        self.assertFalse(can_open_product_url("https://www.yodobashi.com/x?order_number=SECRET"))
        self.assertTrue(can_open_product_url("https://joshinweb.jp/search/?KEY=yugioh"))

    def test_dashboard_has_separate_product_and_application_buttons(self):
        row = {
            "product_name": "商品", "application_state": "応募済み", "tcg": "遊戯王OCG",
            "site_name": "店舗", "product_url": "https://www.yugioh-card.com/japan/products/a/",
            "application_url": "https://www.yodobashi.com/product/a", "site_url": "https://www.yodobashi.com/product/a",
        }
        card = ApplicationRow(row, Mock(), lambda: None, lambda _row: None)
        buttons = {button.text(): button for button in card.findChildren(QPushButton)}
        self.assertTrue(buttons["商品ページを開く"].isEnabled())
        self.assertTrue(buttons["応募ページを開く"].isEnabled())

    def test_missing_url_disables_both_buttons(self):
        card = ApplicationRow({"product_name": "商品"}, Mock(), lambda: None, lambda _row: None)
        buttons = {button.text(): button for button in card.findChildren(QPushButton)}
        self.assertFalse(buttons["商品ページを開く"].isEnabled())
        self.assertFalse(buttons["応募ページを開く"].isEnabled())

    def test_dashboard_propagates_distinct_urls(self):
        dashboard = ApplicationDashboard()
        dashboard.store.load_products = lambda: [{
            "id": "p", "name": "商品", "tcg_key": "yugioh",
            "official_url": "https://www.yugioh-card.com/japan/products/a/",
            "sites": [{"site_key": "shop", "url": "https://www.yodobashi.com/product/a"}],
        }]
        row = dashboard.build()["rows"][0]
        self.assertNotEqual(row["product_url"], row["application_url"])


if __name__ == "__main__":
    unittest.main()
