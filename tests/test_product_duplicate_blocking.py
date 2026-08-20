import hashlib
import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

from core.auto_monitor_manager import AutoMonitorManager
from core.candidate_manager import CandidateManager
from core.json_file_state import CorruptJsonError
from core.product_master import ProductMasterManager
from core.product_store import DuplicateProductIdError, ProductStore


TODAY = date(2026, 8, 11)


class _Config:
    def load(self):
        return {
            "general": {
                "auto_monitor_new_releases": True,
                "auto_monitor_days_before": 60,
            },
            "games": {"pokemon": True, "onepiece": True},
        }


def candidate(
    name="拡張パック「30th CELEBRATION」",
    *,
    official_id="m6a",
    official_url="https://www.30th.pokemon-card.com/product/m6a",
    kind="拡張パック",
    release_date="2026-09-16",
):
    return {
        "id": f"pokemon_official_{official_id}",
        "tcg_key": "pokemon",
        "tcg": "ポケモンカード",
        "name": name,
        "release_date": release_date,
        "product_kind": kind,
        "official_product_id": official_id,
        "official_url": official_url,
        "source_name": "ポケモンカード公式",
        "source_type": "official_source",
    }


class ProductDuplicateBlockingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "data").mkdir()
        (self.root / "config").mkdir()
        (self.root / "config" / "user_state.json").write_text(
            "{}", encoding="utf-8"
        )
        self.store = ProductStore(self.root)
        self.monitor = AutoMonitorManager(_Config(), self.store)

    def tearDown(self):
        self.temporary.cleanup()

    def _raw_products(self):
        return json.loads(self.store.products_path.read_text(encoding="utf-8"))

    def _run_monitor(self, values, count=1):
        results = []
        for _ in range(count):
            results.append(self.monitor.add_due_candidates(values, today=TODAY))
        return results

    def test_same_product_twice_stays_one(self):
        self._run_monitor([candidate()], 2)
        self.assertEqual(1, len(self._raw_products()))

    def test_same_product_ten_times_stays_one(self):
        results = self._run_monitor([candidate()], 10)
        self.assertEqual(1, len(self._raw_products()))
        self.assertEqual([1] * 9, [item["duplicate_suppressed"] for item in results[1:]])

    def test_same_product_one_hundred_times_stays_one(self):
        self._run_monitor([candidate()], 100)
        self.assertEqual(1, len(self._raw_products()))

    def test_same_id_updates_metadata_without_append(self):
        first = candidate()
        self._run_monitor([first])
        updated = dict(first, image_url="https://example.com/new.jpg", msrp=360)
        self._run_monitor([updated])
        products = self._raw_products()
        self.assertEqual(1, len(products))
        self.assertEqual("https://example.com/new.jpg", products[0]["image_url"])
        self.assertEqual(360, products[0]["msrp"])

    def test_same_page_distinct_official_ids_stay_separate(self):
        values = [
            candidate("30周年カードセット A", official_id="cardset-a", official_url="https://example.com/cardset", kind="カードセット"),
            candidate("30周年カードセット B", official_id="cardset-b", official_url="https://example.com/cardset", kind="カードセット"),
        ]
        self.store.merge_discovered_products(values)
        self.store.merge_discovered_products(values)
        self.assertEqual(2, len(self._raw_products()))

    def test_same_name_distinct_identifier_stays_separate(self):
        self.store.merge_discovered_products([candidate(official_id="m6a-a")])
        self.store.merge_discovered_products([candidate(official_id="m6a-b")])
        products = self._raw_products()
        self.assertEqual(2, len(products))
        self.assertEqual(2, len({item["id"] for item in products}))

    def test_existing_identifier_conflict_split_is_preserved(self):
        rows = [
            dict(candidate(official_id="one"), id="same-id"),
            dict(candidate(official_id="two"), id="same-id"),
        ]
        self.store._save_product_file(rows)
        products = self._raw_products()
        self.assertEqual(2, len(products))
        self.assertEqual(2, len({item["id"] for item in products}))

    def test_json_reload_and_resync_do_not_grow(self):
        self._run_monitor([candidate()])
        for _ in range(5):
            ProductStore(self.root).load_products()
            AutoMonitorManager(_Config(), ProductStore(self.root)).add_due_candidates(
                [candidate()], today=TODAY
            )
        self.assertEqual(1, len(self._raw_products()))

    def test_restart_equivalent_manager_does_not_grow(self):
        for _ in range(5):
            AutoMonitorManager(_Config(), ProductStore(self.root)).add_due_candidates(
                [candidate()], today=TODAY
            )
        self.assertEqual(1, len(self._raw_products()))

    def test_atomic_save_keeps_backup_and_removes_tmp(self):
        self._run_monitor([candidate()])
        original = self.store.products_path.read_text(encoding="utf-8")
        self._run_monitor([dict(candidate(), image_url="https://example.com/image.jpg")])
        backup = self.store.products_path.with_suffix(".json.bak")
        self.assertEqual(original, backup.read_text(encoding="utf-8"))
        self.assertFalse(self.store.products_path.with_suffix(".json.tmp").exists())

    def test_corrupt_json_protection_is_preserved(self):
        self.store.products_path.write_text("{broken", encoding="utf-8")
        with self.assertRaises(CorruptJsonError):
            self.store._save_product_file([candidate()])
        self.assertEqual("{broken", self.store.products_path.read_text(encoding="utf-8"))

    def test_safe_duplicate_ids_are_consolidated_before_save(self):
        rows = [
            dict(candidate(), id="same", favorite=True, sites=[
                {"site_key": "a", "url": "https://a.example", "application_state": "応募済み"}
            ]),
            dict(candidate(), id="same", reserved=True, sites=[
                {"site_key": "a", "url": "https://a.example", "result_status": "当選"},
                {"site_key": "b", "url": "https://b.example"},
            ]),
        ]
        self.store._save_product_file(rows)
        products = self._raw_products()
        self.assertEqual(1, len(products))
        self.assertTrue(products[0]["favorite"])
        self.assertTrue(products[0]["reserved"])
        self.assertEqual(2, len(products[0]["sites"]))
        self.assertEqual("応募済み", products[0]["sites"][0]["application_state"])
        self.assertEqual("当選", products[0]["sites"][0]["result_status"])

    def test_unsafe_duplicate_ids_abort_before_backup(self):
        rows = [
            dict(candidate("商品A", official_id=""), id="same", official_url=""),
            dict(candidate("商品B", official_id=""), id="same", official_url=""),
        ]
        text = json.dumps(rows, ensure_ascii=False)
        self.store.products_path.write_text(text, encoding="utf-8")
        backup = self.store.products_path.with_suffix(".json.bak")
        backup.write_text("kept", encoding="utf-8")
        with self.assertRaises(DuplicateProductIdError):
            self.store._save_product_file(rows)
        self.assertEqual(text, self.store.products_path.read_text(encoding="utf-8"))
        self.assertEqual("kept", backup.read_text(encoding="utf-8"))

    def test_same_page_different_names_are_not_repair_merged(self):
        rows = [
            dict(candidate("同一ページ商品A", official_id=""), id="same"),
            dict(candidate("同一ページ商品B", official_id=""), id="same"),
        ]
        with self.assertRaises(DuplicateProductIdError):
            self.store._save_product_file(rows)

    def test_repair_dry_run_has_no_side_effect(self):
        rows = [dict(candidate(), id="same"), dict(candidate(), id="same")]
        original = json.dumps(rows, ensure_ascii=False)
        self.store.products_path.write_text(original, encoding="utf-8")
        report = self.store.repair_duplicate_product_ids(dry_run=True)
        self.assertEqual(1, report["duplicate_record_count"])
        self.assertFalse(report["saved"])
        self.assertEqual(original, self.store.products_path.read_text(encoding="utf-8"))
        self.assertFalse(self.store.products_path.with_suffix(".json.bak").exists())

    def test_explicit_repair_backs_up_and_preserves_information(self):
        rows = [
            dict(candidate(), id="same", favorite=True, aliases=["A"]),
            dict(candidate(), id="same", reserved=True, aliases=["B"]),
        ]
        original = json.dumps(rows, ensure_ascii=False)
        self.store.products_path.write_text(original, encoding="utf-8")
        report = self.store.repair_duplicate_product_ids(dry_run=False)
        self.assertTrue(report["saved"])
        self.assertEqual(original, Path(report["backup_path"]).read_text(encoding="utf-8"))
        repaired = self._raw_products()
        self.assertEqual(1, len(repaired))
        self.assertEqual(["A", "B"], repaired[0]["aliases"])
        self.assertTrue(repaired[0]["favorite"])
        self.assertTrue(repaired[0]["reserved"])

    def test_priority_pokemon_products_remain_distinct_and_idempotent(self):
        values = [
            candidate("拡張パック「30th CELEBRATION」", official_id="m6a", official_url="https://www.30th.pokemon-card.com/product/m6a"),
            candidate("30th CELEBRATION プレミアムデッキセット エーフィ・ブラッキー", official_id="mf", official_url="https://www.30th.pokemon-card.com/product/mf", kind="プレミアムデッキセット"),
            candidate("30周年カードセット", official_id="cardset", official_url="https://www.30th.pokemon-card.com/product/cardset", kind="カードセット"),
            candidate("FUTURISTIC BOX", official_id="furbox", official_url="https://www.30th.pokemon-card.com/product/furbox", kind="カード入り商品"),
            candidate("拡張パック「アビスアイ」", official_id="m5", official_url="https://www.pokemon-card.com/ex/m5/", release_date="2026-08-20"),
        ]
        for _ in range(10):
            self.store.merge_discovered_products(values)
        products = self._raw_products()
        self.assertEqual(5, len(products))
        self.assertEqual(5, len({item["id"] for item in products}))

    def test_candidate_merge_preserves_identifier_and_is_idempotent(self):
        manager = CandidateManager(self.root)
        value = candidate()
        for _ in range(3):
            manager.merge_official_candidates(
                [value], source_id="pokemon", source_name="公式",
                source_url="https://www.pokemon-card.com/",
            )
        candidates = manager.load_candidates()
        self.assertEqual(1, len(candidates))
        self.assertEqual("m6a", candidates[0]["official_product_id"])

    def test_candidate_same_name_distinct_identifiers_stay_separate(self):
        manager = CandidateManager(self.root)
        values = [
            candidate("同名限定セット", official_id="set-a", official_url="https://example.com/shared"),
            candidate("同名限定セット", official_id="set-b", official_url="https://example.com/shared"),
        ]
        manager.merge_official_candidates(
            values,
            source_id="pokemon",
            source_name="公式",
            source_url="https://example.com/",
        )
        candidates = manager.load_candidates()
        self.assertEqual(2, len(candidates))
        self.assertEqual(
            {"set-a", "set-b"},
            {item["official_product_id"] for item in candidates},
        )

    def test_legacy_candidate_without_identifier_is_enriched_not_duplicated(self):
        manager = CandidateManager(self.root)
        value = candidate()
        digest = hashlib.sha256(
            (
                "pokemon|拡張パック「30th CELEBRATION」|"
                "2026-09-16|https://www.30th.pokemon-card.com/product/m6a"
            ).encode("utf-8")
        ).hexdigest()[:20]
        legacy = dict(value)
        legacy["id"] = f"official_{digest}"
        legacy["official_product_id"] = ""
        manager.save_candidates([legacy])

        manager.merge_official_candidates(
            [value],
            source_id="pokemon",
            source_name="公式",
            source_url="https://www.pokemon-card.com/",
        )

        candidates = manager.load_candidates()
        self.assertEqual(1, len(candidates))
        self.assertEqual("m6a", candidates[0]["official_product_id"])

    def test_retail_update_merges_into_existing_official_product(self):
        self._run_monitor([candidate()])
        manager = CandidateManager(self.root)
        retail_candidate = {
            **candidate(),
            "id": "official-candidate",
            "retail_hits": [{
                "site_key": "shop", "name": "店舗", "url": "https://shop.example/item",
                "status": "予約受付中",
            }],
        }
        manager._upsert_product_from_candidate(retail_candidate)
        products = self._raw_products()
        self.assertEqual(1, len(products))
        self.assertEqual(1, len(products[0]["sites"]))

    def test_concurrent_product_master_sync_is_serialized(self):
        barrier = threading.Barrier(8)

        def synchronize(index):
            barrier.wait()
            ProductMasterManager(self.root).synchronize([{
                "id": f"parallel-{index}",
                "tcg_key": "pokemon",
                "name": f"並行商品{index}",
                "product_kind": "拡張パック",
                "official_product_id": f"official-{index}",
            }])

        with ThreadPoolExecutor(max_workers=8) as executor:
            list(executor.map(synchronize, range(8)))

        records = ProductMasterManager(self.root).load()
        self.assertEqual(8, len(records))
        self.assertEqual(8, len({item["product_id"] for item in records}))


if __name__ == "__main__":
    unittest.main()
