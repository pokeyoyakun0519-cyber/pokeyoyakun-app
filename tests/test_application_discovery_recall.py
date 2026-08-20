from __future__ import annotations

import io
import json
import tempfile
import unittest
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from core.application_discovery import (
    ACTIVE,
    CANDIDATE,
    CONFIRMED,
    EXPIRED,
    REJECTED,
    UPCOMING,
    deduplicate_applications,
    match_product_reference,
    normalize_store_reference,
    parse_discovery_post,
    resolve_candidate,
    temporal_state,
)
from core.trusted_x_accounts import TrustedXAccountRegistry
from core.x_recent_search import XRecentSearch


JST = timezone(timedelta(hours=9))


class _Response:
    def __init__(self, payload: dict, headers: dict | None = None):
        self.payload = json.dumps(payload).encode("utf-8")
        self.headers = headers or {
            "x-rate-limit-remaining": "74",
            "x-rate-limit-limit": "75",
            "x-rate-limit-reset": "0",
        }

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _size=-1):
        return self.payload


def _evidence(source_type="OFFICIAL_SHOP_BRANCH", trust=90, url="https://x.com/store/status/1"):
    return [{
        "source_type": source_type,
        "source_url": url,
        "observed_at": "2026-08-16T00:00:00+00:00",
        "trust": trust,
        "extracted_fields": {"product_name": "新弾"},
        "verification_status": "observed",
    }]


