from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from email.message import Message

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.nyuka_now_discovery import (
    CANDIDATE,
    CONFIRMED,
    NYUKA_NOW_INDEX,
    OfficialVerificationQueue,
    NyukaNowDiscovery,
    TIER_B_DISCOVERY,
    discovery_source_diagnostics,
    merge_discovery_candidates,
    official_verification_from_document,
)


def _index(*ids: int) -> str:
    links = "".join(
        f'<h2><a href="https://nyuka-now.com/archives/{value}">記事{value}</a></h2>'
        for value in ids
    )
    return f"<html><body>{links}<a href='/archives/category/news/page/2/'>Next</a></body></html>"


def _article(tcg_text: str, *, store: str = "カードラボ", destination: str = "") -> str:
    link = f'<a href="{destination}">公式応募ページ</a>' if destination else ""
    return f"""
    <html><head>
      <meta property="article:published_time" content="2026-08-22T07:00:00+09:00">
      <meta property="og:title" content="{tcg_text} {store} 抽選受付">
    </head><body><article><h1>{tcg_text} {store} 抽選受付</h1>
      <p>{tcg_text} 新商品「テストブースター」 抽選受付 店頭受取</p>{link}
    </article><aside>ポケモンカード ワンピースカードゲーム</aside></body></html>
    """


class NyukaNowDiscoveryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.sensor = NyukaNowDiscovery(
            self.root, now=lambda: datetime(2026, 8, 22, tzinfo=timezone.utc)
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_index_fixture_extracts_only_unique_new_article_urls(self):
        articles = self.sensor.parse_index(_index(101, 102, 101))
        self.assertEqual([101, 102], [int(item["url"].rsplit("/", 1)[-1]) for item in articles])

    def test_seen_article_does_not_create_candidate_twice(self):
        url = "https://nyuka-now.com/archives/101"
        first = self.sensor.discover_from_documents(
            _index(101), {url: _article("ポケモンカード")}
        )
        second = self.sensor.discover_from_documents(
            _index(101), {url: _article("ポケモンカード")}
        )
        self.assertEqual(1, len(first))
        self.assertEqual([], second)

    def test_ttl_cache_prevents_repeated_index_request(self):
        calls = []

        class Response:
            def __init__(self):
                self.headers = Message()
                self.headers["ETag"] = '"fixture"'

            def read(self):
                return b"<html></html>"

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        def opener(request, **_kwargs):
            calls.append(request)
            return Response()

        sensor = NyukaNowDiscovery(
            self.root, opener=opener,
            now=lambda: datetime(2026, 8, 22, tzinfo=timezone.utc),
        )
        self.assertEqual([], sensor.poll())
        self.assertEqual([], sensor.poll())
        self.assertEqual(1, len(calls))
        self.assertEqual(1, sensor.diagnostics()["cache_hit"])

    def test_three_priority_tcgs_are_normalized(self):
        cases = (
            ("ポケモンカード", "pokemon"),
            ("ONE PIECEカードゲーム OP-17", "onepiece"),
            ("ドラゴンボールカードゲーム フュージョンワールド FB11", "dragon_ball_fusion_world"),
        )
        for index, (text, expected) in enumerate(cases, 201):
            with self.subTest(tcg=expected):
                candidate = self.sensor.parse_article(
                    _article(text), f"https://nyuka-now.com/archives/{index}"
                )
                self.assertIsNotNone(candidate)
                self.assertEqual(expected, candidate["tcg_key"])

    def test_sidebar_tcg_tags_do_not_misclassify_unrelated_article(self):
        html = """
        <html><body><article><h1>魂ネイションズ新製品</h1>
        <p>フィギュアの予約受付情報です。</p></article>
        <aside>ポケモンカード ワンピースカードゲーム</aside></body></html>
        """
        self.assertIsNone(self.sensor.parse_article(
            html, "https://nyuka-now.com/archives/999"
        ))

    def test_official_link_is_verification_candidate_not_official_evidence(self):
        candidate = self.sensor.parse_article(
            _article(
                "ポケモンカード", destination="https://www.cardlabo.com/shop/lottery?utm_source=test"
            ),
            "https://nyuka-now.com/archives/301",
        )
        self.assertEqual(
            "https://www.cardlabo.com/shop/lottery",
            candidate["official_destination_candidates"][0]["url"],
        )
        self.assertEqual(TIER_B_DISCOVERY, candidate["trust_tier"])
        self.assertEqual(CANDIDATE, candidate["verification_status"])

    def test_discovery_alone_never_confirms_or_sets_sales_mode(self):
        candidate = self.sensor.parse_article(
            _article("ポケモンカード"), "https://nyuka-now.com/archives/302"
        )
        self.assertEqual("STORE", candidate["sales_mode_hint"])
        self.assertEqual("UNKNOWN", candidate["sales_mode"])
        self.assertFalse(candidate["confirmed"])

    def test_official_evidence_can_confirm_after_verification(self):
        candidate = self.sensor.parse_article(
            _article("ポケモンカード"), "https://nyuka-now.com/archives/303"
        )
        queue = OfficialVerificationQueue()
        queue.enqueue([candidate])
        verified = queue.verify_next(lambda _item: {
            "application_type": "LOTTERY",
            "application_url": "https://www.cardlabo.com/lottery/303",
            "application_end_at": "2026-08-24T23:59:00+09:00",
            "sales_mode": "STORE",
            "evidence": [{
                "source_type": "OFFICIAL_STORE",
                "source_url": "https://www.cardlabo.com/lottery/303",
                "trust": 100,
                "verification_status": CONFIRMED,
                "extracted_fields": {"application_end_at": "2026-08-24T23:59:00+09:00"},
            }],
        })
        self.assertEqual(CONFIRMED, verified["verification_status"])
        self.assertTrue(verified["confirmed"])
        self.assertEqual(1, queue.official_verified)

    def test_known_official_document_builds_tier_a_evidence(self):
        candidate = self.sensor.parse_article(
            _article("ポケモンカード"), "https://nyuka-now.com/archives/306"
        )
        official = official_verification_from_document(
            candidate,
            "https://www.cardlabo.com/lottery/306",
            "<article>ポケモンカード 抽選受付 "
            + candidate["product_name"]
            + " 店頭受取</article>",
        )
        self.assertIsNotNone(official)
        self.assertEqual("TIER_A_OFFICIAL", official["trust_tier"])
        queue = OfficialVerificationQueue()
        queue.enqueue([candidate])
        self.assertEqual(CONFIRMED, queue.verify_next(lambda _item: official)["verification_status"])

    def test_verification_failure_keeps_candidate(self):
        candidate = self.sensor.parse_article(
            _article("ONE PIECEカードゲーム OP-17"),
            "https://nyuka-now.com/archives/304",
        )
        queue = OfficialVerificationQueue()
        queue.enqueue([candidate])
        result = queue.verify_next(lambda _item: None)
        self.assertEqual(CANDIDATE, result["verification_status"])
        self.assertEqual("official_verification_failed", result["verification_error"])

    def test_multiple_discovery_sources_dedupe_and_raise_priority(self):
        first = self.sensor.parse_article(
            _article("ポケモンカード"), "https://nyuka-now.com/archives/305"
        )
        second = dict(first)
        second["source_article_url"] = "https://another.example/articles/1"
        second["source_url"] = second["source_article_url"]
        second["evidence_sources"] = [second["source_article_url"]]
        merged = merge_discovery_candidates([first, second])
        self.assertEqual(1, len(merged))
        self.assertEqual(2, len(merged[0]["evidence_sources"]))
        queued = OfficialVerificationQueue().enqueue(merged)
        self.assertEqual("HIGH", queued[0]["verification_priority"])

    def test_diagnostics_exposes_tiers_and_only_safe_source_auto_enabled(self):
        diagnostics = discovery_source_diagnostics(official_source_count=70)
        self.assertEqual(70, diagnostics["by_trust_tier"]["TIER_A_OFFICIAL"])
        self.assertGreaterEqual(diagnostics["by_trust_tier"]["TIER_B_DISCOVERY"], 1)
        self.assertGreaterEqual(diagnostics["by_trust_tier"]["TIER_C_REFERENCE"], 1)
        self.assertEqual(["nyuka_now"], diagnostics["auto_enabled"])
        self.assertEqual(NYUKA_NOW_INDEX, diagnostics["sources"][0]["url"])


if __name__ == "__main__":
    unittest.main()
