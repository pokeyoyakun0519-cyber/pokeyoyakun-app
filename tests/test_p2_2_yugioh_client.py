from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
sys.path.insert(0, str(APP))

from PySide6.QtWidgets import QApplication, QLabel

from core.candidate_manager import CandidateManager
from core.gmail_result_service import GmailResultService
from core.pokemon_official_extractor import PokemonOfficialExtractor
from core.public_roadmap import TCG_LABELS as ROADMAP_TCG_LABELS
from core.retail_plugin_registry import BUILTIN_RETAIL_PLUGINS
from core.retail_search_manager import RetailSearchManager
from core.source_manager import SourceManager
from core.source_product_extractor import SourceProductExtractor
from core.tcg_categories import categories, display_name, normalize_key
from core.yugioh_official_extractor import YugiohOfficialExtractor
from ui.candidates_page import CandidateCard
from ui.product_detail_dialog import ProductDetailDialog
from ui.product_page import ProductCard
from ui.sources_page import SourcesPage
from ui.tcg_category_tabs import category_counts, filter_items_by_category


DETAIL_URL = "https://www.yugioh-card.com/japan/products/dbgv/"
DETAIL_HTML = """
<!doctype html><html><body>
<h1>遊戯王OCGデュエルモンスターズ デッキビルドパック
グロリアス・ヴィクターズ</h1>
<p>2026年8月22日(土) 発売</p>
<p>デッキビルドパック</p>
<p>一部店舗では予約・抽選販売となります。</p>
</body></html>
"""


