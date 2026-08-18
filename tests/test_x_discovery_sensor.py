import io
import json
import tempfile
import unittest
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from core.x_recent_search import XRecentSearch


class _Response:
    def __init__(self, payload, headers=None):
        self.payload = json.dumps(payload).encode("utf-8")
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, *_args):
        return self.payload


class XDiscoverySensorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "config").mkdir()
        (self.root / "config" / "trusted_x_accounts.json").write_text(
            json.dumps([{
                "username": "shop", "display_name": "公式店", "category": "store_official",
                "store_name": "カード店", "tcg": "pokemon", "trust_score": 90,
                "enabled": True, "user_id": "12345",
            }]), encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def _payload(text="ポケカ 新商品A WEB抽選 応募締切8月20日 18:00",
                 url="https://shop.example/apply", newest="101"):
        return {"data": [{"id": newest, "author_id": "12345", "text": text,
                           "created_at": "2026-08-19T00:00:00Z",
                           "entities": {"urls": [{"expanded_url": url}]}}],
                "includes": {"users": [{"id": "12345", "username": "shop", "name": "公式店"}]},
                "meta": {"newest_id": newest}}

    def _client(self, payload=None):
        opener = Mock()
        opener.open.return_value = _Response(payload or self._payload())
        return XRecentSearch(self.root, opener=opener,
                             now=lambda: datetime(2026, 8, 19, tzinfo=timezone.utc)), opener

    def test_candidate_has_required_discovery_fields_and_x_never_confirms(self):
        client, _ = self._client()
        item = client.search("pokemon", "secret-token")["candidates"][0]
        required = {"source_type", "source_url", "x_post_id", "x_account", "detected_at",
                    "tcg", "product_text", "store_text", "sales_method_hint", "deadline_hint",
                    "confidence", "evidence", "verification_status"}
        self.assertTrue(required <= set(item))
        self.assertEqual("pending", item["verification_status"])
        self.assertFalse(item["confirmed"])
        self.assertEqual("ONLINE", item["sales_method_hint"])
        self.assertEqual("UNKNOWN", item["prefecture"])

    def test_official_application_match_promotes_candidate(self):
        client, _ = self._client()
        candidate = client.search("pokemon", "token")["candidates"][0]
        verified = client.verify_candidate(candidate, [{
            "source_type": "official_application_page", "tcg_key": "pokemon",
            "url": "https://shop.example/apply", "product_text": "新商品A",
            "prefecture": "東京都",
        }])
        self.assertTrue(verified["confirmed"])
        self.assertEqual("confirmed", verified["verification_status"])
        self.assertEqual("東京都", verified["prefecture"])

    def test_official_rejection_marks_candidate_rejected(self):
        client, _ = self._client()
        candidate = client.search("pokemon", "token")["candidates"][0]
        rejected = client.verify_candidate(candidate, [{
            "source_type": "official_store_page", "tcg_key": "pokemon",
            "url": "https://shop.example/apply", "status": "cancelled",
        }])
        self.assertFalse(rejected["confirmed"])
        self.assertEqual("rejected", rejected["verification_status"])

    def test_non_official_url_cannot_verify(self):
        client, _ = self._client()
        candidate = client.search("pokemon", "token")["candidates"][0]
        result = client.verify_candidate(candidate, [{
            "source_type": "blog", "tcg_key": "pokemon",
            "url": "https://shop.example/apply",
        }])
        self.assertEqual("pending", result["verification_status"])

    def test_product_page_or_official_x_alone_cannot_confirm_sale(self):
        client, _ = self._client()
        candidate = client.search("pokemon", "token")["candidates"][0]
        for source_type in ("official_product_page", "official_x"):
            with self.subTest(source_type=source_type):
                result = client.verify_candidate(candidate, [{
                    "source_type": source_type, "tcg_key": "pokemon",
                    "url": "https://shop.example/apply",
                }])
                self.assertFalse(result["confirmed"])
                self.assertEqual("pending", result["verification_status"])

    def test_timeline_uses_api_since_id_and_ttl(self):
        client, opener = self._client()
        account = client.load_trusted_accounts()[0]
        first = client.search_trusted_timeline(account, "token")
        second = client.search_trusted_timeline(account, "token")
        self.assertEqual("ok", first["status"])
        self.assertIn("/2/users/12345/tweets", opener.open.call_args.args[0].full_url)
        self.assertEqual("ttl", second["status"])
        self.assertEqual(1, opener.open.call_count)

    def test_timeline_resolves_and_caches_user_id_through_x_api(self):
        account = self._client()[0].load_trusted_accounts()[0]
        account.pop("user_id")
        opener = Mock()
        opener.open.side_effect = [
            _Response({"data": {"id": "12345"}}), _Response(self._payload()),
        ]
        client = XRecentSearch(self.root, opener=opener)
        result = client.search_trusted_timeline(account, "token")
        self.assertEqual("ok", result["status"])
        self.assertEqual(2, result["request_count"])
        self.assertIn("/2/users/by/username/shop", opener.open.call_args_list[0].args[0].full_url)
        state = json.loads((self.root / "cache" / "x_recent_search_state.json").read_text("utf-8"))
        self.assertEqual("12345", state["user_ids"]["shop"])

    def test_duplicate_post_is_replaced_by_id(self):
        client, opener = self._client()
        client.search_and_store({"pokemon"}, "token")
        opener.open.return_value = _Response(self._payload(newest="101"))
        client.search_and_store({"pokemon"}, "token")
        saved = json.loads((self.root / "data" / "information_candidates.json").read_text("utf-8"))
        self.assertEqual(1, len(saved))

    def test_trusted_timeline_accounts_rotate_between_runs(self):
        client, _ = self._client()
        accounts = client.load_trusted_accounts()
        accounts.append({**accounts[0], "username": "shop2", "user_id": "67890"})
        self.assertEqual("shop", client._next_timeline_account(accounts, "pokemon")["username"])
        self.assertEqual("shop2", client._next_timeline_account(accounts, "pokemon")["username"])
        self.assertEqual("shop", client._next_timeline_account(accounts, "pokemon")["username"])

    def test_429_metrics_and_backoff_do_not_retry(self):
        opener = Mock()
        opener.open.side_effect = urllib.error.HTTPError(
            "https://api.x.com", 429, "rate", {"x-rate-limit-reset": "0"}, io.BytesIO())
        client = XRecentSearch(self.root, opener=opener)
        result = client.search("pokemon", "token")
        self.assertEqual(1, result["rate_limit_429"])
        self.assertEqual(1, opener.open.call_count)
        self.assertEqual("backoff", client.search("pokemon", "token")["status"])
        self.assertEqual(1, opener.open.call_count)

    def test_missing_token_never_requests_or_logs_secret(self):
        opener = Mock()
        with patch.dict("os.environ", {}, clear=True):
            result = XRecentSearch(self.root, opener=opener).search("pokemon")
        self.assertEqual("disabled", result["status"])
        opener.open.assert_not_called()

    def test_sales_method_and_prefecture_safety(self):
        self.assertEqual("STORE", XRecentSearch.infer_sales_method("店頭販売"))
        self.assertEqual("HYBRID", XRecentSearch.infer_sales_method("WEB応募後に店頭受取"))
        self.assertEqual("UNKNOWN", XRecentSearch.infer_sales_method("予約受付"))
        client, _ = self._client(self._payload(text="ポケカ 新商品A 仙台で予約受付", url=""))
        item = client.search("pokemon", "token")["candidates"][0]
        self.assertEqual("UNKNOWN", item["prefecture"])


if __name__ == "__main__":
    unittest.main()
