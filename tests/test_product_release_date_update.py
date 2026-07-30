from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from core.auto_monitor_manager import AutoMonitorManager
from core.candidate_manager import CandidateManager
from core.config_manager import ConfigManager
from core.product_master import ProductMasterManager
from core.product_store import ProductStore


def product(
    *,
    product_id: str = "stable-id",
    name: str = "テストブースター BOX",
    tcg_key: str = "pokemon",
    release_date: str = "2026-08-01",
    product_kind: str = "ブースターパック",
    product_code: str = "",
    observed_at: str = "",
    site_key: str = "",
) -> dict:
    item = {
        "id": product_id,
        "name": name,
        "tcg_key": tcg_key,
        "release_date": release_date,
        "product_kind": product_kind,
        "product_code": product_code,
        "official_url": "https://example.com/products/test",
        "source_name": "メーカー公式",
        "source_type": "official_source",
        "sites": [],
    }
    if observed_at:
        item["release_date_observed_at"] = observed_at
    if site_key:
        item["sites"] = [{
            "site_key": site_key,
            "name": site_key,
            "url": f"https://example.com/{site_key}",
            "application_url": f"https://example.com/{site_key}/apply",
            "application_period": "2026-07-01 10:00 ～ 2026-07-10 23:59",
            "status": "抽選受付中",
        }]
    return item


class ProductReleaseDateUpdateTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = ProductStore(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def _raw(self) -> list[dict]:
        return self.store._load_product_file()

    def test_same_product_and_same_date_is_not_duplicated(self):
        self.assertEqual(self.store.merge_discovered_products([product()])[1], 1)
        self.assertEqual(self.store.merge_discovered_products([product()])[1], 0)
        self.assertEqual(len(self._raw()), 1)

    def test_release_date_change_updates_existing_and_preserves_id(self):
        self.store.merge_discovered_products([product()])
        changed = product(product_id="new-incoming-id", release_date="2026-08-08")
        visible, added = self.store.merge_discovered_products([changed])
        self.assertEqual(added, 0)
        self.assertEqual(len(self._raw()), 1)
        self.assertEqual(self._raw()[0]["id"], "stable-id")
        self.assertEqual(self._raw()[0]["release_date"], "2026-08-08")
        self.assertEqual(visible[0]["product_id"], "stable-id")
        self.assertTrue(self._raw()[0]["release_date_updated_at"])

    def test_release_date_history_is_written_once(self):
        self.store.merge_discovered_products([product()])
        changed = product(release_date="2026-08-08")
        self.store.merge_discovered_products([changed])
        self.store.merge_discovered_products([changed])
        history = self._raw()[0]["release_date_history"]
        visible = self.store.load_products()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["old_release_date"], "2026-08-01")
        self.assertEqual(history[0]["new_release_date"], "2026-08-08")
        self.assertEqual(visible[0]["release_date"], "2026-08-08")

    def test_legacy_naive_master_timestamp_is_treated_as_local_time(self):
        self.store.merge_discovered_products([product()])
        records = ProductMasterManager(self.root).load()
        records[0]["release_date_observed_at"] = "2026-07-20T12:00:00"
        ProductMasterManager(self.root)._save_if_changed(records)
        changed = product(
            release_date="2026-08-08",
            observed_at="2026-07-20T12:01:00+09:00",
        )
        visible, _added = self.store.merge_discovered_products([changed])
        self.assertEqual(visible[0]["release_date"], "2026-08-08")

    def test_same_name_in_different_tcg_is_not_merged(self):
        self.store.merge_discovered_products([product()])
        self.store.merge_discovered_products([
            product(product_id="other", tcg_key="onepiece")
        ])
        self.assertEqual(len(self._raw()), 2)

    def test_same_name_with_different_product_kind_is_not_merged(self):
        self.store.merge_discovered_products([product()])
        self.store.merge_discovered_products([
            product(product_id="deck", product_kind="スタートデッキ")
        ])
        self.assertEqual(len(self._raw()), 2)

    def test_same_name_with_different_brand_is_not_merged(self):
        first = product()
        first["brand"] = "メーカーA"
        second = product(product_id="brand-b")
        second["brand"] = "メーカーB"
        self.store.merge_discovered_products([first])
        self.store.merge_discovered_products([second])
        self.assertEqual(len(self._raw()), 2)

    def test_numbered_and_edition_variants_are_not_merged(self):
        pairs = (
            ("シリーズ Vol.1", "シリーズ Vol.2"),
            ("記念商品 通常版", "記念商品 限定版"),
            ("新弾 BOX", "新弾 パック"),
            ("シリーズ 第1弾", "シリーズ 第2弾"),
        )
        for left, right in pairs:
            with self.subTest(left=left, right=right):
                index, reason = ProductMasterManager.find_match(
                    [product(name=left)],
                    product(name=right, product_id="other"),
                )
                self.assertIsNone(index)
                self.assertEqual(reason, "no_match")

    def test_box_spelling_and_safe_trailing_metadata_are_normalized(self):
        existing = product(name="テスト商品 BOX")
        variants = (
            "テスト商品 ボックス",
            "テスト商品 ＢＯＸ",
            "テスト商品 BOX 税込5,500円",
            "テスト商品 BOX 発売日 2026年8月1日",
        )
        for name in variants:
            with self.subTest(name=name):
                index, reason = ProductMasterManager.find_match(
                    [existing], product(name=name, product_id="other")
                )
                self.assertEqual(index, 0)
                self.assertIn(reason, {"normalized_name", "strong_name"})

    def test_product_code_exact_match_has_priority_over_changed_name(self):
        self.store.merge_discovered_products([
            product(name="旧商品名", product_code="ABC-001")
        ])
        self.store.merge_discovered_products([
            product(
                product_id="incoming",
                name="正式名称へ変更",
                product_code="abc001",
                release_date="2026-08-08",
            )
        ])
        self.assertEqual(len(self._raw()), 1)
        self.assertEqual(self._raw()[0]["id"], "stable-id")
        self.assertEqual(self._raw()[0]["release_date"], "2026-08-08")

    def test_unknown_date_does_not_erase_existing_date(self):
        self.store.merge_discovered_products([product()])
        self.store.merge_discovered_products([product(release_date="")])
        self.assertEqual(self._raw()[0]["release_date"], "2026-08-01")

    def test_lower_priority_shop_date_does_not_replace_official_date(self):
        self.store.merge_discovered_products([product()])
        shop = product(release_date="2026-08-08")
        shop["source_name"] = "カードショップ"
        shop["source_type"] = "retail_search"
        self.store.merge_discovered_products([shop])
        self.assertEqual(self._raw()[0]["release_date"], "2026-08-01")
        self.assertEqual(
            self.store.last_merge_diagnostics["release_date_conflicts"][0]["reason"],
            "lower_priority_source",
        )

    def test_older_observation_does_not_roll_back_newer_date(self):
        self.store.merge_discovered_products([
            product(
                release_date="2026-08-08",
                observed_at="2026-07-20T12:00:00+09:00",
            )
        ])
        self.store.merge_discovered_products([
            product(
                release_date="2026-08-01",
                observed_at="2026-07-19T12:00:00+09:00",
            )
        ])
        self.assertEqual(self._raw()[0]["release_date"], "2026-08-08")
        self.assertEqual(
            self.store.last_merge_diagnostics["release_date_conflicts"][0]["reason"],
            "older_observation",
        )

    def test_historical_date_is_not_restored_by_same_priority_source(self):
        self.store.merge_discovered_products([product()])
        self.store.merge_discovered_products([product(release_date="2026-08-08")])
        self.store.merge_discovered_products([product(release_date="2026-08-01")])
        self.assertEqual(self._raw()[0]["release_date"], "2026-08-08")
        self.assertEqual(
            len(self._raw()[0]["release_date_history"]),
            1,
        )

    def test_master_is_merged_but_store_application_sites_are_retained(self):
        self.store.merge_discovered_products([product(site_key="first-sale")])
        self.store.merge_discovered_products([
            product(
                product_id="resale",
                release_date="2026-08-08",
                site_key="resale-lottery",
            )
        ])
        visible = self.store.load_products()
        self.assertEqual(len(visible), 1)
        self.assertEqual(
            {site["site_key"] for site in visible[0]["sites"]},
            {"first-sale", "resale-lottery"},
        )

    def test_legacy_product_json_remains_readable(self):
        self.store.products_path.parent.mkdir(parents=True, exist_ok=True)
        self.store.products_path.write_text(
            json.dumps([{
                "id": "legacy",
                "name": "旧形式商品",
                "tcg": "ポケモンカード",
                "release_date": "2026-08-01",
            }], ensure_ascii=False),
            encoding="utf-8",
        )
        loaded = self.store.load_products()
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["product_id"], "legacy")
        self.assertEqual(loaded[0]["sites"], [])

    def test_official_candidate_updates_existing_product_outside_monitor_window(self):
        self.store.merge_discovered_products([product()])
        manager = CandidateManager(self.root)
        changed = product(release_date="2027-08-01")
        _candidates, added = manager.merge_official_candidates(
            [changed],
            source_id="official",
            source_name="メーカー公式",
            source_url="https://example.com/",
        )
        raw = self._raw()
        self.assertEqual(added, 0)
        self.assertEqual(len(raw), 1)
        self.assertEqual(raw[0]["id"], "stable-id")
        self.assertEqual(raw[0]["release_date"], "2027-08-01")


class AutoMonitorReleaseDateUpdateTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = ProductStore(self.root)
        self.manager = AutoMonitorManager(
            ConfigManager(self.root),
            self.store,
        )
        self.today = date.today()

    def tearDown(self):
        self.temp.cleanup()

    def candidate(self, *, offset: int, name: str = "自動監視商品") -> dict:
        return {
            "name": name,
            "tcg_key": "pokemon",
            "release_date": (self.today + timedelta(days=offset)).isoformat(),
            "product_kind": "ブースターパック",
            "official_url": "https://example.com/auto",
            "source_name": "メーカー公式",
        }

    def test_auto_monitor_updates_date_without_changing_id(self):
        first = self.manager.add_due_candidates(
            [self.candidate(offset=10)], today=self.today
        )
        product_id = first["products"][0]["id"]
        second = self.manager.add_due_candidates(
            [self.candidate(offset=15)], today=self.today
        )
        raw = self.store._load_product_file()
        self.assertEqual(second["added"], 0)
        self.assertEqual(second["updated"], 1)
        self.assertEqual(len(raw), 1)
        self.assertEqual(raw[0]["id"], product_id)
        self.assertEqual(
            raw[0]["release_date"],
            (self.today + timedelta(days=15)).isoformat(),
        )

    def test_deleted_product_is_not_readded_after_date_change(self):
        first = self.manager.add_due_candidates(
            [self.candidate(offset=10)], today=self.today
        )
        self.assertTrue(
            self.store.exclude_auto_monitored_product(first["products"][0]["id"])
        )
        result = self.manager.add_due_candidates(
            [self.candidate(offset=15)], today=self.today
        )
        self.assertEqual(result["added"], 0)
        self.assertEqual(self.store._load_product_file(), [])

    def test_legacy_exclusion_key_still_prevents_readdition(self):
        candidate = self.candidate(offset=10)
        legacy_key = AutoMonitorManager.legacy_product_key(candidate)
        state = self.store._load_user_state()
        state["auto_monitor_excluded_keys"] = [legacy_key]
        self.store._save_user_state(state)
        result = self.manager.add_due_candidates(
            [self.candidate(offset=15)], today=self.today
        )
        self.assertEqual(result["added"], 0)
        self.assertEqual(self.store._load_product_file(), [])


if __name__ == "__main__":
    unittest.main()
