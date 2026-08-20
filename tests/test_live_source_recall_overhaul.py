import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

from core.candidate_manager import CandidateManager
from core.card_labo_parser import CardLaboParser
from core.onepiece_official_extractor import OnePieceOfficialExtractor
from core.priority_application_adapters import (
    MagiApplicationAdapter,
    PremiumBandaiApplicationAdapter,
)
from core.trusted_x_accounts import (
    OFFICIAL_SHOP_BRANCH,
    TRUSTED_INFORMATION,
    TrustedXAccountRegistry,
)
from core.x_recent_search import XRecentSearch
from tests.test_card_labo_parser import Fetcher, article, calendar_html, listing, rss
from tests.test_pokemon_onepiece_precision import _Response
from tools.audit_pokemon_onepiece_sources import evaluate_catalog


NOW = datetime(2026, 8, 15, 3, 0, tzinfo=timezone.utc)


class OnePieceLiveCatalogueTests(unittest.TestCase):
    def test_continuous_audit_detects_catalogue_structure_drop(self):
        baseline = {
            "minimum_catalog_count": 2,
            "critical_urls": ["https://official.example/a", "https://official.example/b"],
        }
        result = evaluate_catalog(
            [{"official_url": "https://official.example/a"}], baseline
        )
        self.assertTrue(result["structure_drop_detected"])
        self.assertEqual(["https://official.example/b"], result["missing_critical_urls"])

    def test_current_php_product_urls_are_accepted(self):
        for url in (
            "https://www.onepiece-cardgame.com/products/boosters/pack.php",
            "https://www.onepiece-cardgame.com/products/decks/st01.php",
            "https://www.onepiece-cardgame.com/products/special.php",
        ):
            with self.subTest(url=url):
                self.assertTrue(OnePieceOfficialExtractor.is_product_detail_url(url))

    def test_all_advertised_catalogue_pages_are_collected(self):
        links = "".join(
            f'<a href="/products/?page={number}">{number}</a>'
            for number in range(1, 16)
        )
        pages = OnePieceOfficialExtractor().collect_page_urls(
            f'<html lang="ja">{links}</html>',
            "https://www.onepiece-cardgame.com/products/",
        )
        self.assertEqual(15, len(pages))
        self.assertTrue(pages[-1].endswith("page=15"))

    def test_sparse_paginator_expands_omitted_middle_pages(self):
        html = (
            '<html lang="ja"><a href="?view=normal&page=2">2</a>'
            '<a href="?view=normal&page=3">3</a>'
            '<a href="?view=normal&page=15">15</a></html>'
        )
        pages = OnePieceOfficialExtractor().collect_page_urls(
            html, "https://www.onepiece-cardgame.com/products/?view=normal"
        )
        self.assertEqual(15, len(pages))
        self.assertIn("page=14", pages[13])

    def test_supply_products_are_excluded(self):
        html = '''<html lang="ja"><li class="linkListColBox" data-cat="other"><a href="/products/other/binder.php" class="linkListColItem"><h4 class="linkListColTitle">オフィシャル9ポケットバインダー vol.1</h4><time datetime="2026-03-28"></time></a></li></html>'''
        self.assertEqual([], OnePieceOfficialExtractor().extract_list_products(
            html, "https://www.onepiece-cardgame.com/products/", "公式"
        ))

    def test_official_card_without_date_is_kept_as_candidate(self):
        self.assertTrue(CandidateManager._is_new_release_candidate({
            "name": "プレミアムカードコレクション テスト",
            "tcg_key": "onepiece",
            "product_kind": "プレミアムカードコレクション",
            "release_date": "",
            "official_url": "https://www.onepiece-cardgame.com/products/other/test.php",
            "manufacturer_official": True,
        }, "onepiece"))

    def test_official_special_card_set_without_date_is_kept_as_candidate(self):
        self.assertTrue(CandidateManager._is_new_release_candidate({
            "name": "ONE PIECEカードゲーム 4th Anniversary Set",
            "tcg_key": "onepiece",
            "product_kind": "その他",
            "release_date": "",
            "official_url": "https://www.onepiece-cardgame.com/products/other/anniversary4.php",
            "manufacturer_official": True,
        }, "onepiece"))

    def test_unofficial_missing_date_is_not_promoted(self):
        self.assertFalse(CandidateManager._is_new_release_candidate({
            "name": "プレミアムカードコレクション テスト",
            "product_kind": "プレミアムカードコレクション",
            "release_date": "",
            "official_url": "https://shop.example/test",
        }, "onepiece"))


class CardLaboDiscoveryPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.state_path = self.root / "config" / "card_labo_state.json"

    def tearDown(self):
        self.temp.cleanup()

    def parser(self, fetcher):
        return CardLaboParser(
            fetcher=fetcher,
            state_path=self.state_path,
            request_interval_seconds=0,
            now_provider=lambda: NOW,
        )

    def test_checked_article_keeps_normalized_application_on_next_scan(self):
        first = Fetcher({
            CardLaboParser.RSS_URL: rss(900),
            CardLaboParser.BLOG_URL: listing(900),
            CardLaboParser.CALENDAR_URL: calendar_html(),
            "https://www.c-labo.jp/blog/900/": article(),
        })
        first_records = self.parser(first).scan()
        self.assertTrue(any(item.get("article_type") == "lottery" for item in first_records))

        second = Fetcher({
            CardLaboParser.RSS_URL: rss(900),
            CardLaboParser.BLOG_URL: listing(900),
        })
        second_records = self.parser(second).scan()
        self.assertTrue(any(item.get("article_type") == "lottery" for item in second_records))
        self.assertNotIn("https://www.c-labo.jp/blog/900/", second.calls)
        saved = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertEqual(1, len(saved["article_records"]))

    def test_product_code_matches_prefixed_article_title(self):
        candidate = {
            "name": "ブースターパック 世界最強の戦士【OP-17】",
            "product_code": "OP-17",
        }
        record = {
            "product_name": "ONE PIECEカードゲーム ブースターパック OP17",
            "title": "OP-17 抽選販売",
        }
        self.assertTrue(CardLaboParser._matches_candidate(candidate, record))

    def test_article_without_code_matches_distinctive_product_title(self):
        candidate = {
            "name": "ブースターパック 世界最強の戦士【OP-17】",
            "product_code": "OP-17",
        }
        record = {
            "product_name": "ワンピースカードゲーム ブースターパック 世界最強戦士",
            "title": "抽選予約販売のお知らせ",
        }
        self.assertTrue(CardLaboParser._matches_candidate(candidate, record))

    def test_conflicting_product_codes_never_match_by_name(self):
        candidate = {"name": "同名商品 OP-17", "product_code": "OP-17"}
        record = {"product_name": "同名商品 OP-16", "title": "抽選販売"}
        self.assertFalse(CardLaboParser._matches_candidate(candidate, record))

    def test_unmatched_official_applications_create_one_candidate_with_all_evidence(self):
        manager = CandidateManager(self.root)
        manager._upsert_product_from_candidate = Mock()
        discoveries = []
        for article_id, store in (("1", "A店"), ("2", "B店")):
            record = {
                "article_id": article_id,
                "article_url": f"https://www.c-labo.jp/blog/{article_id}/",
                "article_type": "lottery",
                "application_evidence": True,
                "tcg_key": "pokemon",
                "tcg": "ポケモンカード",
                "product_name": "ポケモンカードゲーム 再販テスト商品",
                "store_name": store,
            }
            hit = CardLaboParser._build_hit(record)
            discoveries.append({"record": record, "hit": hit})
        result = manager.merge_application_discoveries(
            discoveries, matcher=CardLaboParser._matches_candidate
        )
        candidates = manager.load_candidates()
        self.assertEqual({"created": 1, "updated": 2, "ambiguous": 0}, result)
        self.assertEqual(1, len(candidates))
        self.assertEqual(2, len(candidates[0]["retail_hits"]))
        self.assertTrue(candidates[0]["approved"])
        manager._upsert_product_from_candidate.assert_called()

    def test_ambiguous_discovery_is_not_auto_merged(self):
        manager = CandidateManager(self.root)
        manager.save_candidates([
            {"id": "a", "name": "候補A", "tcg_key": "pokemon"},
            {"id": "b", "name": "候補B", "tcg_key": "pokemon"},
        ])
        result = manager.merge_application_discoveries([{
            "record": {"product_name": "曖昧", "tcg_key": "pokemon"},
            "hit": {"site_key": "card_labo", "url": "https://www.c-labo.jp/blog/1/"},
        }], matcher=lambda _candidate, _record: True)
        self.assertEqual(1, result["ambiguous"])
        self.assertEqual(2, len(manager.load_candidates()))


class TrustedXAccountDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "config").mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def write_accounts(self, source_type=OFFICIAL_SHOP_BRANCH, score=90):
        path = self.root / "config" / "trusted_x_accounts.json"
        path.write_text(json.dumps([{
            "user_id": "",
            "username": "official_store",
            "display_name": "公式店",
            "tcg": "pokemon",
            "source_type": source_type,
            "store_name": "公式店",
            "manual_trust_score": score,
            "enabled": True,
            "memo": "fixture",
        }]), encoding="utf-8")
        return path

    @staticmethod
    def payload(text="ポケカ 抽選受付", newest="501"):
        return json.dumps({
            "data": [{
                "id": newest,
                "author_id": "u501",
                "text": text,
                "created_at": "2026-08-15T01:00:00Z",
                "entities": {"urls": [{"expanded_url": "https://store.example/apply"}]},
            }],
            "includes": {"users": [{
                "id": "u501", "username": "official_store", "name": "公式店",
            }]},
            "meta": {"newest_id": newest},
        })

    def test_read_does_not_rewrite_legacy_or_current_config(self):
        path = self.write_accounts()
        before = path.read_bytes()
        accounts = TrustedXAccountRegistry(self.root).load()
        self.assertEqual(OFFICIAL_SHOP_BRANCH, accounts[0]["source_type"])
        self.assertEqual(before, path.read_bytes())

    def test_registry_supports_explicit_admin_changes(self):
        self.write_accounts()
        registry = TrustedXAccountRegistry(self.root)
        self.assertTrue(registry.set_enabled("official_store", "pokemon", False))
        self.assertTrue(registry.set_manual_trust("official_store", "pokemon", 77))
        account = registry.load()[0]
        self.assertFalse(account["enabled"])
        self.assertEqual(77, account["manual_trust_score"])

    def test_account_query_uses_from_and_group_since_id(self):
        self.write_accounts()
        opener = Mock()
        opener.open.side_effect = [
            _Response(self.payload(newest="501")),
            _Response(self.payload(newest="502")),
        ]
        client = XRecentSearch(self.root, opener=opener, now=lambda: NOW)
        first = client.search_trusted_accounts("pokemon", "token")
        second = client.search_trusted_accounts("pokemon", "token")
        self.assertEqual("ok", first["status"])
        self.assertIn("from%3Aofficial_store", opener.open.call_args.args[0].full_url)
        self.assertIn("since_id=501", opener.open.call_args.args[0].full_url)
        self.assertEqual("502", second["since_id"])

    def test_official_explicit_x_post_stays_pending_without_web_evidence(self):
        self.write_accounts()
        opener = Mock()
        opener.open.return_value = _Response(self.payload())
        item = XRecentSearch(self.root, opener=opener, now=lambda: NOW).search_trusted_accounts(
            "pokemon", "token"
        )["candidates"][0]
        self.assertFalse(item["confirmed"])
        self.assertEqual("pending", item["verification_status"])
        self.assertEqual("LOTTERY", item["application_type"])
        self.assertEqual(1, len(item["evidence"]))

    def test_information_account_remains_candidate(self):
        self.write_accounts(TRUSTED_INFORMATION, 99)
        opener = Mock()
        opener.open.return_value = _Response(self.payload())
        item = XRecentSearch(self.root, opener=opener, now=lambda: NOW).search_trusted_accounts(
            "pokemon", "token"
        )["candidates"][0]
        self.assertFalse(item["confirmed"])
        self.assertEqual("pending", item["verification_status"])

    def test_false_positive_keywords_are_rejected(self):
        self.write_accounts()
        opener = Mock()
        opener.open.return_value = _Response(self.payload("ポケカ 高価買取 デッキレシピ"))
        result = XRecentSearch(self.root, opener=opener, now=lambda: NOW).search_trusted_accounts(
            "pokemon", "token"
        )
        self.assertEqual([], result["candidates"])

    def test_runtime_state_separates_observation_from_manual_trust(self):
        config = self.write_accounts()
        opener = Mock()
        opener.open.return_value = _Response(self.payload())
        XRecentSearch(self.root, opener=opener, now=lambda: NOW).search_trusted_accounts(
            "pokemon", "token"
        )
        state = TrustedXAccountRegistry(self.root).load_runtime_state()
        observed = state["official_store|pokemon"]
        self.assertEqual("u501", observed["user_id"])
        self.assertEqual("501", observed["latest_tweet_id"])
        self.assertEqual(1, observed["detected_count"])
        self.assertEqual(0, observed["confirmed_count"])
        self.assertNotIn("manual_trust_score", observed)
        self.assertEqual(90, json.loads(config.read_text(encoding="utf-8"))[0]["manual_trust_score"])
        combined = TrustedXAccountRegistry(self.root).load_with_observations()[0]
        self.assertEqual(1, combined["past_candidate_count"])
        self.assertIsNone(combined["observed_accuracy"])

    def test_information_post_is_confirmed_only_with_matching_web_evidence(self):
        self.write_accounts(TRUSTED_INFORMATION, 75)
        data = self.root / "data"
        data.mkdir(parents=True)
        (data / "candidates.json").write_text(json.dumps([{
            "name": "新弾テスト",
            "tcg_key": "pokemon",
            "retail_hits": [{
                "name": "公式店",
                "application_url": "https://store.example/apply",
                "verification_status": "confirmed",
                "source_evidence": [{
                    "source_type": "OFFICIAL_STORE",
                    "source_url": "https://store.example/apply",
                }],
            }],
        }], ensure_ascii=False), encoding="utf-8")
        opener = Mock()
        opener.open.return_value = _Response(self.payload("「新弾テスト」抽選受付"))
        item = XRecentSearch(
            self.root, opener=opener, now=lambda: NOW
        ).search_trusted_accounts("pokemon", "token")["candidates"][0]
        self.assertTrue(item["confirmed"])
        self.assertEqual("confirmed", item["corroboration_status"])
        self.assertEqual(2, len(item["evidence"]))

    def test_latest_tweet_id_tracks_irrelevant_post(self):
        self.write_accounts()
        opener = Mock()
        opener.open.return_value = _Response(
            self.payload("ポケカ 大会結果のお知らせ", newest="999")
        )
        client = XRecentSearch(self.root, opener=opener, now=lambda: NOW)
        result = client.search_trusted_accounts("pokemon", "token")
        self.assertEqual([], result["candidates"])
        account = client.accounts.load_with_observations()[0]
        self.assertEqual("999", account["latest_tweet_id"])


