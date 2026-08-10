import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from core.candidate_manager import CandidateManager
from core.initial_data_bootstrap import InitialDataBootstrap
from core.json_file_state import (
    CORRUPT,
    MISSING,
    PRODUCT_LIST_FIELDS,
    VALID,
    VALID_EMPTY,
    CorruptJsonError,
    JsonFileResult,
    inspect_json_file,
    restore_json_backup,
)
from core.product_store import ProductStore
from core.startup_check import StartupCheck


class JsonStateTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.path = self.root / "data" / "value.json"
        self.path.parent.mkdir(parents=True)

    def tearDown(self):
        self.temporary.cleanup()

    def inspect_list(self):
        return inspect_json_file(
            self.path, list, nullable_list_fields=PRODUCT_LIST_FIELDS
        )

    def test_missing_and_valid_empty_are_distinct(self):
        self.assertEqual(self.inspect_list().state, MISSING)
        self.path.write_text("[]", encoding="utf-8")
        result = self.inspect_list()
        self.assertEqual(result.state, VALID_EMPTY)
        self.assertEqual(result.data, [])

    def test_expected_empty_object_is_valid_empty(self):
        self.path.write_text("{}", encoding="utf-8")
        self.assertEqual(inspect_json_file(self.path, dict).state, VALID_EMPTY)

    def test_syntax_and_top_level_type_errors_are_corrupt(self):
        for content in ("{broken", "{}", "null"):
            with self.subTest(content=content):
                self.path.write_text(content, encoding="utf-8")
                self.assertEqual(self.inspect_list().state, CORRUPT)

    def test_broken_only_is_corrupt_not_missing(self):
        self.path.with_suffix(".json.broken").write_text("broken", encoding="utf-8")
        self.assertEqual(self.inspect_list().state, CORRUPT)

    def test_valid_backup_is_reported_without_changing_main(self):
        original = b"{broken"
        self.path.write_bytes(original)
        self.path.with_suffix(".json.bak").write_text("[]", encoding="utf-8")
        result = self.inspect_list()
        self.assertEqual(result.state, CORRUPT)
        self.assertTrue(result.recoverable)
        self.assertEqual(self.path.read_bytes(), original)

    def test_explicit_restore_accepts_only_valid_backup(self):
        self.path.write_text("{broken", encoding="utf-8")
        backup = self.path.with_suffix(".json.bak")
        backup.write_text("{}", encoding="utf-8")
        self.assertFalse(
            restore_json_backup(
                self.path, list, nullable_list_fields=PRODUCT_LIST_FIELDS
            )
        )
        self.assertEqual(self.path.read_text(encoding="utf-8"), "{broken")
        backup.write_text('[{"name":"restored"}]', encoding="utf-8")
        self.assertTrue(
            restore_json_backup(
                self.path, list, nullable_list_fields=PRODUCT_LIST_FIELDS
            )
        )
        self.assertEqual(self.path.read_bytes(), backup.read_bytes())


class StoreSafetyTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "data").mkdir(parents=True)
        self.products = self.root / "data" / "products.json"
        self.candidates = self.root / "data" / "candidates.json"

    def tearDown(self):
        self.temporary.cleanup()

    def test_corrupt_product_and_candidate_saves_are_rejected(self):
        self.products.write_text("{broken", encoding="utf-8")
        self.candidates.write_text("{broken", encoding="utf-8")
        with self.assertRaises(CorruptJsonError):
            ProductStore(self.root)._save_product_file([])
        with self.assertRaises(CorruptJsonError):
            CandidateManager(self.root).save_candidates([])
        self.assertEqual(self.products.read_text(encoding="utf-8"), "{broken")
        self.assertEqual(self.candidates.read_text(encoding="utf-8"), "{broken")

    def test_corrupt_main_never_overwrites_valid_backup(self):
        self.products.write_text("{broken", encoding="utf-8")
        backup = self.products.with_suffix(".json.bak")
        backup.write_text('[{"id":"safe"}]', encoding="utf-8")
        before = backup.read_bytes()
        with self.assertRaises(CorruptJsonError):
            ProductStore(self.root)._save_product_file([])
        self.assertEqual(backup.read_bytes(), before)

    def test_restore_does_not_immediately_replace_backup_data(self):
        self.products.write_text("{broken", encoding="utf-8")
        backup = self.products.with_suffix(".json.bak")
        backup.write_text('[{"id":"safe"}]', encoding="utf-8")
        store = ProductStore(self.root)
        self.assertTrue(store.restore_products_backup())
        self.assertEqual(self.products.read_bytes(), backup.read_bytes())

    def test_legacy_null_list_fields_are_normalized_in_memory_only(self):
        original = json.dumps(
            [{
                "name": "legacy",
                "aliases": None,
                "source_urls": None,
                "release_date_history": None,
                "sites": None,
            }],
            ensure_ascii=False,
        )
        self.products.write_text(original, encoding="utf-8")
        store = ProductStore(self.root)
        result = store.inspect_product_file()
        self.assertEqual(result.state, VALID)
        for field in ("aliases", "source_urls", "release_date_history", "sites"):
            self.assertEqual(result.data[0][field], [])
        loaded = store.load_products()
        self.assertEqual(loaded[0]["sites"], [])
        self.assertEqual(self.products.read_text(encoding="utf-8"), original)

    def test_list_values_are_preserved(self):
        value = [{"aliases": ["a"], "sites": [{"name": "s"}]}]
        self.products.write_text(json.dumps(value), encoding="utf-8")
        self.assertEqual(ProductStore(self.root).inspect_product_file().data, value)

    def test_candidate_legacy_list_fields_are_normalized(self):
        self.candidates.write_text(
            json.dumps([{"candidate_reasons": None, "retail_hits": None}]),
            encoding="utf-8",
        )
        candidate = CandidateManager(self.root).load_candidates()[0]
        self.assertEqual(candidate["candidate_reasons"], [])
        self.assertEqual(candidate["retail_hits"], [])

    def test_wrong_nullable_list_field_types_are_not_coerced(self):
        for value in ("x", 1, {"x": 1}):
            with self.subTest(value=value):
                self.products.write_text(
                    json.dumps([{"aliases": value}]), encoding="utf-8"
                )
                result = ProductStore(self.root).inspect_product_file()
                self.assertEqual(result.state, CORRUPT)
                self.assertIsNone(result.data)


class BootstrapAndStartupTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "data").mkdir(parents=True)
        self.config = Mock()
        self.config.load.return_value = {
            "general": {"setup_completed": True, "new_product_auto_fetch": True}
        }

    def tearDown(self):
        self.temporary.cleanup()

    def bootstrap(self):
        return InitialDataBootstrap(
            config_manager=self.config,
            product_store=ProductStore(self.root),
            candidate_manager=CandidateManager(self.root),
            source_manager=Mock(),
            candidate_auto_search=Mock(),
        )

    def test_corrupt_products_or_candidates_block_initial_fetch(self):
        for filename in ("products.json", "candidates.json"):
            with self.subTest(filename=filename):
                for path in (self.root / "data").glob("*.json"):
                    path.unlink()
                (self.root / "data" / filename).write_text(
                    "{broken", encoding="utf-8"
                )
                bootstrap = self.bootstrap()
                self.assertFalse(bootstrap.should_run())
                result = bootstrap.run()
                self.assertEqual(result["reason"], "corrupt_json")
                bootstrap.source_manager.check_all.assert_not_called()

    def test_valid_empty_files_allow_initial_fetch(self):
        for filename in ("products.json", "candidates.json"):
            (self.root / "data" / filename).write_text("[]", encoding="utf-8")
        self.assertTrue(self.bootstrap().should_run())

    def test_corrupt_json_blocks_monitor_worker_start(self):
        from PySide6.QtCore import QCoreApplication
        from core.monitor_scheduler import MonitorScheduler

        application = QCoreApplication.instance() or QCoreApplication([])
        scheduler = MonitorScheduler()
        scheduler.timer.stop()
        scheduler.log_manager = Mock()
        corrupt = JsonFileResult(
            self.root / "data" / "products.json", CORRUPT, error="broken"
        )
        healthy = JsonFileResult(
            self.root / "data" / "candidates.json", VALID_EMPTY, data=[]
        )
        product_store = Mock()
        product_store.inspect_product_file.return_value = corrupt
        candidate_manager = Mock()
        candidate_manager.inspect_candidates_file.return_value = healthy
        product_master = Mock()
        product_master.inspect_file.return_value = healthy
        source_manager = Mock()
        source_manager.inspect_sources_file.return_value = healthy
        statuses = []
        scheduler.status_changed.connect(statuses.append)
        with (
            patch("core.monitor_scheduler.ProductStore", return_value=product_store),
            patch("core.monitor_scheduler.CandidateManager", return_value=candidate_manager),
            patch("core.monitor_scheduler.ProductMasterManager", return_value=product_master),
            patch("core.monitor_scheduler.SourceManager", return_value=source_manager),
        ):
            scheduler._start_run({"check_sources": True})
        self.assertFalse(scheduler.running)
        self.assertIsNone(scheduler.thread)
        self.assertIn("自動監視：破損JSONの復元待ち", statuses)
        scheduler.shutdown()
        self.assertIsNotNone(application)

    @patch("core.startup_check.UserDataMigration.run", return_value=[])
    def test_startup_check_reports_without_moving_or_rewriting_corrupt_file(self, _run):
        products = self.root / "data" / "products.json"
        products.write_text("{broken", encoding="utf-8")
        checker = StartupCheck(self.root)
        messages = checker.run()
        self.assertTrue(any("data/products.jsonが破損" in item for item in messages))
        self.assertEqual(products.read_text(encoding="utf-8"), "{broken")
        self.assertFalse(products.with_suffix(".json.broken").exists())
        self.assertTrue(any(item.path == products for item in checker.json_issues))


if __name__ == "__main__":
    unittest.main()
