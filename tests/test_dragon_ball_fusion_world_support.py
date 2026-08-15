import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
sys.path.insert(0, str(APP_DIR))

from core.candidate_manager import CandidateManager
from core.card_labo_parser import CardLaboParser
from core.config_manager import ConfigManager
from core.dragon_ball_fusion_world_official_extractor import (
    DragonBallFusionWorldOfficialExtractor,
)
from core.hobby_station_parser import HobbyStationParser
from core.priority_application_adapters import PremiumBandaiApplicationAdapter
from core.product_master import ProductMasterManager
from core.product_store import ProductStore
from core.retail_plugin_registry import enabled_plugins_for_tcg
from core.setup_coordinator import SUPPORTED_TCG_KEYS
from core.source_manager import SourceManager
from core.tcg_categories import category_for_key, normalize_key
from core.x_recent_search import QUERIES, XRecentSearch


LIST_URL = DragonBallFusionWorldOfficialExtractor.LIST_URL


def product_block(path: str, name: str, date="2026.09.12", price="￥240(税込)"):
    return f'''<li class="prpductListItem cardCol">
      <a href="https://www.dbs-cardgame.com{path}" class="cardLink">
      <img src="/noimage.webp" data-src="/images/item.png" alt="{name}">
      <h3 class="cardText">{name}</h3>
      <dl><dt class="cardInfoTit">発売日</dt><dd class="cardInfoTxt">{date}</dd></dl>
      <dl><dt class="cardInfoTit">メーカー希望小売価格</dt><dd class="cardInfoTxt">{price}</dd></dl>
      </a></li>'''


def page(*released: str, upcoming=()):
    return (
        '<section id="available"><ul class="prpductList">'
        + "".join(released)
        + '</ul></section><section id="comingsoon"><ul class="prpductList">'
        + "".join(upcoming)
        + "</ul></section>"
    )


