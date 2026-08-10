from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.builtin_store_catalog import (
    CatalogValidationError,
    build_alias_index,
    load_builtin_store_catalog,
    match_builtin_store,
)
from core.retail_price_policy import RetailPricePolicy
from core.site_master_manager import DEFAULT_SITES, SiteMasterManager
from core.store_candidate_manager import CANDIDATE_STATES, StoreCandidateManager
from core.store_discovery import StoreDiscovery


class BuiltinStoreCatalogTest(unittest.TestCase):
    def setUp(self):
        self.catalog = load_builtin_store_catalog()
        self.stores = self.catalog["stores"]
        self.by_id = {item["canonical_store_id"]: item for item in self.stores}

    def test_catalog_is_versioned_complete_and_default_off(self):
        self.assertEqual(self.catalog["schema_version"], 1)
        self.assertGreaterEqual(len(self.stores), 57)
        self.assertTrue(all(not item["default_enabled"] for item in self.stores))
        required = {
            "yodobashi_physical", "yodobashi_online", "biccamera_physical",
            "biccamera_online", "card_labo", "cardbox", "aoki_toy",
            "pelican_toy", "aonekotei", "toreca_capital",
            "amazon_jp", "rakuten_books", "yahoo_shopping",
            "pokemon_center_online", "konami_style", "mugiwara_store",
        }
        self.assertFalse(required - set(self.by_id))

    def test_aliases_and_channels_share_store_group(self):
        aliases = build_alias_index(self.stores)
        self.assertEqual(aliases["clabo"], "card_labo")
        self.assertEqual(self.by_id["yodobashi_physical"]["store_group_id"], "yodobashi")
        self.assertEqual(self.by_id["yodobashi_online"]["store_group_id"], "yodobashi")
        self.assertNotEqual(self.by_id["yodobashi_physical"]["channel"], self.by_id["yodobashi_online"]["channel"])
        self.assertEqual(
            match_builtin_store(self.stores, name="未知の表記", url="https://www.yodobashi.com/")["store_group_id"],
            "yodobashi",
        )

    def test_partial_chain_and_unknown_tcg_are_not_overstated(self):
        partial = [item for item in self.stores if item["chain_support"] == "partial"]
        self.assertGreaterEqual(len(partial), 1)
        self.assertTrue(all(not item["default_enabled"] for item in partial))
        self.assertEqual(self.by_id["toreca_capital"]["supported_tcg_keys"], [])
        self.assertFalse(self.by_id["aonekotei"]["monitoring_supported"])

    def test_invalid_official_domain_is_rejected(self):
        payload = Path(__file__).resolve().parents[1] / "app" / "resources" / "builtin_stores.json"
        text = payload.read_text(encoding="utf-8").replace(
            '"official_url":"https://www.aoki-toy.co.jp/"',
            '"official_url":"https://evil.example/"',
            1,
        )
        with tempfile.TemporaryDirectory() as directory:
            altered = Path(directory) / "stores.json"
            altered.write_text(text, encoding="utf-8")
            with self.assertRaises(CatalogValidationError):
                load_builtin_store_catalog(altered)


class StoreCandidateFlowTest(unittest.TestCase):
    def test_unknown_is_candidate_only_with_evidence_and_unknown_tcg(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = StoreCandidateManager(Path(directory))
            saved = manager.add_candidate({
                "name": "新規カードショップ", "url": "https://new-card.example/reserve",
                "source_url": "https://source.example/list", "tcg_key": "unknown",
                "discovery_type": "reservation", "confidence": 0.81,
            })
            self.assertTrue(saved)
            item = manager.load()[0]
            self.assertEqual(item["candidate_state"], "new")
            self.assertEqual(item["tcg_key"], "unknown")
            self.assertEqual(item["review_status"], "管理者確認待ち")
            self.assertTrue(item["evidence"])
            self.assertTrue(CANDIDATE_STATES.issuperset({item["candidate_state"]}))

    def test_known_alias_dangerous_url_and_save_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = StoreCandidateManager(Path(directory))
            self.assertFalse(manager.add_candidate({"name": "C-Labo", "url": "https://www.c-labo.jp/"}))
            self.assertEqual(manager.last_result["status"], "duplicate")
            self.assertFalse(manager.add_candidate({"name": "危険", "url": "http://127.0.0.1/item"}))
            self.assertEqual(manager.last_result["status"], "rejected")
            with patch.object(manager, "_save", side_effect=OSError("disk full")):
                self.assertFalse(manager.add_candidate({"name": "保存失敗店", "url": "https://save-fail.example/"}))
            self.assertIn("保存失敗", manager.last_result["reason"])

    def test_discovery_diagnostics_never_register_site_master(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate_manager = StoreCandidateManager(root)
            discovery = StoreDiscovery(candidate_manager)
            before = len(SiteMasterManager(root).load_sites())
            result = discovery.inspect_links([
                {"text": "ヨドバシ・ドット・コム", "url": "https://www.yodobashi.com/"},
                {"text": "新しい店", "url": "https://brand-new.example/lottery"},
                {"text": "新しい店", "url": "https://brand-new.example/lottery"},
                {"text": "危険な店", "url": "http://localhost/"},
                {"text": "", "url": "https://missing.example/"},
            ], source_url="https://source.example/", product_name="新商品")
            self.assertEqual(result["existing_store_match_count"], 1)
            self.assertEqual(result["new_candidate_count"], 1)
            self.assertEqual(result["duplicate_excluded_count"], 1)
            self.assertEqual(result["url_safety_rejected_count"], 1)
            self.assertEqual(result["insufficient_evidence_count"], 1)
            self.assertEqual(len(SiteMasterManager(root).load_sites()), before)


class StoreCompatibilityAndMarketplaceTest(unittest.TestCase):
    def test_existing_settings_and_custom_name_survive_catalog_merge(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = SiteMasterManager(Path(directory))
            manager.save_sites([{
                **DEFAULT_SITES[0], "name": "ユーザー編集名", "enabled": True,
            }])
            sites = manager.load_sites()
            current = next(item for item in sites if item["id"] == DEFAULT_SITES[0]["id"])
            self.assertEqual(current["name"], "ユーザー編集名")
            self.assertTrue(current["enabled"])
            self.assertGreater(len(sites), 1)

    def test_marketplace_requires_official_seller_evidence(self):
        candidate = {"reference_price": 1000, "product_kind": "その他"}
        yahoo = {"site_key": "yahoo_shopping", "retailer_verified": True, "seller": "店"}
        self.assertFalse(RetailPricePolicy.evaluate(candidate, yahoo)["accepted"])
        yahoo["official_store_verified"] = True
        self.assertTrue(RetailPricePolicy.evaluate(candidate, yahoo)["accepted"])
        rakuten = {"site_key": "rakuten_books", "retailer_verified": True, "seller": "転売店"}
        self.assertFalse(RetailPricePolicy.evaluate(candidate, rakuten)["accepted"])


if __name__ == "__main__":
    unittest.main()
