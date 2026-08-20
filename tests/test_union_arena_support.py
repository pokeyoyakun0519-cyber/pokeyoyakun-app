import json
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
sys.path.insert(0, str(APP_DIR))

from core.candidate_manager import CandidateManager
from core.card_labo_parser import CardLaboParser
from core.config_manager import ConfigManager
from core.hobby_station_parser import HobbyStationParser
from core.product_master import ProductMasterManager
from core.product_store import ProductStore
from core.priority_application_adapters import PremiumBandaiApplicationAdapter
from core.retail_plugin_registry import enabled_plugins_for_tcg
from core.setup_coordinator import SUPPORTED_TCG_KEYS
from core.source_manager import SourceManager
from core.tcg_categories import category_for_key, normalize_key
from core.union_arena_official_extractor import UnionArenaOfficialExtractor
from core.x_recent_search import QUERIES, XRecentSearch


LIST_URL = UnionArenaOfficialExtractor.LIST_URL


def product_block(category: str, path: str, name: str, date="2026.12.11", price="385"):
    return f'''<li class="productsDetail" data-tags="{category},all">
      <a href="{path}"><img src="/images/{path.rsplit('/', 1)[-1]}.jpg"></a>
      <dl><dt class="productsTit">{name}</dt>
      <dd>{date} メーカー希望小売価格 {price}円</dd></dl></li>'''


