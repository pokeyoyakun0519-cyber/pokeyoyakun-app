import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "app"))

from core.favorites_manager import FavoritesManager
from core.json_file_state import (
    CORRUPT,
    MISSING,
    VALID,
    VALID_EMPTY,
    CorruptJsonError,
)
from core.product_master import ProductMasterManager
from core.product_store import ProductStore
from core.startup_check import StartupCheck


def product(identifier="4901234567890", **updates):
    value = {
        "id": updates.pop("id", "same-id"),
        "name": updates.pop("name", "同一商品"),
        "tcg_key": updates.pop("tcg_key", "pokemon"),
        "product_kind": updates.pop("product_kind", "BOX"),
        "brand": updates.pop("brand", "ブランドA"),
        "jan": identifier,
        "sites": updates.pop("sites", []),
    }
    value.update(updates)
    return value


class B3ProductIdSeparationTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = ProductStore(self.root)

    def tearDown(self):
        self.temporary.cleanup()

    def _save_conflict(self):
        self.store.merge_discovered_products([product("4901234567890")])
        return self.store.merge_discovered_products([product("4901234567891")])[0]

    def test_conflict_remains_two_after_save_load_and_master_sync(self):
        loaded = self._save_conflict()
        saved = json.loads(self.store.products_path.read_text(encoding="utf-8"))
        self.assertEqual(2, len(saved))
        self.assertEqual(2, len({item["id"] for item in saved}))
        self.assertEqual(2, len(loaded))
        restarted = ProductStore(self.root).load_products()
        self.assertEqual(2, len(restarted))
        synchronized = ProductMasterManager(self.root).synchronize(restarted)
        self.assertEqual(2, len(synchronized))
        self.assertEqual(2, len({item["id"] for item in synchronized}))

    def test_same_item_reacquisition_uses_same_product_id(self):
        first = self._save_conflict()
        ids_before = {item["jan"]: item["id"] for item in first}
        after, added = self.store.merge_discovered_products([
            product("4901234567891", name="同一商品 微差")
        ])
        self.assertEqual(0, added)
        self.assertEqual(2, len(after))
        self.assertEqual(ids_before["4901234567891"], {
            item["jan"]: item["id"] for item in after
        }["4901234567891"])

    def test_each_external_identifier_changes_deterministic_id(self):
        cases = (
            ("jan", "4901234567890", "4901234567891"),
            ("product_code", "CODE-1", "CODE-2"),
            ("official_product_id", "OFFICIAL-1", "OFFICIAL-2"),
        )
        for field, left, right in cases:
            with self.subTest(field=field):
                first = product("")
                second = product("")
                first[field] = left
                second[field] = right
                repaired, warnings = ProductMasterManager.split_conflicting_product_ids(
                    [first, second]
                )
                self.assertEqual(1, len(warnings))
                self.assertNotEqual(repaired[0]["id"], repaired[1]["id"])

    def test_old_duplicate_ids_keep_sites_and_application_state_separate(self):
        products = [
            product("4901234567890", sites=[{
                "site_key": "shop-a", "url": "https://a.example/apply"
            }]),
            product("4901234567891", sites=[{
                "site_key": "shop-b", "url": "https://b.example/apply"
            }]),
        ]
        self.store.products_path.parent.mkdir(parents=True)
        self.store.products_path.write_text(
            json.dumps(products, ensure_ascii=False), encoding="utf-8"
        )
        self.store.user_state_path.parent.mkdir(parents=True)
        self.store.user_state_path.write_text(json.dumps({
            "reserved_product_ids": ["same-id"],
            "site_applications": {
                "same-id|shop-b|https://b.example/apply": {
                    "applied": True, "result_status": "当選"
                }
            },
            "auto_monitor_excluded_keys": [],
        }, ensure_ascii=False), encoding="utf-8")
        FavoritesManager(self.root).set_favorite("product", "same-id", True)

        loaded = self.store.load_products()
        by_jan = {item["jan"]: item for item in loaded}
        self.assertEqual(2, len(loaded))
        self.assertEqual(
            {"shop-a"}, {site["site_key"] for site in by_jan["4901234567890"]["sites"]}
        )
        self.assertEqual(
            {"shop-b"}, {site["site_key"] for site in by_jan["4901234567891"]["sites"]}
        )
        self.assertFalse(by_jan["4901234567890"]["sites"][0].get("applied", False))
        self.assertTrue(by_jan["4901234567891"]["sites"][0]["applied"])
        self.assertEqual("当選", by_jan["4901234567891"]["sites"][0]["result_status"])
        self.assertTrue(by_jan["4901234567890"]["reserved"])
        self.assertFalse(by_jan["4901234567891"]["reserved"])
        self.assertTrue(FavoritesManager(self.root).is_favorite("product", "same-id"))

    def test_split_product_can_be_deleted_without_deleting_the_other(self):
        products = [
            product("4901234567890", auto_monitored=True),
            product("4901234567891", auto_monitored=True),
        ]
        self.store.products_path.parent.mkdir(parents=True)
        self.store.products_path.write_text(json.dumps(products), encoding="utf-8")
        self.store.user_state_path.parent.mkdir(parents=True)
        self.store.user_state_path.write_text("{}", encoding="utf-8")
        loaded = self.store.load_products()
        second_id = next(item["id"] for item in loaded if item["jan"].endswith("1"))
        self.assertTrue(self.store.exclude_auto_monitored_product(second_id))
        remaining = self.store.load_products()
        self.assertEqual(["4901234567890"], [item["jan"] for item in remaining])

    def test_kind_tcg_and_brand_separation_is_unchanged(self):
        cases = (
            (product(product_kind="BOX"), product(product_kind="パック")),
            (product(tcg_key="pokemon"), product(tcg_key="onepiece")),
            (product(brand="ブランドA"), product(brand="ブランドB")),
        )
        for left, right in cases:
            with self.subTest(left=left, right=right):
                self.assertEqual(
                    (None, "no_match"),
                    ProductMasterManager.find_match([left], right),
                )

    def test_same_internal_id_cannot_remerge_kind_tcg_or_brand_conflicts(self):
        cases = (
            (product(product_kind="BOX"), product(product_kind="パック")),
            (product(tcg_key="pokemon"), product(tcg_key="onepiece")),
            (product(brand="ブランドA"), product(brand="ブランドB")),
        )
        for left, right in cases:
            with self.subTest(left=left, right=right):
                repaired, warnings = ProductMasterManager.split_conflicting_product_ids(
                    [left, right]
                )
                self.assertEqual(1, len(warnings))
                self.assertEqual(2, len({item["id"] for item in repaired}))


class UserStateCorruptionProtectionTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = ProductStore(self.root)

    def tearDown(self):
        self.temporary.cleanup()

    def _write(self, text):
        self.store.user_state_path.parent.mkdir(parents=True, exist_ok=True)
        self.store.user_state_path.write_text(text, encoding="utf-8")

    def test_missing_empty_valid_and_corrupt_states(self):
        self.assertEqual(MISSING, self.store.inspect_user_state_file().state)
        self._write("{}")
        self.assertEqual(VALID_EMPTY, self.store.inspect_user_state_file().state)
        self._write('{"reserved_product_ids":["p1"]}')
        self.assertEqual(VALID, self.store.inspect_user_state_file().state)
        for text in ("{broken", "[]"):
            with self.subTest(text=text):
                self._write(text)
                self.assertEqual(CORRUPT, self.store.inspect_user_state_file().state)

    def test_corrupt_state_rejects_all_normal_product_state_saves(self):
        self._write("{broken")
        calls = (
            lambda: self.store.save_reserved_state("p1", True),
            lambda: self.store.save_site_application_state("p1", "shop", "url", True),
            lambda: self.store.save_site_result("p1", "shop", "url", "当選"),
            self.store.reset_reserved_state,
        )
        for call in calls:
            with self.subTest(call=call), self.assertRaises(CorruptJsonError):
                call()
            self.assertEqual("{broken", self.store.user_state_path.read_text(encoding="utf-8"))

    def test_corrupt_state_rejects_auto_monitor_exclusion_save(self):
        self.store.products_path.parent.mkdir(parents=True)
        self.store.products_path.write_text(json.dumps([
            product(auto_monitored=True)
        ]), encoding="utf-8")
        self._write("{broken")
        before = self.store.products_path.read_bytes()
        with self.assertRaises(CorruptJsonError):
            self.store.exclude_auto_monitored_product("same-id")
        self.assertEqual(before, self.store.products_path.read_bytes())
        self.assertEqual("{broken", self.store.user_state_path.read_text(encoding="utf-8"))

    def test_missing_state_can_be_created_by_explicit_user_save(self):
        self.store.save_reserved_state("p1", True)
        self.assertEqual(["p1"], self.store._load_user_state()["reserved_product_ids"])

    def test_valid_empty_state_keeps_normal_save_behavior(self):
        self._write("{}")
        self.store.save_site_application_state("p1", "shop", "url", True)
        state = self.store._load_user_state()
        self.assertTrue(state["site_applications"]["p1|shop|url"]["applied"])

    def test_corruption_warning_contains_file_and_recovery_status(self):
        self._write("{broken")
        backup = self.store.user_state_path.with_suffix(".json.bak")
        backup.write_text("{}", encoding="utf-8")
        result = self.store.inspect_user_state_file()
        self.assertEqual(self.store.user_state_path, result.path)
        self.assertEqual(CORRUPT, result.state)
        self.assertTrue(result.recoverable)

    @patch("core.startup_check.UserDataMigration.run", return_value=[])
    def test_startup_warning_does_not_rewrite_corrupt_user_state(self, _run):
        self._write("{broken")
        messages = StartupCheck(self.root).run()
        self.assertTrue(any("config/user_state.jsonが破損" in value for value in messages))
        self.assertEqual("{broken", self.store.user_state_path.read_text(encoding="utf-8"))

    def test_corrupt_state_does_not_overwrite_existing_backup(self):
        self._write("{broken")
        backup = self.store.user_state_path.with_suffix(".json.bak")
        backup.write_text('{"reserved_product_ids":["kept"]}', encoding="utf-8")
        before = backup.read_bytes()
        with self.assertRaises(CorruptJsonError):
            self.store.save_reserved_state("new", True)
        self.assertEqual(before, backup.read_bytes())
        self.assertEqual("{broken", self.store.user_state_path.read_text(encoding="utf-8"))

    def test_read_does_not_restore_valid_backup_but_explicit_restore_does(self):
        self._write("{broken")
        backup = self.store.user_state_path.with_suffix(".json.bak")
        backup.write_text('{"reserved_product_ids":["kept"]}', encoding="utf-8")
        result = self.store.inspect_user_state_file()
        self.assertTrue(result.recoverable)
        self.assertEqual("{broken", self.store.user_state_path.read_text(encoding="utf-8"))
        self.assertTrue(self.store.restore_user_state_backup())
        self.assertEqual(["kept"], self.store._load_user_state()["reserved_product_ids"])

    def test_invalid_backup_is_not_restored(self):
        self._write("{broken")
        backup = self.store.user_state_path.with_suffix(".json.bak")
        backup.write_text('{"reserved_product_ids":{}}', encoding="utf-8")
        self.assertFalse(self.store.restore_user_state_backup())
        self.assertEqual("{broken", self.store.user_state_path.read_text(encoding="utf-8"))

    def test_known_null_lists_are_normalized_only_in_memory(self):
        original = '{"reserved_product_ids":null,"auto_monitor_excluded_keys":null,"site_applications":{}}'
        self._write(original)
        state = self.store._load_user_state()
        self.assertEqual([], state["reserved_product_ids"])
        self.assertEqual([], state["auto_monitor_excluded_keys"])
        self.assertEqual(original, self.store.user_state_path.read_text(encoding="utf-8"))

    def test_invalid_known_field_types_are_corrupt(self):
        invalid = (
            '{"reserved_product_ids":"p1"}',
            '{"reserved_product_ids":1}',
            '{"reserved_product_ids":{}}',
            '{"site_applications":null}',
        )
        for text in invalid:
            with self.subTest(text=text):
                self._write(text)
                self.assertEqual(CORRUPT, self.store.inspect_user_state_file().state)

    def test_corrupt_state_does_not_prevent_product_display(self):
        self.store.products_path.parent.mkdir(parents=True)
        self.store.products_path.write_text(
            json.dumps([product()]), encoding="utf-8"
        )
        self._write("{broken")
        loaded = self.store.load_products()
        self.assertEqual(1, len(loaded))
        self.assertEqual(CORRUPT, self.store.last_user_state_file_result.state)
        self.assertEqual("{broken", self.store.user_state_path.read_text(encoding="utf-8"))

    def test_favorite_save_does_not_touch_corrupt_user_state(self):
        self._write("{broken")
        FavoritesManager(self.root).set_favorite("product", "p1", True)
        self.assertTrue(FavoritesManager(self.root).is_favorite("product", "p1"))
        self.assertEqual("{broken", self.store.user_state_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