class DragonBallFusionWorldSupportTest(unittest.TestCase):
    def setUp(self):
        self.extractor = DragonBallFusionWorldOfficialExtractor()

    def test_category_aliases_and_formal_identifier(self):
        values = (
            "DRAGON_BALL_FUSION_WORLD", "DBSCG FUSION WORLD", "DBS FW",
            "ドラゴンボールスーパーカードゲーム フュージョンワールド",
            "フュージョンワールド",
        )
        for value in values:
            with self.subTest(value=value):
                self.assertEqual("dragon_ball_fusion_world", normalize_key(value)[0])
        self.assertEqual(
            "ドラゴンボールSCG フュージョンワールド",
            category_for_key("dragon_ball_fusion_world").display_name,
        )

    def test_setup_and_default_config_enable_tcg(self):
        self.assertIn("dragon_ball_fusion_world", SUPPORTED_TCG_KEYS)
        with tempfile.TemporaryDirectory() as directory:
            config = ConfigManager(Path(directory)).load()
        self.assertTrue(config["games"]["dragon_ball_fusion_world"])

    def test_official_booster_fields_are_extracted(self):
        html = page(product_block(
            "/fw/jp/products/01_422.html",
            "ブースターパック BRIGHTNESS OF HOPE [FB11]",
        ))
        item = self.extractor.extract_list_products(html, LIST_URL, "公式")[0]
        self.assertEqual("DRAGON_BALL_FUSION_WORLD", item["tcg_identifier"])
        self.assertEqual("01_422", item["official_product_id"])
        self.assertEqual("FB11", item["product_code"])
        self.assertEqual("", item["jan"])
        self.assertEqual("2026-09-12", item["release_date"])
        self.assertEqual(240, item["msrp"])
        self.assertEqual("ブースターパック", item["product_kind"])
        self.assertTrue(item["image_url"].endswith("/images/item.png"))

    def test_upcoming_is_classified_from_official_section(self):
        html = page(upcoming=(product_block(
            "/fw/jp/products/01_477.html",
            "ブースターパック REACH THE GOD [FB12]",
            "2026.12.12",
        ),))
        item = self.extractor.extract_list_products(html, LIST_URL, "公式")[0]
        self.assertEqual("UPCOMING", item["product_status"])
        self.assertEqual("発売予定", item["status"])

    def test_supported_product_types_are_included(self):
        rows = (
            product_block("/fw/jp/products/01_5.html", "ブースターパック 覚醒の鼓動 [FB01]"),
            product_block("/fw/jp/products/01_1.html", "スタートデッキ 孫悟空 [FS01]"),
            product_block("/fw/jp/products/01_190.html", "MANGA BOOSTER 01 [SB01]"),
            product_block("/fw/jp/products/01_401.html", "STORY BOOSTER 01 [ST01]"),
            product_block("/fw/jp/products/02_160.html", "プレミアムカードコレクション02"),
            product_block("/fw/jp/products/01_348.html", "2nd ANNIVERSARY SET"),
        )
        items = self.extractor.extract_list_products(page(*rows), LIST_URL, "公式")
        self.assertEqual(6, len(items))
        self.assertEqual(
            {"ブースターパック", "スタートデッキ", "プレミアム商品"},
            {item["product_kind"] for item in items},
        )

    def test_supplies_are_excluded(self):
        names = (
            "オフィシャルカードスリーブ04", "オフィシャルプレイマット",
            "カードケース&カードスリーブセット", "チャンピオンシップセット 01",
            "フュージョンワールド フィギュア", "公式グッズ",
        )
        html = page(*(
            product_block(f"/fw/jp/products/02_{index}.html", name)
            for index, name in enumerate(names, 1)
        ))
        self.assertEqual([], self.extractor.extract_list_products(html, LIST_URL, "公式"))

    def test_other_dragon_ball_products_are_not_misclassified(self):
        names = (
            "ドラゴンボールスーパーダイバーズ アドバンスパック",
            "ドラゴンボールZ ゲームソフト", "ドラゴンボール超 フィギュア",
            "大会情報", "カードリスト", "キャンペーンニュース",
        )
        html = page(*(
            product_block(f"/fw/jp/products/01_{index + 500}.html", name)
            for index, name in enumerate(names)
        ))
        self.assertEqual([], self.extractor.extract_list_products(html, LIST_URL, "公式"))

    def test_month_only_date_is_not_invented(self):
        html = page(product_block(
            "/fw/jp/products/02_160.html", "プレミアムカードコレクション02", "2026年3月",
        ))
        item = self.extractor.extract_list_products(html, LIST_URL, "公式")[0]
        self.assertEqual("", item["release_date"])
        self.assertEqual("2026年3月", item["release_date_text"])
        self.assertEqual("month", item["release_date_precision"])

    def test_non_official_or_non_japanese_page_is_rejected(self):
        html = page(product_block("/fw/jp/products/01_5.html", "商品 [FB01]"))
        for url in ("http://www.dbs-cardgame.com/fw/jp/products/", "https://example.com/fw/jp/products/"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                self.extractor.extract_list_products(html, url, "公式")

    def test_source_manager_registers_official_provider(self):
        source = next(
            item for item in SourceManager.DEFAULT_SOURCES
            if item["tcg_key"] == "dragon_ball_fusion_world"
        )
        self.assertEqual(LIST_URL, source["url"])
        self.assertTrue(SourceManager._is_dragon_ball_fusion_world_official(LIST_URL))
        self.assertFalse(SourceManager._is_dragon_ball_fusion_world_official(
            "https://www.dbs-cardgame.com/fw/digital_member/"
        ))

    def test_source_manager_fetches_pages_once_and_deduplicates(self):
        html = page(product_block(
            "/fw/jp/products/01_422.html", "ブースターパック BRIGHTNESS OF HOPE [FB11]",
        ))
        manager = SourceManager()
        with patch.object(manager, "_fetch_page", return_value={
            "ok": True, "html": html, "url": LIST_URL, "status": "ok", "title": "products",
        }), patch("core.source_manager.time.sleep"):
            products, pages, duplicates = manager._extract_dragon_ball_fusion_world_official_products(
                html, LIST_URL, "公式"
            )
        self.assertEqual(1, len(products))
        self.assertEqual(6, pages)
        self.assertEqual(5, duplicates)

    def test_same_official_id_matches_despite_title_difference(self):
        existing = {"name": "FB11", "tcg_key": "dragon_ball_fusion_world",
                    "product_kind": "ブースターパック", "official_product_id": "01_422"}
        incoming = {**existing, "name": "ブースターパック BRIGHTNESS OF HOPE [FB11]"}
        self.assertEqual((0, "identifier"), ProductMasterManager.find_match([existing], incoming))

    def test_different_official_ids_never_merge(self):
        first = {"id": "a", "name": "同名商品", "tcg_key": "dragon_ball_fusion_world",
                 "product_kind": "ブースターパック", "official_product_id": "01_422", "sites": []}
        second = {**first, "id": "b", "official_product_id": "01_477"}
        self.assertEqual((None, "identifier_conflict"), ProductMasterManager.find_match([first], second))

    def test_repeated_store_sync_is_idempotent(self):
        product = {"id": "a", "name": "FB11", "tcg_key": "dragon_ball_fusion_world",
                   "product_kind": "ブースターパック", "official_product_id": "01_422", "sites": []}
        with tempfile.TemporaryDirectory() as directory:
            store = ProductStore(Path(directory))
            store.merge_discovered_products([product])
            store.merge_discovered_products([product])
            loaded = store.load_products()
        self.assertEqual(1, len(loaded))
        self.assertEqual(1, len({item["product_id"] for item in loaded}))

    def test_store_parsers_require_fusion_world_context(self):
        text = "ドラゴンボールスーパーカードゲーム フュージョンワールド FB11 WEB抽選"
        self.assertEqual(("dragon_ball_fusion_world", ""), CardLaboParser.detect_tcg(text))
        self.assertEqual("dragon_ball_fusion_world", HobbyStationParser.detect_tcg(text))
        self.assertNotEqual("dragon_ball_fusion_world", CardLaboParser.detect_tcg("ドラゴンボール超 フィギュア")[0])
        self.assertNotEqual("dragon_ball_fusion_world", HobbyStationParser.detect_tcg("スーパーダイバーズ 大会"))

    def test_required_retail_plugins_are_enabled(self):
        ids = {item["id"] for item in enabled_plugins_for_tcg("dragon_ball_fusion_world")}
        self.assertTrue({
            "amazon_jp", "yodobashi_lottery", "rakuten_books", "biccamera", "joshin",
            "card_labo", "hobby_station", "premium_bandai",
        } <= ids)

    def test_premium_bandai_is_candidate_until_period_verified(self):
        self.assertEqual(
            "https://p-bandai.jp/carddas/a0008/b0003/dbscgfw/list-da20-n0/",
            PremiumBandaiApplicationAdapter.DRAGON_BALL_FUSION_WORLD_INDEX_URL,
        )
        html = '''<a href="https://p-bandai.jp/item/item-1000000001/">
        〖抽選販売〗ドラゴンボールスーパーカードゲーム FW ブースター [FB11]</a>'''
        adapter = PremiumBandaiApplicationAdapter(fetcher=lambda _url: html)
        hits, _message = adapter.search_candidate({
            "tcg_key": "dragon_ball_fusion_world", "name": "ブースター FB11",
            "product_code": "FB11", "release_date": "2026-09-12",
        })
        self.assertEqual(1, len(hits))
        self.assertFalse(hits[0]["confirmed"])
        self.assertEqual("candidate", hits[0]["verification_status"])

    def test_x_query_is_specific_and_missing_token_is_safe(self):
        query = QUERIES["dragon_ball_fusion_world"]
        self.assertIn("DBSCG FUSION WORLD", query)
        self.assertNotIn('"ドラゴンボール" OR', query)
        with tempfile.TemporaryDirectory() as directory:
            result = XRecentSearch(Path(directory)).search(
                "dragon_ball_fusion_world", bearer_token=""
            )
        self.assertEqual("disabled", result["status"])
        self.assertEqual(0, result["request_count"])

    def test_x_classification_and_product_code(self):
        self.assertEqual("LOTTERY", XRecentSearch._classify_post("DBSCG FW FB11 WEB抽選受付"))
        self.assertEqual("RESERVATION", XRecentSearch._classify_post("フュージョンワールド FS13 予約受付"))
        self.assertEqual("RESTOCK", XRecentSearch._classify_post("DBSCG FW SB02 再入荷"))
        self.assertEqual("FB11", XRecentSearch._extract_product_name("DBSCG FW FB11 予約受付"))
        self.assertEqual("IRRELEVANT", XRecentSearch._classify_post("ドラゴンボール フィギュア抽選"))

    def test_candidate_filter_allows_cards_and_rejects_supply(self):
        base = {"name": "ブースターパック FB11", "product_kind": "ブースターパック",
                "release_date": "2026-09-12", "official_url": LIST_URL,
                "manufacturer_official": True}
        self.assertTrue(CandidateManager._is_new_release_candidate(
            base, "dragon_ball_fusion_world"
        ))
        self.assertFalse(CandidateManager._is_new_release_candidate(
            {**base, "name": "公式スリーブ", "product_kind": "その他"},
            "dragon_ball_fusion_world",
        ))

    def test_trusted_account_resource_contains_verified_official(self):
        accounts = json.loads((APP_DIR / "resources" / "trusted_x_accounts.json").read_text(
            encoding="utf-8"
        ))
        account = next(item for item in accounts if item["username"] == "dbfw_cardgameJP")
        self.assertEqual("dragon_ball_fusion_world", account["tcg"])
        self.assertEqual("OFFICIAL_MANUFACTURER", account["source_type"])
        self.assertEqual(100, account["manual_trust_score"])


if __name__ == "__main__":
    unittest.main()
