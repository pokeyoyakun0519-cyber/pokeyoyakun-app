from __future__ import annotations

import json
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "app"))

from core.x_monitoring_status import XMonitoringStatus
from core.x_recent_search import XRecentSearch


TARGETS = {
    "pokemon",
    "onepiece",
    "union_arena",
    "dragon_ball_fusion_world",
}


class XTrustedExpansionTest(unittest.TestCase):
    def test_each_target_tcg_has_at_least_five_enabled_accounts(self):
        accounts = XRecentSearch(PROJECT_ROOT).load_trusted_accounts()
        counts = Counter(
            item["tcg"] for item in accounts if item.get("enabled", True)
        )
        for tcg in TARGETS:
            self.assertGreaterEqual(counts[tcg], 5, tcg)
        usernames = {item["username"] for item in accounts}
        for existing in (
            "Pokemon_cojp",
            "ONEPIECE_tcg",
            "UNION_ARENA_TCG",
            "dbfw_cardgameJP",
            "HBSTsendai",
            "ikebukuro_labo",
        ):
            self.assertIn(existing, usernames)

    def test_every_account_has_supported_trust_level(self):
        accounts = XRecentSearch(PROJECT_ROOT).load_trusted_accounts()
        allowed = {
            "OFFICIAL_TCG",
            "OFFICIAL_STORE",
            "TRUSTED_CHAIN",
            "TRUSTED_STORE",
            "INFO_ACCOUNT",
        }
        self.assertTrue(accounts)
        self.assertTrue(all(item["trust_level"] in allowed for item in accounts))

    def test_candidate_carries_trust_and_supply_category(self):
        client = XRecentSearch(PROJECT_ROOT)
        item = client._candidate(
            {
                "id": "100",
                "author_id": "1",
                "text": "ポケカ 公式スリーブ 予約受付",
                "entities": {"urls": []},
            },
            {"username": "Pokemon_cojp", "name": "ポケモン公式"},
            "pokemon",
        )
        self.assertEqual(item["trust_level"], "OFFICIAL_TCG")
        self.assertEqual(item["source_type"], "official_x")
        self.assertEqual(item["product_category"], "SUPPLY")
        self.assertEqual(item["verification_status"], "pending")

    def test_info_account_and_official_x_alone_never_confirm(self):
        client = XRecentSearch(PROJECT_ROOT)
        candidate = {
            "tcg_key": "pokemon",
            "product_text": "商品A",
            "store_text": "",
            "application_url": "https://official.example/apply",
            "trust_level": "INFO_ACCOUNT",
            "evidence": [],
            "confidence": 60,
        }
        verified = client.verify_candidate(
            candidate,
            [{
                "tcg_key": "pokemon",
                "product_text": "商品A",
                "source_type": "official_x",
                "url": "https://official.example/apply",
            }],
        )
        self.assertEqual(verified["verification_status"], "pending")

    def test_period_change_updates_same_application_and_cancel_rejects(self):
        client = XRecentSearch(PROJECT_ROOT)
        base = {
            "tcg_key": "pokemon",
            "x_account": "Pokemon_cojp",
            "product_text": "商品A",
            "store_text": "公式店",
            "application_url": "https://official.example/apply",
            "verification_status": "confirmed",
            "confirmed": True,
            "detected_at": "2026-08-20T01:00:00+00:00",
            "x_post_id": "1",
            "evidence": [{"source_type": "x_api", "url": "https://x.com/a/1"}],
        }
        changed = {
            **base,
            "x_post_id": "2",
            "deadline_hint": "8月25日",
            "detected_at": "2026-08-20T02:00:00+00:00",
            "evidence": [{"source_type": "x_api", "url": "https://x.com/a/2"}],
        }
        merged = client._coalesce_updates([base, changed])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["deadline_hint"], "8月25日")
        self.assertEqual(merged[0]["x_post_ids"], ["1", "2"])

        canceled = client.verify_candidate(
            {**changed, "lifecycle_status": "cancelled", "trust_level": "OFFICIAL_TCG"},
            [],
        )
        self.assertEqual(canceled["verification_status"], "rejected")

    def test_confirmed_candidate_promotes_to_application_payload(self):
        client = XRecentSearch(PROJECT_ROOT)
        item = {
            "tcg_key": "pokemon",
            "tcg": "Pokemon",
            "product_text": "商品A",
            "product_category": "CARD",
            "application_url": "https://official.example/apply",
            "verification_status": "confirmed",
            "confirmed": True,
            "store_text": "公式店",
            "sales_method_hint": "ONLINE",
            "prefecture": "UNKNOWN",
            "evidence": [{"source_type": "official_application_page", "url": "https://official.example/apply"}],
        }
        with patch("core.product_store.ProductStore") as store_class:
            store_class.return_value.merge_discovered_products.return_value = ([], 1)
            promoted = client._promote_confirmed([item])
        self.assertEqual(promoted, 1)
        payload = store_class.return_value.merge_discovered_products.call_args.args[0][0]
        self.assertEqual(payload["sites"][0]["verification_status"], "confirmed")
        self.assertEqual(payload["sites"][0]["prefecture"], "UNKNOWN")

    def test_monitoring_status_reads_saved_state_without_network(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.joinpath("config").mkdir()
            root.joinpath("cache").mkdir()
            root.joinpath("data").mkdir()
            account = {
                "username": "shop",
                "display_name": "公式店",
                "category": "store_official",
                "store_name": "公式店",
                "tcg": "pokemon",
                "trust_level": "TRUSTED_STORE",
                "trust_score": 90,
                "enabled": True,
            }
            root.joinpath("config", "trusted_x_accounts.json").write_text(
                json.dumps([account]), encoding="utf-8"
            )
            root.joinpath("cache", "x_recent_search_state.json").write_text(
                json.dumps({"timeline": {"shop:pokemon": {"last_request_at": 1}}}),
                encoding="utf-8",
            )
            root.joinpath("data", "information_candidates.json").write_text(
                json.dumps([{
                    "x_account": "shop", "tcg_key": "pokemon",
                    "verification_status": "confirmed", "detected_at": "2026-08-20T00:00:00Z",
                }]),
                encoding="utf-8",
            )
            rows = XMonitoringStatus(root).rows()
            self.assertEqual(rows[0]["confirmed_count"], 1)
            self.assertTrue(rows[0]["last_fetch"])

    def test_monitoring_ui_and_refresh_pipeline_are_connected(self):
        sources_ui = (PROJECT_ROOT / "app" / "ui" / "sources_page.py").read_text(
            encoding="utf-8"
        )
        main_ui = (PROJECT_ROOT / "app" / "ui" / "main_window.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("SNS情報監視", sources_ui)
        self.assertNotIn("monitor.rows()", sources_ui)
        self.assertIn('x_recent.get("promoted_count")', main_ui)


if __name__ == "__main__":
    unittest.main()