class YugiohClientCoreTest(unittest.TestCase):
    def setUp(self):
        self.extractor = YugiohOfficialExtractor()

    def test_categories_include_yugioh_without_changing_existing_keys(self):
        self.assertEqual(
            [item.key for item in categories()],
            ["pokemon", "onepiece", "yugioh", "gundam", "other"],
        )
        self.assertEqual(display_name("yugioh"), "遊戯王OCG")
        self.assertEqual(normalize_key("", "遊戯王")[0], "yugioh")
        self.assertEqual(display_name("pokemon"), "ポケモンカード")

    def test_category_filter_never_mixes_yugioh_and_pokemon(self):
        items = [
            {"id": "p", "tcg_key": "pokemon", "tcg": "ポケモンカード"},
            {"id": "y", "tcg_key": "yugioh", "tcg": "遊戯王OCG"},
            {"id": "o", "tcg_key": "onepiece", "tcg": "ワンピースカード"},
        ]
        self.assertEqual(
            [item["id"] for item in filter_items_by_category(items, "yugioh")],
            ["y"],
        )
        counts = category_counts(items)
        self.assertEqual(counts["pokemon"], 1)
        self.assertEqual(counts["yugioh"], 1)
        self.assertEqual(counts["onepiece"], 1)

    def test_official_list_accepts_only_yugioh_product_links(self):
        html = f"""
        <a href="/japan/products/dbgv/">遊戯王OCG 2026年8月22日発売</a>
        <a href="{DETAIL_URL}#top">重複</a>
        <a href="/japan/event/duelist/">大会</a>
        <a href="https://evil.example/japan/products/fake/">外部</a>
        """
        self.assertEqual(
            self.extractor.collect_candidate_links(
                html, "https://www.yugioh-card.com/japan/products/"
            ),
            [{"url": DETAIL_URL, "text": "遊戯王OCG 2026年8月22日発売"}],
        )

    def test_official_detail_extracts_yugioh_product(self):
        product = self.extractor.extract_detail_products(
            DETAIL_HTML, DETAIL_URL, "遊戯王OCG公式"
        )[0]
        self.assertEqual(product["tcg_key"], "yugioh")
        self.assertEqual(product["tcg"], "遊戯王OCG")
        self.assertEqual(product["release_date"], "2026-08-22")
        self.assertEqual(product["product_kind"], "デッキビルドパック")
        self.assertTrue(product["reservation_related"])
        self.assertTrue(product["lottery_related"])

    def test_yugioh_candidate_and_product_never_fall_back_to_pokemon(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("core.candidate_manager.app_root", return_value=Path(directory)):
                manager = CandidateManager()
            discovered = self.extractor.extract_detail_products(
                DETAIL_HTML, DETAIL_URL, "遊戯王OCG公式"
            )
            candidates, added = manager.merge_official_candidates(
                discovered,
                source_id="yugioh_official",
                source_name="遊戯王OCG公式",
                source_url=SourceManager.YUGIOH_OFFICIAL_PRODUCTS_URL,
            )
            self.assertEqual(added, 1)
            self.assertEqual(candidates[0]["tcg_key"], "yugioh")
            manager.update_search_result(
                candidates[0]["id"],
                hits=[
                    {
                        "site_key": "biccamera",
                        "name": "ビックカメラ",
                        "status": "予約受付中",
                    }
                ],
                messages=[],
            )
            products = manager._load_list(manager.products_path)
            self.assertEqual(products[0]["tcg_key"], "yugioh")
            self.assertNotEqual(products[0]["tcg_key"], "pokemon")

    def test_manual_candidate_preserves_existing_tcg_categories(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("core.candidate_manager.app_root", return_value=Path(directory)):
                manager = CandidateManager()
            manager.add_manual_candidate("遊戯王商品", tcg_key="yugioh")
            manager.add_manual_candidate("ポケモン商品", tcg_key="pokemon")
            values = {item["name"]: item["tcg_key"] for item in manager.load_candidates()}
            self.assertEqual(values["遊戯王商品"], "yugioh")
            self.assertEqual(values["ポケモン商品"], "pokemon")

    def test_generic_official_source_does_not_default_to_pokemon(self):
        html = """
        <article><h2>ブースターパック「テスト・ブレイカー」30種</h2>
        <p>2026年9月1日発売</p></article>
        """
        products = SourceProductExtractor().extract(
            html, "https://cards.example/products", "汎用公式ソース"
        )
        self.assertTrue(products)
        self.assertEqual(products[0]["tcg_key"], "other")
        self.assertNotEqual(products[0]["tcg_key"], "pokemon")

    def test_source_manager_saves_yugioh_key_without_touching_user_data(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("core.source_manager.app_root", return_value=Path(directory)):
                manager = SourceManager()
            manager.add_source(
                "遊戯王OCG公式",
                SourceManager.YUGIOH_OFFICIAL_PRODUCTS_URL,
                "yugioh",
            )
            source = next(
                item
                for item in manager.load_sources()
                if item["url"] == SourceManager.YUGIOH_OFFICIAL_PRODUCTS_URL
            )
            self.assertEqual(source["tcg_key"], "yugioh")
            self.assertEqual(source["tcg"], "遊戯王OCG")

    def test_gmail_yugioh_classification_and_existing_pokemon_regression(self):
        service = GmailResultService.__new__(GmailResultService)
        yugioh = service._judge_message(
            {
                "subject": "遊戯王OCG 当選のお知らせ",
                "from": "shop",
                "date": "",
                "body": "抽選結果",
            },
            [],
        )
        pokemon = service._judge_message(
            {
                "subject": "ポケモンカード 当選のお知らせ",
                "from": "shop",
                "date": "",
                "body": "抽選結果",
            },
            [],
        )
        unknown = service._judge_message(
            {
                "subject": "商品A 抽選結果",
                "from": "shop",
                "date": "",
                "body": "",
            },
            [],
        )
        self.assertEqual(yugioh["tcg_key"], "yugioh")
        self.assertNotEqual(yugioh["tcg_key"], "pokemon")
        self.assertEqual(pokemon["tcg_key"], "pokemon")
        self.assertEqual(unknown["tcg_key"], "other")

    def test_verified_retail_plugins_support_yugioh(self):
        by_id = {plugin["id"]: plugin for plugin in BUILTIN_RETAIL_PLUGINS}
        for plugin_id in (
            "amazon_jp",
            "yodobashi_lottery",
            "rakuten_books",
            "biccamera",
            "joshin",
            "geo",
        ):
            with self.subTest(plugin_id=plugin_id):
                self.assertIn("yugioh", by_id[plugin_id]["tcg"])

    def test_pokemon_extractor_rejects_yugioh_domain(self):
        links = PokemonOfficialExtractor().collect_candidate_links(
            f'<a href="{DETAIL_URL}">ブースターパック 2026年8月22日発売</a>',
            SourceManager.YUGIOH_OFFICIAL_PRODUCTS_URL,
        )
        self.assertEqual(links, [])

    def test_yugioh_retail_search_never_calls_pokemon_center(self):
        searcher = RetailSearchManager()
        with (
            patch.object(
                searcher,
                "_search_pokemon_center",
                side_effect=AssertionError("遊戯王でポケモンセンターを検索しました"),
            ),
            patch.object(searcher, "_search_yodobashi", return_value=([], "")),
            patch(
                "core.retail_search_manager.enabled_plugins_for_tcg",
                return_value=[],
            ),
        ):
            hits, _messages = searcher.search_candidate(
                {"name": "遊戯王OCG 商品", "tcg_key": "yugioh"}
            )
        self.assertEqual(hits, [])

    def test_popular_roadmap_exposes_yugioh_label(self):
        self.assertEqual(ROADMAP_TCG_LABELS["yugioh"], "遊戯王OCG")


class YugiohClientUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_product_list_and_candidate_cards_show_yugioh(self):
        product = {
            "id": "y1",
            "tcg_key": "yugioh",
            "tcg": "遊戯王OCG",
            "name": "デッキビルドパック",
            "status": "発売予定",
            "release_date": "2026-08-22",
            "sites": [],
        }
        product_card = ProductCard(product, object(), lambda _item: None, lambda: None)
        candidate_card = CandidateCard(
            {**product, "retail_hits": []}, lambda _id: None, lambda _id: None, False
        )
        self.assertTrue(
            any("遊戯王OCG" in label.text() for label in product_card.findChildren(QLabel))
        )
        self.assertTrue(
            any("遊戯王OCG" in label.text() for label in candidate_card.findChildren(QLabel))
        )

    @patch("ui.product_detail_dialog.SiteMasterManager.load_sites", return_value=[])
    def test_product_detail_shows_yugioh(self, _load_sites):
        dialog = ProductDetailDialog(
            {
                "tcg_key": "yugioh",
                "tcg": "遊戯王OCG",
                "name": "遊戯王商品",
                "status": "発売予定",
                "release_date": "2026-08-22",
                "sites": [],
            }
        )
        self.assertTrue(
            any("TCG：遊戯王OCG" in label.text() for label in dialog.findChildren(QLabel))
        )

    @patch("ui.sources_page.SourceManager.load_sources", return_value=[])
    def test_official_source_preset_is_yugioh_https(self, _load_sources):
        page = SourcesPage()
        page.fill_yugioh_official_source()
        self.assertEqual(page.tcg_input.currentData(), "yugioh")
        self.assertEqual(page.url_input.text(), SourceManager.YUGIOH_OFFICIAL_PRODUCTS_URL)
        self.assertTrue(page.url_input.text().startswith("https://"))


if __name__ == "__main__":
    unittest.main()
