from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PySide6.QtWidgets import QApplication, QLabel, QPushButton


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "app"))

from core.pokemon_official_extractor import PokemonOfficialExtractor
from core.product_record_policy import is_product_record, product_records
from core.source_manager import SourceManager
from core.x_monitoring_status import XMonitoringStatus
from ui.application_dashboard_page import ApplicationRow
from ui.product_page import ProductCard


class ProductApplicationSeparationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_application_article_is_hidden_without_mutating_saved_record(self):
        application = {
            "id": "retail_application_1", "name": "再入荷商品の抽選販売について",
            "source_type": "retail_search", "product_kind": "その他",
            "sites": [{"application_url": "https://shop.example/apply"}],
        }
        product = {
            "id": "m6a", "name": "拡張パック「30th CELEBRATION」",
            "source_type": "pokemon_official_catalog", "product_kind": "拡張パック",
            "official_product_id": "m6a", "sites": [],
        }
        records = [application, product]
        self.assertFalse(is_product_record(application))
        self.assertEqual([product], product_records(records))
        self.assertEqual("https://shop.example/apply", records[0]["sites"][0]["application_url"])

    def test_product_card_does_not_render_store_or_application_controls(self):
        product = {
            "id": "m6a", "name": "拡張パック「30th CELEBRATION」",
            "tcg_key": "pokemon", "tcg": "ポケモンカード", "status": "発売予定",
            "release_date": "2026-09-16", "reference_price": 360,
            "sites": [{"name": "応募店舗", "application_url": "https://shop.example/apply"}],
        }
        card = ProductCard(product, Mock(root=Path(tempfile.gettempdir())), Mock(), Mock())
        text = "\n".join(label.text() for label in card.findChildren(QLabel))
        buttons = [button.text() for button in card.findChildren(QPushButton)]
        self.assertNotIn("応募店舗", text)
        self.assertFalse(any("応募" in value for value in buttons))
        card.close()


class SalesModePresentationTest(unittest.TestCase):
    def test_verified_modes_have_clear_labels_and_unknown_stays_unknown(self):
        self.assertEqual("🏪 店舗販売", ApplicationRow._sales_mode_label("STORE"))
        self.assertEqual("🌐 ネット販売", ApplicationRow._sales_mode_label("ONLINE"))
        self.assertEqual("🏪🌐 店舗＋ネット", ApplicationRow._sales_mode_label("HYBRID"))
        self.assertEqual("販売方法 未確認", ApplicationRow._sales_mode_label("UNKNOWN"))
        self.assertEqual("販売方法 未確認", ApplicationRow._sales_mode_label("unexpected"))


class XStatusTest(unittest.TestCase):
    def test_missing_token_is_visible_and_never_starts_network(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {"POKEYOYA_X_BEARER_TOKEN": ""}, clear=False
        ), patch("urllib.request.OpenerDirector.open") as open_request:
            summary = XMonitoringStatus(Path(directory)).summary()
        self.assertEqual("未設定", summary["state"])
        self.assertIn("秘密情報を同梱しません", summary["message"])
        open_request.assert_not_called()


class Pokemon30thTest(unittest.TestCase):
    def test_30th_index_is_a_default_periodic_official_source(self):
        source = next(
            item for item in SourceManager.DEFAULT_SOURCES
            if item["url"] == "https://www.30th.pokemon-card.com/product"
        )
        self.assertEqual("pokemon", source["tcg_key"])
        self.assertEqual(600, SourceManager.CACHE_TTL_SECONDS)

    def test_live_order_product_block_has_name_date_price_and_no_application(self):
        html = '''<html><head><meta property="og:title" content="拡張パック『30th CELEBRATION』"><meta property="og:image" content="/m6a.jpg"></head><body>
        商品名 ポケモンカードゲーム MEGA 拡張パック 「30th CELEBRATION」
        発売日 2026年9月16日（水） 希望小売価格 360円（税込） 内容物 キラカード6枚入り
        </body></html>'''
        products = PokemonOfficialExtractor().extract_detail_products(
            html, "https://www.30th.pokemon-card.com/product/m6a", "30周年公式"
        )
        self.assertEqual(1, len(products))
        self.assertEqual("拡張パック「30th CELEBRATION」", products[0]["name"])
        self.assertEqual("2026-09-16", products[0]["release_date"])
        self.assertEqual(360, products[0]["reference_price"])
        self.assertEqual("m6a", products[0]["official_product_id"])
        self.assertNotIn("application_url", products[0])


if __name__ == "__main__":
    unittest.main()
