from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "app"))

from core.additional_official_extractors import (
    DuelMastersOfficialExtractor,
    MtgOfficialExtractor,
    WeissOfficialExtractor,
)
from core.builtin_store_catalog import load_builtin_store_catalog
from core.retail_plugin_registry import enabled_plugins_for_tcg
from core.retail_search_manager import RetailSearchManager
from core.tcg_categories import normalize_key


class AdditionalOfficialExtractorTest(unittest.TestCase):
    def test_duelmasters_list_extracts_official_product(self):
        html = """
        <div class="itemList01_item expansion">
          <img src="/img/dm26rp1.jpg" alt="DM26-RP1">
          <div class="product_type"><p>拡張パック</p></div>
          <h2 class="title">DM26-RP1 デュエル・マスターズTCG 逆札篇 第1弾</h2>
          <dl><dt>発売日</dt><dd>2026年4月11日（土）</dd></dl>
          <dl><dt>希望小売価格</dt><dd>1BOX 6,000円（税込）</dd></dl>
          <a href="/product/dm26rp1/" class="btn_basic01">商品詳細</a>
        </div></div>
        """
        products = DuelMastersOfficialExtractor().extract_list_products(
            html, "https://dm.takaratomy.co.jp/product/", "DM公式"
        )
        self.assertEqual(len(products), 1)
        self.assertEqual(products[0]["tcg_key"], "duelmasters")
        self.assertEqual(products[0]["release_date"], "2026-04-11")
        self.assertEqual(products[0]["product_code"], "DM26-RP1")
        self.assertEqual(products[0]["msrp"], 6000)

    def test_weiss_list_extracts_official_product(self):
        html = """
        <a href="https://ws-tcg.com/products/bp_rzvol-4/" class="products__link">
          <li class="products__catItem">ブースターパック</li>
          <p class="products__name">「Re:ゼロから始める異世界生活」Vol.4</p>
          <p class="products__salesdate">発売日：2026年7月24日(金)</p>
        </a>
        """
        products = WeissOfficialExtractor().extract_list_products(
            html, "https://ws-tcg.com/products/", "WS公式"
        )
        self.assertEqual(len(products), 1)
        self.assertEqual(products[0]["tcg_key"], "weiss")
        self.assertEqual(products[0]["release_date"], "2026-07-24")
        self.assertEqual(products[0]["product_kind"], "ブースターパック")

    def test_mtg_list_and_detail_extract_release_date(self):
        extractor = MtgOfficialExtractor()
        products = extractor.extract_list_products(
            '<li><a href="/products/0000311/"><img alt="リアリティ・フラクチャー"></a></li>',
            "https://mtg-jp.com/products/index.php",
            "MTG日本公式",
        )
        self.assertEqual(len(products), 1)
        supplement = extractor.supplement_from_detail(
            '<meta property="og:image" content="/img/311.jpg"><p>公式発売日 | 2026年8月7日</p>',
            products[0]["official_url"],
        )
        self.assertEqual(products[0]["tcg_key"], "mtg")
        self.assertEqual(supplement["release_date"], "2026-08-07")
        self.assertEqual(supplement["image_url"], "https://mtg-jp.com/img/311.jpg")

    def test_official_extractors_reject_non_official_hosts(self):
        with self.assertRaises(ValueError):
            DuelMastersOfficialExtractor().validate_japanese_page(
                '<div class="itemList01_item"></div>', "https://example.com/product/"
            )
        with self.assertRaises(ValueError):
            WeissOfficialExtractor().validate_japanese_page(
                '<a class="products__link"></a>', "https://example.com/products/"
            )
        with self.assertRaises(ValueError):
            MtgOfficialExtractor().validate_japanese_page(
                "<html></html>", "https://example.com/products/"
            )


class MultiTcgSourceCoverageTest(unittest.TestCase):
    def test_new_tcg_aliases_are_normalized(self):
        cases = {
            "デュエマ": "duelmasters",
            "Duel Masters": "duelmasters",
            "ヴァイスシュヴァルツ": "weiss",
            "Weiss Schwarz": "weiss",
            "Magic: The Gathering": "mtg",
            "MTG": "mtg",
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(normalize_key(value)[0], expected)

    def test_each_non_pokemon_tcg_has_multiple_enabled_retail_sources(self):
        for tcg_key in (
            "onepiece", "gundam", "yugioh",
            "duelmasters", "weiss", "mtg",
        ):
            with self.subTest(tcg_key=tcg_key):
                plugins = enabled_plugins_for_tcg(tcg_key)
                self.assertGreaterEqual(len(plugins), 3)
                self.assertTrue(any(item["id"] != "amazon_jp" for item in plugins))

    def test_catalog_exposes_explicit_new_tcg_support(self):
        catalog = load_builtin_store_catalog()
        stores = {item["canonical_store_id"]: item for item in catalog["stores"]}
        self.assertIn("duelmasters", stores["takaratomy_mall"]["supported_tcg_keys"])
        self.assertIn("weiss", stores["bushiroad_store"]["supported_tcg_keys"])
        self.assertIn("mtg", stores["hareruya"]["supported_tcg_keys"])

    def test_link_parser_supports_json_ld_products(self):
        html = """
        <script type="application/ld+json">
          {"@context":"https://schema.org","@type":"Product",
           "name":"新商品 BOX","url":"/products/new-box"}
        </script>
        """
        links = RetailSearchManager._json_ld_product_links(
            html, "https://shop.example/products/"
        )
        self.assertEqual(
            links,
            [{"url": "https://shop.example/products/new-box", "text": "新商品 BOX"}],
        )


if __name__ == "__main__":
    unittest.main()
