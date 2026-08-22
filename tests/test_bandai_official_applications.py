from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from core.application_dashboard import ApplicationDashboard
from core.bandai_official_applications import (
    BandaiOfficialApplicationMonitor,
    BandaiOfficialApplicationParser,
    normalize_bandai_tcg,
    parse_application_dates,
)
from core.candidate_manager import CandidateManager
from core.card_labo_parser import CardLaboParser
from core.config_manager import ConfigManager
from core.product_store import ProductStore


ONE_PIECE_URL = (
    "https://parks2.bandainamco-am.co.jp/category/ECCL00000054/"
    "ECCL00000054_20260822_25_004.html"
)
DBFW_URL = (
    "https://parks2.bandainamco-am.co.jp/category/TITLE/"
    "ECCL00000052_20260808_09_008.html"
)


def application_html(tcg: str) -> str:
    if tcg == "onepiece":
        return """
        <html><head><title>【大阪梅田店】8/22~26【抽選申込】 ONE PIECEカードゲーム</title></head>
        <body><main>
        <h1>【大阪梅田店】8/22~26【抽選申込】 ONE PIECEカードゲーム</h1>
        <p>申込開始</p><p>2026/08/12 10:00から</p>
        <p>申込終了</p><p>2026/08/16 23:59まで</p>
        <p>当選発表</p><p>2026/08/17 17:00</p>
        <p>販売は＜ONE PIECE カードゲーム 公式ショップ 大阪梅田店＞店頭での購入となります。</p>
        <p>商品名：ブースターパック 世界最強の戦士【OP-17】</p>
        </main></body></html>
        """
    return """
    <html><head><title>【東京店】8/8・9【抽選申込】 DBFW</title></head>
    <body><main>
    <h1>【東京店】8/8・9【抽選申込】 ドラゴンボールスーパーカードゲーム フュージョンワールド</h1>
    <p>申込開始</p><p>2026/07/29 10:00から</p>
    <p>申込終了</p><p>2026/08/02 23:59まで</p>
    <p>当選発表</p><p>2026/08/03 17:00</p>
    <p>販売は＜ドラゴンボールスーパーカードゲーム フュージョンワールド オフィシャルストア 東京店＞店頭での購入のみです。</p>
    <p>商品名：STORY BOOSTER 01 [ST01]</p>
    </main></body></html>
    """