class UnionArenaSupportTest(unittest.TestCase):
    def setUp(self):
        self.extractor = UnionArenaOfficialExtractor()

    def test_category_aliases_and_display(self):
        for value in ("UNION_ARENA", "UNION ARENA", "ユニオンアリーナ", "ユニアリ"):
            self.assertEqual("union_arena", normalize_key(value)[0])
        self.assertEqual("UNION ARENA", category_for_key("union_arena").display_name)

    def test_setup_and_default_config_enable_union_arena(self):
        self.assertIn("union_arena", SUPPORTED_TCG_KEYS)
        with tempfile.TemporaryDirectory() as directory:
            config = ConfigManager(Path(directory)).load()
        self.assertTrue(config["games"]["union_arena"])

    def test_official_list_extracts_supported_card_products(self):
        html = "".join((
            product_block("boosters", "/jp/products/boosters/ua-1.php", "ブースターパック 作品A"),
            product_block("decks", "/jp/products/decks/ua-1.php", "スタートデッキ 作品B", "2026年9月1日", "1,650"),
            product_block("other", "/jp/products/other/premium/a.php", "UNION ARENA PREMIUM CARD SET 作品C"),
        ))
        products = self.extractor.extract_list_products(html, LIST_URL, "UNION ARENA公式")
        self.assertEqual(3, len(products))
        self.assertEqual({"作品A", "作品B", "作品C"}, {item["title_name"] for item in products})
        self.assertTrue(all(item["official_product_id"] for item in products))
        self.assertTrue(all(item["source"] == "UNION ARENA公式" for item in products))
        self.assertTrue(all(item["last_verified_at"] for item in products))

    def test_supply_goods_and_non_card_other_are_excluded(self):
        names = (
            "オフィシャルカードスリーブ 作品A", "プレイマット 作品A",
            "アクションポイントカードセット 作品A", "フィギュア 作品A",
            "イベント記念グッズ", "カードリスト公開",
        )
        html = "".join(
            product_block("other", f"/jp/products/other/x/{index}.php", name)
            for index, name in enumerate(names)
        )
        self.assertEqual([], self.extractor.extract_list_products(html, LIST_URL, "公式"))

    def test_detail_uses_primary_heading_code_only(self):
        html = """<html><head><title>アドバンスドデッキ BLEACH</title></head>
        <body><h1>アドバンスドデッキ BLEACH</h1>
        関連商品 ブースターパック【EX15BT】 発売日 2026年9月11日
        メーカー希望小売価格 2,640円</body></html>"""
        data = self.extractor.supplement_from_detail(
            html, "https://www.unionarena-tcg.com/jp/products/decks/dc-blc.php"
        )
        self.assertEqual("", data["product_code"])

    def test_detail_extracts_own_code_jan_date_and_price(self):
        html = """<title>ブースターパック D.Gray-man【UA58BT】</title>
        <h1>ブースターパック D.Gray-man【UA58BT】</h1>
        JANコード：4580123456789 発売日 2026年11月27日
        メーカー希望小売価格：385円"""
        data = self.extractor.supplement_from_detail(
            html, "https://www.unionarena-tcg.com/jp/products/boosters/dgm-1.php"
        )
        self.assertEqual("UA58BT", data["product_code"])
        self.assertEqual("4580123456789", data["jan"])
        self.assertEqual("2026-11-27", data["release_date"])
        self.assertEqual(385, data["msrp"])

    def test_non_official_or_non_japanese_page_is_rejected(self):
        html = product_block("boosters", "/jp/products/boosters/a.php", "商品")
        for url in ("http://www.unionarena-tcg.com/jp/products/", "https://example.com/jp/products/"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                self.extractor.extract_list_products(html, url, "公式")

    def test_same_title_different_official_ids_never_merge(self):
        first = {"id": "a", "name": "ブースターパック 同一作品", "tcg_key": "union_arena",
                 "product_kind": "ブースターパック", "official_product_id": "boosters/a", "sites": []}
        second = {**first, "id": "b", "official_product_id": "boosters/b"}
        self.assertEqual(
            (None, "identifier_conflict"),
            ProductMasterManager.find_match([first], second),
        )
        with tempfile.TemporaryDirectory() as directory:
            store = ProductStore(Path(directory))
            store.merge_discovered_products([first, second])
            loaded = store.load_products()
        self.assertEqual(2, len(loaded))
        self.assertEqual(2, len({item["product_id"] for item in loaded}))

    def test_same_official_id_matches_despite_title_difference(self):
        first = {"name": "作品A ブースター", "tcg_key": "union_arena", "product_kind": "ブースターパック", "official_product_id": "boosters/a"}
        second = {**first, "name": "UNION ARENA ブースターパック 作品A"}
        self.assertEqual((0, "identifier"), ProductMasterManager.find_match([first], second))

    def test_candidate_filter_allows_cards_and_rejects_supply(self):
        base = {"name": "ブースターパック 作品A", "product_kind": "ブースターパック",
                "release_date": "2026-08-28", "official_url": "https://www.unionarena-tcg.com/jp/products/boosters/a.php",
                "manufacturer_official": True}
        self.assertTrue(CandidateManager._is_new_release_candidate(base, "union_arena"))
        self.assertFalse(CandidateManager._is_new_release_candidate(
            {**base, "name": "公式スリーブ 作品A", "product_kind": "その他"}, "union_arena"
        ))

    def test_dedicated_store_parsers_detect_union_arena(self):
        for parser, expected in (
            (CardLaboParser, ("union_arena", "")),
            (HobbyStationParser, "union_arena"),
        ):
            with self.subTest(parser=parser.__name__):
                self.assertEqual(expected, parser.detect_tcg("UNION ARENA 新弾 WEB抽選"))
                self.assertEqual(expected, parser.detect_tcg("ユニアリ 予約受付中"))

    def test_verified_retail_plugins_include_union_arena(self):
        ids = {item["id"] for item in enabled_plugins_for_tcg("union_arena")}
        self.assertTrue({
            "amazon_jp", "yodobashi_lottery", "rakuten_books", "biccamera",
            "joshin", "card_labo", "hobby_station", "premium_bandai",
        } <= ids)

    def test_source_manager_registers_official_provider(self):
        source = next(item for item in SourceManager.DEFAULT_SOURCES if item["tcg_key"] == "union_arena")
        self.assertEqual(LIST_URL, source["url"])
        self.assertTrue(SourceManager._is_union_arena_official(LIST_URL))
        self.assertFalse(SourceManager._is_union_arena_official("https://example.com/jp/products/"))

    def test_x_query_exists_and_missing_token_is_safe(self):
        self.assertIn("union_arena", QUERIES)
        with tempfile.TemporaryDirectory() as directory:
            result = XRecentSearch(Path(directory)).search("union_arena", bearer_token="")
        self.assertEqual("disabled", result["status"])
        self.assertEqual(0, result["request_count"])

    def test_x_classifier_recognizes_application_types(self):
        self.assertEqual("LOTTERY", XRecentSearch._classify_post("ユニアリ新弾 WEB抽選受付"))
        self.assertEqual("RESERVATION", XRecentSearch._classify_post("UNION ARENA 予約受付中"))
        self.assertEqual("RESTOCK", XRecentSearch._classify_post("ユニオンアリーナ 再入荷"))

    def test_x_classifier_rejects_non_product_information(self):
        values = ("大会情報 応募受付", "キャンペーン抽選", "デッキレシピ", "カードリスト", "新作フィギュア予約")
        for value in values:
            with self.subTest(value=value):
                self.assertEqual("IRRELEVANT", XRecentSearch._classify_post(value))

    def test_x_product_code_extraction(self):
        self.assertEqual("UA58BT", XRecentSearch._extract_product_name("D.Gray-man UA58BT 予約受付"))
        self.assertEqual("EX16BT", XRecentSearch._extract_product_name("EX16BT 再入荷"))
        self.assertEqual("UA01DC", XRecentSearch._extract_product_name("UA01DC 予約受付"))

    def test_premium_bandai_union_arena_is_candidate_until_period_verified(self):
        self.assertEqual(
            "https://p-bandai.jp/carddas/a0015/list-da10-n0/",
            PremiumBandaiApplicationAdapter.UNION_ARENA_INDEX_URL,
        )
        html = '''<a href="https://p-bandai.jp/item/item-1000000001/">
        UNION ARENA ブースターパック 作品A【UA58BT】 予約</a>'''
        adapter = PremiumBandaiApplicationAdapter(fetcher=lambda _url: html)
        hits, _message = adapter.search_candidate({
            "tcg_key": "union_arena", "name": "ブースターパック 作品A",
            "product_code": "UA58BT", "release_date": "2026-11-27",
        })
        self.assertEqual(1, len(hits))
        self.assertFalse(hits[0]["confirmed"])
        self.assertEqual("candidate", hits[0]["verification_status"])
        self.assertEqual(
            adapter.UNION_ARENA_INDEX_URL,
            hits[0]["source_evidence"][0]["source_url"],
        )

    def test_trusted_account_resource_has_verified_official(self):
        path = APP_DIR / "resources" / "trusted_x_accounts.json"
        accounts = json.loads(path.read_text(encoding="utf-8"))
        account = next(item for item in accounts if item["username"] == "UNION_ARENA_TCG")
        self.assertEqual("union_arena", account["tcg"])
        self.assertEqual("OFFICIAL_MANUFACTURER", account["source_type"])
        self.assertEqual(100, account["manual_trust_score"])


if __name__ == "__main__":
    unittest.main()