class PriorityApplicationAdapterTests(unittest.TestCase):
    def test_magi_official_period_is_confirmed(self):
        index = '''<html><a href="/news/1222/web">30th CELEBRATION BOX 抽選定価販売</a></html>'''
        detail = '''<html><body><h1>30th CELEBRATION BOX 抽選定価販売</h1><p>キャンペーン参加期間：2026年7月30日～2026年9月15日 23:59</p><p>当選発表：2026年9月16日</p></body></html>'''
        pages = {
            MagiApplicationAdapter.INDEX_URL: index,
            "https://magi.camp/news/1222/web": detail,
        }
        adapter = MagiApplicationAdapter(fetcher=lambda url: pages[url])
        hits, _ = adapter.search_candidate({
            "tcg_key": "pokemon",
            "name": "拡張パック 30th CELEBRATION",
            "release_date": "2026-09-16",
        })
        self.assertEqual(1, len(hits))
        self.assertTrue(hits[0]["confirmed"])
        self.assertEqual("confirmed", hits[0]["verification_status"])
        self.assertTrue(hits[0].get("application_end_at"))

    def test_premium_bandai_listing_is_candidate_without_period_guess(self):
        html = '''<html><a href="/item/item-1000255803/"><img alt="【抽選販売】ONE PIECEカードゲーム ブースターパック 世界最強の戦士【OP-17】"></a></html>'''
        adapter = PremiumBandaiApplicationAdapter(fetcher=lambda _url: html)
        hits, _ = adapter.search_candidate({
            "tcg_key": "onepiece",
            "name": "ブースターパック 世界最強の戦士【OP-17】",
            "product_code": "OP-17",
        })
        self.assertEqual(1, len(hits))
        self.assertFalse(hits[0]["confirmed"])
        self.assertEqual("candidate", hits[0]["verification_status"])
        self.assertFalse(hits[0].get("application_end_at"))

    def test_premium_bandai_name_match_does_not_expand_to_other_onepiece_items(self):
        candidate = {"name": "ONE PIECEカードゲーム 4th Anniversary Set"}
        self.assertTrue(PremiumBandaiApplicationAdapter.matches_candidate(
            candidate, "【抽選販売】ONEPIECEカードゲーム 4th Anniversary Set"
        ))
        self.assertFalse(PremiumBandaiApplicationAdapter.matches_candidate(
            candidate, "【抽選販売】ONE PIECEカードゲーム ブースターパック OP-17"
        ))

    def test_magi_same_anniversary_series_does_not_merge_distinct_products(self):
        booster = {"name": "拡張パック 30th CELEBRATION"}
        deck_post = "30th CELEBRATION プレミアムデッキセット 抽選販売"
        future_post = "30th CELEBRATION FUTURISTIC BOX 抽選販売"
        self.assertFalse(MagiApplicationAdapter.matches_candidate(booster, deck_post))
        self.assertFalse(MagiApplicationAdapter.matches_candidate(booster, future_post))

    def test_candidate_only_hit_is_not_auto_promoted(self):
        manager = CandidateManager(Path(tempfile.mkdtemp()))
        manager._upsert_product_from_candidate = Mock()
        candidates = [{"id": "c1", "retail_hits": []}]
        updated = manager.update_search_result(
            "c1",
            hits=[{
                "site_key": "premium_bandai",
                "url": "https://p-bandai.jp/item/item-1/",
                "verification_status": "candidate",
            }],
            messages=[],
            candidates=candidates,
            save=False,
        )
        self.assertFalse(updated["approved"])
        self.assertEqual(1, len(updated["retail_hits"]))
        manager._upsert_product_from_candidate.assert_not_called()

    def test_confirmed_hit_keeps_existing_auto_promotion(self):
        manager = CandidateManager(Path(tempfile.mkdtemp()))
        manager._upsert_product_from_candidate = Mock()
        candidates = [{"id": "c1", "retail_hits": []}]
        updated = manager.update_search_result(
            "c1",
            hits=[{
                "site_key": "magi_official",
                "url": "https://magi.camp/news/1/web",
                "verification_status": "confirmed",
            }],
            messages=[],
            candidates=candidates,
            save=False,
        )
        self.assertTrue(updated["approved"])
        manager._upsert_product_from_candidate.assert_called_once()


if __name__ == "__main__":
    unittest.main()