class BandaiOfficialApplicationsTest(unittest.TestCase):
    def test_one_piece_normalization_variants_and_prefix_guard(self):
        for value in (
            "ONE PIECEカードゲーム", "ONE PIECE CARD GAME", "ワンピースカード",
            "ワンピカード", "ONE PIECE OP-17", "ワンピ EB-03",
            "ONE PIECE PRB-02", "ワンピース ST-21",
        ):
            with self.subTest(value=value):
                self.assertEqual("onepiece", normalize_bandai_tcg(value))
        self.assertEqual("other", normalize_bandai_tcg("店舗番号 OP-17"))

    def test_dbfw_normalization_variants_and_masters_guard(self):
        for value in (
            "DRAGON BALL SUPER CARD GAME FUSION WORLD", "FUSION WORLD",
            "DBSCG FW", "DBFW", "ドラゴンボール FB-11",
            "DBSCG SB-02", "ドラゴンボール FS-08",
        ):
            with self.subTest(value=value):
                self.assertEqual("dragon_ball_fusion_world", normalize_bandai_tcg(value))
        self.assertEqual("other", normalize_bandai_tcg("DRAGON BALL SUPER CARD GAME MASTERS FB-01"))
        self.assertEqual("other", normalize_bandai_tcg("商品棚 FS-08"))

    def test_application_date_formats_require_safe_reference_for_missing_year(self):
        full = parse_application_dates(
            "応募開始：2026年8月22日(土) 12:00 締切：2026/08/24 23:59"
        )
        self.assertEqual("2026-08-22T12:00+09:00", full["application_start_at"])
        self.assertEqual("2026-08-24T23:59+09:00", full["application_end_at"])
        omitted = parse_application_dates(
            "応募期間：8月22日(土) 12:00～8月24日 23:59",
            reference_date=datetime(2026, 8, 20),
        )
        self.assertEqual("2026-08-22T12:00+09:00", omitted["application_start_at"])
        self.assertEqual("2026-08-24T23:59+09:00", omitted["application_end_at"])
        self.assertEqual({}, parse_application_dates("応募期間：8/22～8/24"))
        same_day = parse_application_dates(
            "当日18時まで", reference_date=datetime(2026, 8, 22)
        )
        self.assertEqual("2026-08-22T18:00+09:00", same_day["application_end_at"])

    def test_official_parsers_produce_confirmed_store_evidence(self):
        one_piece = BandaiOfficialApplicationParser.parse(
            application_html("onepiece"), ONE_PIECE_URL
        )
        dbfw = BandaiOfficialApplicationParser.parse(application_html("dbfw"), DBFW_URL)
        self.assertIsNotNone(one_piece)
        self.assertIsNotNone(dbfw)
        self.assertEqual("onepiece", one_piece["tcg_key"])
        self.assertEqual("dragon_ball_fusion_world", dbfw["tcg_key"])
        self.assertTrue(one_piece["confirmed"])
        self.assertTrue(dbfw["confirmed"])
        self.assertEqual("OFFICIAL_SHOP_BRANCH", one_piece["evidence"][0]["source_type"])
        self.assertEqual("STORE", one_piece["hit"]["sales_mode"])
        self.assertEqual("大阪府", one_piece["hit"]["prefecture"])
        self.assertEqual("東京都", dbfw["hit"]["prefecture"])

    def test_official_domain_and_required_fields_are_not_relaxed(self):
        self.assertIsNone(BandaiOfficialApplicationParser.parse(
            application_html("onepiece"), "https://example.invalid/application"
        ))
        self.assertIsNone(BandaiOfficialApplicationParser.parse(
            "<p>ONE PIECEカードゲーム 商品名：OP-17</p>", ONE_PIECE_URL
        ))

    def test_index_news_application_scan_deduplicates_and_confirms(self):
        one_index = "https://bandainamco-am.co.jp/official_shop/onepiece-cardgame/index.html"
        news = "https://bandainamco-am.co.jp/official_shop/onepiece-cardgame/news/important/20260810.html"
        documents = {
            one_index: f'<a href="{news}">抽選販売</a>',
            news: f'<a href="{ONE_PIECE_URL}">大阪梅田店</a><a href="{ONE_PIECE_URL}">重複</a>',
            ONE_PIECE_URL: application_html("onepiece"),
        }

        def fetch(url):
            return {"ok": url in documents, "html": documents.get(url, "")}

        monitor = BandaiOfficialApplicationMonitor(fetch)
        found = monitor.scan({"onepiece"})
        self.assertEqual(1, len(found))
        self.assertEqual(1, monitor.diagnostics["confirmed"])
        self.assertEqual(1, monitor.diagnostics["duplicate"])

    def test_confirmed_to_storage_to_dashboard_and_ended_retention(self):
        records = [
            BandaiOfficialApplicationParser.parse(application_html("onepiece"), ONE_PIECE_URL),
            BandaiOfficialApplicationParser.parse(application_html("dbfw"), DBFW_URL),
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manager = CandidateManager(root)
            result = manager.merge_application_discoveries(
                [{"record": record, "hit": record["hit"]} for record in records],
                matcher=CardLaboParser._matches_candidate,
            )
            dashboard = ApplicationDashboard(ProductStore(root), ConfigManager(root))
            one = dashboard.build(
                tcg_filter="onepiece", sales_mode_filter="STORE",
                prefecture_filter="大阪府", show_ended=True,
                now=datetime.fromisoformat("2026-08-22T12:00:00+09:00"),
            )
            db = dashboard.build(
                tcg_filter="dragon_ball_fusion_world", period_filter="ended",
                show_ended=True, now=datetime.fromisoformat("2026-08-10T12:00:00+09:00"),
            )
            db_outside_retention = dashboard.build(
                tcg_filter="dragon_ball_fusion_world", show_ended=True,
                now=datetime.fromisoformat("2026-08-22T12:00:00+09:00"),
            )
        self.assertEqual({"created": 2, "updated": 2, "ambiguous": 0}, result)
        self.assertEqual(1, len(one["rows"]))
        self.assertTrue(one["rows"][0]["period_ended"])
        self.assertEqual(1, len(one["groups"]))
        self.assertEqual(ONE_PIECE_URL, one["rows"][0]["application_url"])
        self.assertEqual(1, len(db["rows"]))
        self.assertTrue(db["rows"][0]["period_ended"])
        self.assertEqual([], db_outside_retention["rows"])

    def test_multi_branch_expansion_and_dedupe(self):
        record = BandaiOfficialApplicationParser.parse(
            application_html("onepiece"), ONE_PIECE_URL
        )
        site = dict(record["hit"])
        site["target_store_details"] = [
            {"branch": "大阪梅田店", "prefecture": "大阪府"},
            {"branch": "東京新宿店", "prefecture": "東京都"},
            {"branch": "東京新宿店", "prefecture": "東京都"},
        ]
        product = {
            "id": "op17-branches", "name": record["product_name"],
            "tcg_key": "onepiece", "release_date": "2026-08-22", "sites": [site],
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = ProductStore(root)
            store.merge_discovered_products([product])
            rows = ApplicationDashboard(store, ConfigManager(root)).build(
                show_ended=True, now=datetime.fromisoformat("2026-08-22T12:00:00+09:00")
            )["rows"]
        self.assertEqual(2, len(rows))
        self.assertEqual({"大阪府", "東京都"}, {row["prefecture"] for row in rows})


if __name__ == "__main__":
    unittest.main()
