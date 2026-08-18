import io
import json
import tempfile
import unittest
import urllib.error
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from core.candidate_auto_search import CandidateAutoSearch
from core.auto_monitor_manager import AutoMonitorManager
from core.information_classifier import APPLICATION, NEWS, PRODUCT, RESTOCK, classify_information
from core.monitoring_scope import enabled_tcg_keys
from core.onepiece_official_extractor import OnePieceOfficialExtractor
from core.pokemon_official_extractor import PokemonOfficialExtractor
from core.source_manager import SourceManager
from core.x_recent_search import QUERIES, XRecentSearch
from ui.main_window import MainWindow


class _Headers(dict):
    def get_content_charset(self):
        return "utf-8"


class _Response:
    def __init__(self, payload, headers=None, url="https://api.x.com/test"):
        self.payload = payload if isinstance(payload, bytes) else payload.encode("utf-8")
        self.headers = _Headers(headers or {})
        self.url = url

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, *_args):
        return self.payload

    def geturl(self):
        return self.url


class PrecisionTests(unittest.TestCase):
    def test_classifier_requires_product_evidence(self):
        self.assertEqual(NEWS, classify_information({"name": "新商品ニュース"}))
        self.assertEqual(PRODUCT, classify_information({"name": "拡張パック A", "release_date": "2026-08-01"}))

    def test_classifier_excludes_false_positive_categories(self):
        for name in ("大会イベント", "優勝デッキレシピ", "高価買取", "発売キャンペーン", "公式ニュース"):
            with self.subTest(name=name):
                self.assertEqual(NEWS, classify_information({"name": name, "release_date": "2026-08-01"}))

    def test_classifier_separates_application_and_restock(self):
        self.assertEqual(APPLICATION, classify_information({"name": "抽選受付"}))
        self.assertEqual(RESTOCK, classify_information({"name": "再入荷のお知らせ"}))

    def test_pokemon_catalog_extracts_cards_and_excludes_supplies(self):
        payload = {"products": [
            {"productTitle": "拡張パック「アビスアイ」", "productType": "拡張パック", "releaseDate": "2026年5月22日", "priceTxt": "200円（税込）", "tumbsImg": "/a.jpg", "link_detailPage": "/ex/m5/"},
            {"productTitle": "デッキシールド A", "productType": "周辺グッズ", "releaseDate": "2026年5月22日", "priceTxt": "889円", "tumbsImg": "/b.jpg", "link_detailPage": ""},
        ]}
        products = PokemonOfficialExtractor().extract_catalog_products(payload, "公式")
        self.assertEqual(1, len(products))
        self.assertEqual("アビスアイ", products[0]["name"].split("「")[1].rstrip("」"))
        self.assertEqual(200, products[0]["msrp"])
        self.assertEqual("m5", products[0]["official_product_id"])
        self.assertEqual("PRODUCT", products[0]["information_type"])

    def test_pokemon_catalog_rejects_invalid_shape(self):
        with self.assertRaises(ValueError):
            PokemonOfficialExtractor().extract_catalog_products("null", "公式")

    def test_pokemon_special_official_page_uses_single_exact_title(self):
        html = '''<html><head><meta property="og:title" content="拡張パック「30th CELEBRATION」"><meta property="og:image" content="/m6a.jpg"></head><body><h2>商品情報</h2><p>商品名 ポケモンカードゲーム MEGA 拡張パック「30th CELEBRATION」</p><p>希望小売価格 360円（税込）</p><p>発売日 2026年9月16日</p><p>抽選応募受け付け期間 2026年8月10日（月）12:00 ～2026年8月14日（金）16:59</p><a href="https://www.pokemoncenter-online.com/item.html">ポケモンセンターオンライン</a><p>大会イベントのお知らせ</p></body></html>'''
        products = PokemonOfficialExtractor().extract_detail_products(
            html, "https://www.30th.pokemon-card.com/product/m6a", "公式"
        )
        self.assertEqual(1, len(products))
        self.assertEqual("拡張パック「30th CELEBRATION」", products[0]["name"])
        self.assertEqual(360, products[0]["msrp"])
        self.assertEqual("2026-08-14T16:59:00+09:00", products[0]["application_end_at"])
        self.assertEqual("https://www.pokemoncenter-online.com/item.html", products[0]["application_url"])

    def test_pokemon_special_cardset_extracts_each_named_product(self):
        html = '''<html><head><meta property="og:title" content="カードセット"></head><body>商品名 ポケモンカードゲーム MEGA 「30th CELEBRATION カードセット A」 希望小売価格 1,200円（税込） 発売日 2026年10月16日 商品名 ポケモンカードゲーム MEGA 「30th CELEBRATION カードセット B」 希望小売価格 1,200円（税込） 発売日 2026年10月16日</body></html>'''
        products = PokemonOfficialExtractor().extract_detail_products(
            html, "https://www.30th.pokemon-card.com/product/cardset", "公式"
        )
        self.assertEqual(2, len(products))
        self.assertEqual(2, len({item["official_product_id"] for item in products}))

    def test_pokemon_starter_fragments_have_distinct_official_ids(self):
        extractor = PokemonOfficialExtractor()
        self.assertNotEqual(
            extractor._official_id("https://www.pokemon-card.com/ex/me/#mee"),
            extractor._official_id("https://www.pokemon-card.com/ex/me/#mez"),
        )

    def test_official_application_is_monitored_before_normal_release_window(self):
        product, reason = AutoMonitorManager.classify_candidate({
            "name": "拡張パック A", "tcg_key": "pokemon",
            "release_date": "2026-09-16",
            "official_url": "https://www.pokemon-card.com/product/a",
            "application_url": "https://www.pokemoncenter-online.com/a",
            "application_end_at": "2026-08-14T16:59:00+09:00",
            "application_status": "抽選受付",
        }, date(2026, 8, 1), 30)
        self.assertEqual("eligible", reason)
        self.assertEqual(1, len(product["sites"]))

    def test_onepiece_accepts_current_directory_product_url(self):
        self.assertTrue(OnePieceOfficialExtractor.is_product_detail_url(
            "https://www.onepiece-cardgame.com/products/boosters/op17/"
        ))

    def test_onepiece_extracts_op17_and_excludes_supply(self):
        html = '''<html lang="ja"><li class="linkListColBox" data-cat="boosters"><a href="/products/boosters/op17/" class="linkListColItem"><img src="/op17.jpg"><h4 class="linkListColTitle">ブースターパック OP-17</h4><time datetime="2026-08-22"></time></a></li><li class="linkListColBox" data-cat="other"><a href="/products/sleeve.html" class="linkListColItem"><h4 class="linkListColTitle">オフィシャルカードスリーブ</h4><time datetime="2026-08-22"></time></a></li></html>'''
        products = OnePieceOfficialExtractor().extract_list_products(
            html, "https://www.onepiece-cardgame.com/products/", "公式"
        )
        self.assertEqual(1, len(products))
        self.assertEqual("OP-17", products[0]["product_code"])

    def test_priority_scope_defaults_to_two_games(self):
        config = {"general": {"priority_monitoring_only": True}, "games": {"pokemon": True, "onepiece": True, "yugioh": True}}
        self.assertEqual({"pokemon", "onepiece"}, enabled_tcg_keys(config))

    def test_disabled_tcg_skips_candidate_search(self):
        search = CandidateAutoSearch()
        search.candidates = Mock()
        search.candidates.load_candidates.return_value = [
            {"id": "p", "tcg_key": "pokemon", "last_searched": ""},
            {"id": "y", "tcg_key": "yugioh", "last_searched": ""},
        ]
        search.searcher = Mock()
        search.searcher.search_candidate.return_value = ([], [])
        search.candidates.update_search_result.return_value = {}
        result = search.run_due(enabled_tcg_keys={"pokemon"})
        self.assertEqual(1, result["searched_count"])
        self.assertEqual("p", search.searcher.search_candidate.call_args.args[0]["id"])

    def test_candidate_results_are_saved_once_per_batch(self):
        search = CandidateAutoSearch()
        search.candidates = Mock()
        items = [
            {"id": "a", "tcg_key": "pokemon", "last_searched": ""},
            {"id": "b", "tcg_key": "pokemon", "last_searched": ""},
        ]
        search.candidates.load_candidates.return_value = items
        search.candidates.update_search_result.side_effect = lambda candidate_id, **kwargs: {"id": candidate_id}
        search.searcher = Mock()
        search.searcher.search_candidate.return_value = ([], [])
        result = search.run_due(enabled_tcg_keys={"pokemon"})
        self.assertEqual(2, result["searched_count"])
        search.candidates.load_candidates.assert_called_once_with()
        search.candidates.save_candidates.assert_called_once_with(items)

    def test_source_manager_skips_disabled_tcg(self):
        manager = SourceManager()
        manager.load_sources = Mock(return_value=[
            {"id": "p", "enabled": True, "tcg_key": "pokemon"},
            {"id": "y", "enabled": True, "tcg_key": "yugioh"},
        ])
        manager.save_sources = Mock()
        manager._check_source_record = Mock(return_value=False)
        manager.check_all(enabled_tcg_keys={"pokemon"})
        self.assertEqual(1, manager._check_source_record.call_count)

    def test_monitor_ui_refresh_is_debounced_and_split(self):
        dummy = type("Window", (), {})()
        dummy._shutdown_started = False
        dummy._pending_monitor_refresh = set()
        dummy.monitor_refresh_timer = Mock()
        dummy.product_page = Mock()
        dummy.application_dashboard_page = Mock()
        dummy.candidates_page = Mock()
        dummy.sources_page = Mock()
        result = {"source_count": 2, "changed_sources": [{}], "candidate_search": {"new_hit_candidates": []}}
        MainWindow._refresh_data_pages_after_monitor(dummy, result)
        MainWindow._refresh_data_pages_after_monitor(dummy, result)
        dummy.product_page.reload_saved_products.assert_not_called()
        MainWindow._flush_monitor_refresh(dummy)
        dummy.product_page.reload_saved_products.assert_called_once_with()
        dummy.candidates_page.reload_candidates.assert_called_once_with()
        dummy.sources_page.reload_sources.assert_called_once_with()
        dummy.application_dashboard_page.reload.assert_not_called()

    def test_http_cache_avoids_duplicate_request(self):
        SourceManager._response_cache.clear()
        opener = Mock()
        opener.open.return_value = _Response("<title>A</title>", url="https://example.com/")
        with patch("core.source_manager.build_https_opener", return_value=opener):
            self.assertTrue(SourceManager()._fetch_page("https://example.com/")["ok"])
            self.assertTrue(SourceManager()._fetch_page("https://example.com/")["cache_hit"])
        self.assertEqual(1, opener.open.call_count)


class XRecentSearchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        resources = self.root / "config"
        resources.mkdir()
        (resources / "trusted_x_accounts.json").write_text(json.dumps([{
            "username": "official_store", "display_name": "公式店", "category": "store_official",
            "store_name": "公式店", "tcg": "pokemon", "trust_score": 90, "enabled": True,
        }]), encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def _payload(self, username="general_user", newest="101", url="https://store.example/apply"):
        return json.dumps({
            "data": [{"id": newest, "author_id": "u1", "text": "ポケカ 抽選受付", "created_at": "2026-08-10T00:00:00Z", "entities": {"urls": [{"expanded_url": url}]}}],
            "includes": {"users": [{"id": "u1", "username": username, "name": "User"}]},
            "meta": {"newest_id": newest},
        })

    def test_queries_cover_required_tcg_and_exclude_retweets(self):
        self.assertEqual({
            "pokemon", "onepiece", "union_arena", "dragon_ball_fusion_world",
        }, set(QUERIES))
        self.assertTrue(all("-is:retweet" in value for value in QUERIES.values()))

    def test_general_user_is_candidate_not_confirmed(self):
        opener = Mock()
        opener.open.return_value = _Response(self._payload())
        result = XRecentSearch(self.root, opener=opener, now=lambda: datetime(2026, 8, 11, tzinfo=timezone.utc)).search("pokemon", "token")
        self.assertFalse(result["candidates"][0]["confirmed"])
        self.assertEqual(30, result["candidates"][0]["trust_score"])

    def test_official_store_is_high_trust_but_x_alone_is_not_confirmed(self):
        opener = Mock()
        opener.open.return_value = _Response(self._payload("official_store"))
        item = XRecentSearch(self.root, opener=opener).search("pokemon", "token")["candidates"][0]
        self.assertEqual(90, item["trust_score"])
        self.assertFalse(item["confirmed"])
        self.assertEqual("pending", item["verification_status"])

    def test_since_id_is_used_after_success(self):
        opener = Mock()
        opener.open.side_effect = [_Response(self._payload(newest="101")), _Response(self._payload(newest="102"))]
        client = XRecentSearch(self.root, opener=opener)
        client.search("pokemon", "token")
        client.search("pokemon", "token")
        self.assertIn("since_id=101", opener.open.call_args.args[0].full_url)
        self.assertNotIn("start_time=", opener.open.call_args.args[0].full_url)

    def test_429_sets_exponential_backoff_without_retry_loop(self):
        opener = Mock()
        opener.open.side_effect = urllib.error.HTTPError(
            "https://api.x.com", 429, "rate", {"x-rate-limit-reset": "0"}, io.BytesIO()
        )
        result = XRecentSearch(self.root, opener=opener).search("pokemon", "token")
        self.assertEqual("rate_limited", result["status"])
        self.assertEqual(1, opener.open.call_count)
        self.assertGreaterEqual(result["retry_after"], 59)

    def test_missing_token_disables_without_request(self):
        opener = Mock()
        with patch.dict("os.environ", {}, clear=True):
            result = XRecentSearch(self.root, opener=opener).search("pokemon")
        self.assertEqual("disabled", result["status"])
        opener.open.assert_not_called()

    def test_web_and_x_duplicate_are_merged(self):
        web = [{"tcg_key": "pokemon", "product_name": "商品A", "store_name": "店", "application_url": "https://s/app", "application_end_at": "2026-08-12"}]
        x = [{**web[0], "source_url": "https://x.com/store/status/1"}]
        merged = XRecentSearch.deduplicate(web, x)
        self.assertEqual(1, len(merged))
        self.assertEqual(["https://x.com/store/status/1"], merged[0]["source_urls"])

    def test_web_and_realistic_x_item_merge_by_application_url(self):
        web = [{"tcg_key": "onepiece", "product_name": "OP-17", "application_url": "https://shop.example/apply"}]
        x = [{"tcg_key": "onepiece", "text": "抽選受付", "application_url": "https://shop.example/apply/?utm_source=x", "source_url": "https://x.com/store/status/2"}]
        merged = XRecentSearch.deduplicate(web, x)
        self.assertEqual(1, len(merged))
        self.assertEqual(["https://x.com/store/status/2"], merged[0]["source_urls"])

    def test_search_and_store_is_atomic_and_keeps_candidates(self):
        opener = Mock()
        opener.open.return_value = _Response(self._payload())
        result = XRecentSearch(self.root, opener=opener).search_and_store({"pokemon"}, "token")
        self.assertEqual(1, result["candidate_count"])
        self.assertTrue((self.root / "data" / "information_candidates.json").exists())
        self.assertFalse((self.root / "data" / "information_candidates.json.tmp").exists())
        path = self.root / "data" / "information_candidates.json"
        path.write_text("{broken", encoding="utf-8")
        calls = opener.open.call_count
        blocked = XRecentSearch(self.root, opener=opener).search_and_store({"pokemon"}, "token")
        self.assertEqual("corrupt", blocked["status"])
        self.assertEqual("{broken", path.read_text(encoding="utf-8"))
        self.assertEqual(calls, opener.open.call_count)


if __name__ == "__main__":
    unittest.main()