class ApplicationDiscoveryRuleTest(unittest.TestCase):
    def test_official_store_explicit_lottery_is_confirmed(self):
        item = resolve_candidate({
            "tcg_key": "pokemon", "application_type": "LOTTERY",
            "application_url": "https://store.example/apply", "source_type": "OFFICIAL_SHOP_BRANCH",
            "manual_trust_score": 90, "evidence": _evidence(),
        })
        self.assertEqual(CONFIRMED, item["verification_status"])

    def test_trusted_information_stays_candidate_without_official_evidence(self):
        item = resolve_candidate({
            "tcg_key": "pokemon", "application_type": "LOTTERY",
            "application_url": "https://info.example/post", "source_type": "TRUSTED_INFORMATION",
            "manual_trust_score": 95, "evidence": _evidence("TRUSTED_INFORMATION", 95),
        })
        self.assertEqual(CANDIDATE, item["verification_status"])

    def test_general_user_stays_candidate(self):
        item = resolve_candidate({
            "tcg_key": "onepiece", "application_type": "RESERVATION",
            "application_url": "https://example/apply", "source_type": "GENERAL_INFORMATION",
            "evidence": _evidence("GENERAL_INFORMATION", 30),
        })
        self.assertFalse(item["confirmed"])

    def test_date_contradiction_is_rejected(self):
        item = resolve_candidate({
            "tcg_key": "pokemon", "application_type": "LOTTERY",
            "application_start_at": "2026-08-20T00:00:00+09:00",
            "application_end_at": "2026-08-19T00:00:00+09:00",
            "evidence": _evidence(),
        })
        self.assertEqual(REJECTED, item["verification_status"])

    def test_multiple_evidence_is_deduplicated_and_raises_confidence(self):
        one = resolve_candidate({"application_type": "LOTTERY", "evidence": _evidence()})
        three = resolve_candidate({
            "application_type": "LOTTERY",
            "evidence": [
                *_evidence(),
                *_evidence("TRUSTED_INFORMATION", 80, "https://x.com/info/status/2"),
                *_evidence("OFFICIAL_STORE", 95, "https://store.example/news"),
            ],
        })
        self.assertGreater(three["confidence"], one["confidence"])
        self.assertEqual(3, three["evidence_count"])

    def test_same_application_merges_evidence(self):
        base = {
            "tcg_key": "pokemon", "product_id": "p1", "store_id": "card_labo",
            "branch": "池袋", "application_end_at": "2026-08-20T23:59:00+09:00",
            "application_type": "LOTTERY",
        }
        merged = deduplicate_applications([
            {**base, "evidence": _evidence("TRUSTED_INFORMATION", 80)},
            {**base, "evidence": _evidence("OFFICIAL_SHOP_BRANCH", 90, "https://x.com/store/status/2")},
        ])
        self.assertEqual(1, len(merged))
        self.assertEqual(2, len(merged[0]["evidence"]))

    def test_different_branch_is_not_merged(self):
        base = {"tcg_key": "pokemon", "product_id": "p1", "store_id": "card_labo", "application_end_at": "2026-08-20"}
        self.assertEqual(2, len(deduplicate_applications([
            {**base, "branch": "池袋"}, {**base, "branch": "秋葉原"},
        ])))

    def test_store_alias_resolves_yodobashi_akiba(self):
        store = normalize_store_reference("ヨドバシ秋葉原")
        self.assertEqual("yodobashi", store["store_id"])
        self.assertEqual("マルチメディアAkiba", store["branch"])

    def test_post_extracts_store_branch(self):
        parsed = parse_discovery_post("カードラボ池袋店 ポケカ新弾 WEB抽選")
        self.assertEqual("card_labo", parsed["store_id"])
        self.assertEqual("池袋", parsed["branch"])

    def test_post_extracts_purchase_period_without_ai(self):
        parsed = parse_discovery_post(
            "ポケカ「新弾」抽選受付 購入期間: 8月20日10:00～8月22日20:00"
        )
        self.assertEqual("8月20日10:00~8月22日20:00", parsed["purchase_period"])

    def test_unknown_store_remains_ambiguous(self):
        self.assertTrue(normalize_store_reference("名称不明の店舗")["store_ambiguous"])

    def test_tcg_abbreviations(self):
        cases = {
            "ポケカ新弾 抽選受付": "pokemon",
            "ワンピ新弾 予約受付": "onepiece",
            "ユニアリ UA58BT 再入荷": "union_arena",
            "DBFW FB11 抽選受付": "dragon_ball_fusion_world",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(expected, parse_discovery_post(text)["tcg_key"])

    def test_news_is_not_application(self):
        self.assertEqual("NEWS", parse_discovery_post("ポケカ新商品を紹介します")["application_type"])

    def test_negative_posts_are_irrelevant(self):
        for text in ("ポケカ買取情報", "ワンピカード大会結果", "ユニアリ プレゼント企画"):
            with self.subTest(text=text):
                self.assertEqual("IRRELEVANT", parse_discovery_post(text)["application_type"])

    def test_malformed_tweet_is_safe(self):
        self.assertEqual("NEWS", parse_discovery_post(None)["application_type"])

    def test_no_url_or_deadline_is_candidate(self):
        parsed = parse_discovery_post("ポケカ新弾 抽選受付")
        item = resolve_candidate({**parsed, "source_type": "OFFICIAL_STORE", "evidence": _evidence("OFFICIAL_STORE")})
        self.assertEqual(CANDIDATE, item["verification_status"])

    def test_trusted_information_becomes_confirmed_after_official_evidence(self):
        item = resolve_candidate({
            "tcg_key": "pokemon", "application_type": "LOTTERY",
            "application_url": "https://store.example/apply", "source_type": "TRUSTED_INFORMATION",
            "evidence": [
                *_evidence("TRUSTED_INFORMATION", 80),
                *_evidence("OFFICIAL_STORE", 95, "https://store.example/news"),
            ],
        })
        self.assertEqual(CONFIRMED, item["verification_status"])

    def test_product_code_matches_existing_product(self):
        result = match_product_reference(
            {"tcg_key": "dragon_ball_fusion_world", "product_code": "FB11", "product_name": "新弾"},
            [{"id": "p1", "tcg_key": "dragon_ball_fusion_world", "product_code": "FB11", "name": "BRIGHTNESS OF HOPE"}],
        )
        self.assertEqual("p1", result["product_id"])
        self.assertEqual(1.0, result["product_match_confidence"])

    def test_product_identifier_conflict_is_not_guessed(self):
        result = match_product_reference(
            {"tcg_key": "pokemon", "jan": "222", "product_name": "同名"},
            [{"id": "p1", "tcg_key": "pokemon", "jan": "111", "name": "同名"}],
        )
        self.assertNotIn("product_id", result)
        self.assertEqual(0.0, result["product_match_confidence"])

    def test_ai_failure_falls_back_to_rules(self):
        def broken(_text):
            raise RuntimeError("offline")
        parsed = parse_discovery_post("DBFW FB11 予約受付", ai_parser=broken)
        self.assertEqual("RESERVATION", parsed["application_type"])
        self.assertTrue(parsed["ai_fallback"])

    def test_temporal_active_upcoming_expired(self):
        now = datetime(2026, 8, 16, 12, tzinfo=JST)
        self.assertEqual(ACTIVE, temporal_state({"application_end_at": "2026-08-17T00:00:00+09:00"}, now=now))
        self.assertEqual(UPCOMING, temporal_state({"application_start_at": "2026-08-17T00:00:00+09:00"}, now=now))
        self.assertEqual(EXPIRED, temporal_state({"application_end_at": "2026-08-15T00:00:00+09:00"}, now=now))


class TrustedAccountTimelineTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "config").mkdir()
        (self.root / "config/trusted_x_accounts.json").write_text(json.dumps([{
            "user_id": "u1", "username": "official_store", "display_name": "カードラボ池袋店",
            "source_type": "OFFICIAL_SHOP_BRANCH", "store_name": "カードラボ池袋店",
            "tcg": "pokemon", "manual_trust_score": 90, "enabled": True, "memo": "fixture",
        }]), encoding="utf-8")
        self.clock = datetime(2026, 8, 16, tzinfo=timezone.utc)

    def tearDown(self):
        self.temp.cleanup()

    def payload(self, tweet_id="101"):
        return {
            "data": [{
                "id": tweet_id, "author_id": "u1", "created_at": "2026-08-16T00:00:00Z",
                "text": "ポケカ「新弾」WEB抽選 8月16日10:00～8月18日23:59",
                "entities": {"urls": [{"expanded_url": "https://www.c-labo.jp/apply"}]},
            }],
            "includes": {"users": [{"id": "u1", "username": "official_store", "name": "公式店"}]},
            "meta": {"newest_id": tweet_id},
        }

    def test_timeline_uses_user_endpoint_and_records_last_seen(self):
        opener = Mock(); opener.open.return_value = _Response(self.payload())
        result = XRecentSearch(self.root, opener=opener, now=lambda: self.clock).poll_trusted_account_timelines("pokemon", "token")
        self.assertEqual("ok", result["status"])
        self.assertIn("/2/users/u1/tweets", opener.open.call_args.args[0].full_url)
        account = TrustedXAccountRegistry(self.root).load_with_observations()[0]
        self.assertEqual("101", account["last_seen_tweet_id"])
        self.assertTrue(account["last_checked_at"])

    def test_timeline_second_poll_is_ttl_cache_hit(self):
        opener = Mock(); opener.open.return_value = _Response(self.payload())
        client = XRecentSearch(self.root, opener=opener, now=lambda: self.clock)
        client.poll_trusted_account_timelines("pokemon", "token")
        result = client.poll_trusted_account_timelines("pokemon", "token")
        self.assertEqual("cached", result["status"])
        self.assertEqual(1, opener.open.call_count)
        self.assertEqual(1, result["cache_hits"])

    def test_timeline_uses_since_id_after_ttl(self):
        opener = Mock(); opener.open.side_effect = [_Response(self.payload("101")), _Response(self.payload("102"))]
        client = XRecentSearch(self.root, opener=opener, now=lambda: self.clock)
        client.poll_trusted_account_timelines("pokemon", "token")
        self.clock += timedelta(minutes=16)
        client.poll_trusted_account_timelines("pokemon", "token")
        self.assertIn("since_id=101", opener.open.call_args.args[0].full_url)

    def test_timeline_rate_limit_honors_retry_after_and_has_no_loop(self):
        opener = Mock(); opener.open.side_effect = urllib.error.HTTPError(
            "https://api.x.com", 429, "rate",
            {"Retry-After": "120", "x-rate-limit-reset": "0", "x-rate-limit-remaining": "0"},
            io.BytesIO(),
        )
        client = XRecentSearch(self.root, opener=opener, now=lambda: self.clock, jitter=lambda _a, _b: 0)
        result = client.poll_trusted_account_timelines("pokemon", "token")
        self.assertEqual("rate_limited", result["status"])
        self.assertEqual(1, opener.open.call_count)
        self.assertGreaterEqual(result["request_count"], 1)

    def test_timeline_disabled_has_zero_http_and_notice(self):
        opener = Mock()
        with patch.dict("os.environ", {}, clear=True):
            result = XRecentSearch(self.root, opener=opener).poll_trusted_account_timelines("pokemon")
        self.assertEqual("disabled", result["status"])
        self.assertEqual(0, result["request_count"])
        self.assertIn("Discovery範囲", result["notice"])
        opener.open.assert_not_called()

    def test_rate_limit_headers_are_reported(self):
        opener = Mock(); opener.open.return_value = _Response(self.payload())
        result = XRecentSearch(self.root, opener=opener, now=lambda: self.clock).poll_trusted_account_timelines("pokemon", "token")
        self.assertEqual("74", result["rate_limit_remaining"])
        self.assertEqual("75", result["rate_limit_limit"])

    def test_official_timeline_candidate_requires_web_corroboration(self):
        opener = Mock(); opener.open.return_value = _Response(self.payload())
        item = XRecentSearch(self.root, opener=opener, now=lambda: self.clock).poll_trusted_account_timelines("pokemon", "token")["candidates"][0]
        self.assertFalse(item["confirmed"])
        self.assertEqual("pending", item["verification_status"])
        self.assertEqual("card_labo", item["store_id"])
        self.assertEqual("池袋", item["branch"])

    def test_general_search_preserves_store_extracted_from_post(self):
        client = XRecentSearch(self.root, opener=Mock(), now=lambda: self.clock)
        tweet = self.payload()["data"][0]
        tweet["text"] = "カードラボ池袋店 ポケカ新弾 WEB抽選"
        item = client._build_candidates(
            "pokemon", [tweet], {"u1": {"id": "u1", "username": "general"}},
            {}, monitored_only=False,
        )[0]
        self.assertEqual("card_labo", item["store_id"])
        self.assertEqual("池袋", item["branch"])


if __name__ == "__main__":
    unittest.main()
