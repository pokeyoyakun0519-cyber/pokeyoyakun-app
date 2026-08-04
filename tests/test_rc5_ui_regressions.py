from __future__ import annotations

import sys
import tempfile
import unittest
import json
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch
from unittest.mock import Mock


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
sys.path.insert(0, str(APP_DIR))

from PySide6.QtWidgets import QApplication

from core.application_dashboard import ApplicationDashboard
from core.candidate_auto_search import CandidateAutoSearch
from core.candidate_manager import CandidateManager
from core.config_manager import ConfigManager
from core.data_pipeline_diagnostics import DataPipelineDiagnostics
from core.initial_data_bootstrap import InitialDataBootstrap
from core.product_store import ProductStore
from core.tcg_categories import categories
from ui.tcg_category_tabs import ALL_CATEGORY_KEY, TcgCategoryTabs


class Rc5UiRegressionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_product_tabs_keep_every_supported_tcg_visible_at_zero(self):
        tabs = TcgCategoryTabs()
        tabs.set_counts({
            ALL_CATEGORY_KEY: 2,
            "pokemon": 1,
            "gundam": 1,
        })

        visible_keys = {
            tabs._keys[index]
            for index in range(len(tabs._keys))
            if tabs.tab_bar.isTabVisible(index)
        }
        self.assertEqual(
            {ALL_CATEGORY_KEY, *(item.key for item in categories(enabled_only=True))},
            visible_keys,
        )
        tabs.close()

    def test_legacy_lottery_and_reservation_hits_remain_dashboard_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ProductStore(Path(directory))
            products = []
            for index, status in enumerate(("抽選情報あり", "予約情報あり")):
                products.append({
                    "id": f"p{index}",
                    "name": status,
                    "tcg_key": "onepiece",
                    "release_date": "2099-01-01",
                    "sites": [{
                        "site_key": f"s{index}",
                        "name": "店舗",
                        "url": f"https://example.com/{index}",
                        "status": status,
                    }],
                })
            products.append({
                "id": "product-only",
                "name": "通常販売商品",
                "tcg_key": "onepiece",
                "release_date": "2099-01-01",
                "sites": [{
                    "site_key": "normal",
                    "name": "通常店舗",
                    "url": "https://example.com/product",
                    "product_url": "https://example.com/product",
                    "status": "商品掲載あり",
                }],
            })
            store._save_product_file(products)

            rows = ApplicationDashboard(store=store).build(
                state_filter="すべて",
                show_ended=True,
            )["rows"]

        self.assertEqual(2, len(rows))
        self.assertEqual(
            {"抽選情報あり", "予約情報あり"},
            {row["status"] for row in rows},
        )
        self.assertTrue(all(row["application_url"] for row in rows))

    def test_dashboard_initial_state_shows_all_active_applications(self):
        from ui.application_dashboard_page import ApplicationDashboardPage

        with tempfile.TemporaryDirectory() as directory, patch.dict(
            "os.environ", {"POKEYOYA_DATA_ROOT": directory}, clear=False
        ):
            page = ApplicationDashboardPage()
            self.assertEqual(
                "すべて",
                page.state_tabs.tabData(page.state_tabs.currentIndex()),
            )
            page.close()

    def test_gmail_page_is_visible_and_routable_in_simple_mode(self):
        from ui.main_window import MainWindow

        with tempfile.TemporaryDirectory() as directory, patch.dict(
            "os.environ", {"POKEYOYA_DATA_ROOT": directory}, clear=False
        ):
            window = MainWindow()
            window._apply_ui_mode("simple")
            notification_buttons = window.menu_sections["通知"][3]

            self.assertIn(window.email_accounts_button, window.simple_mode_buttons)
            self.assertIn(window.email_accounts_button, notification_buttons)
            self.assertFalse(window.email_accounts_button.isHidden())
            window.email_accounts_button.click()
            self.assertIs(window.email_accounts_page, window.pages.currentWidget())
            window.close()

    def test_owner_simple_mode_keeps_gmail_page_visible(self):
        from ui.owner_main_window import OwnerMainWindow

        with tempfile.TemporaryDirectory() as directory, patch.dict(
            "os.environ", {"POKEYOYA_DATA_ROOT": directory}, clear=False
        ):
            window = OwnerMainWindow()
            window._apply_ui_mode("simple")
            self.assertFalse(window.email_accounts_button.isHidden())
            window.close()

    def test_monitor_completion_refreshes_product_and_application_pages(self):
        from ui.main_window import MainWindow

        with tempfile.TemporaryDirectory() as directory, patch.dict(
            "os.environ", {"POKEYOYA_DATA_ROOT": directory}, clear=False
        ):
            window = MainWindow()
            with (
                patch.object(window.product_page, "reload_saved_products") as products,
                patch.object(window.application_dashboard_page, "reload") as dashboard,
                patch.object(window.candidates_page, "reload_candidates") as candidates,
                patch.object(window.sources_page, "reload_sources") as sources,
            ):
                window.monitor_scheduler.run_completed.emit({})
            products.assert_called_once_with()
            dashboard.assert_called_once_with()
            candidates.assert_called_once_with()
            sources.assert_called_once_with()
            window.close()

    def test_empty_first_run_bootstraps_official_products_when_enabled(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = ConfigManager(root)
            values = config.load()
            values["general"]["setup_completed"] = True
            values["general"]["new_product_auto_fetch"] = True
            config.save(values)
            store = ProductStore(root)
            candidates = CandidateManager(root)
            source = Mock()

            def check_all():
                candidates.save_candidates([{
                    "id": "candidate-1",
                    "name": "公式商品",
                    "tcg_key": "onepiece",
                    "release_date": "2099-01-01",
                }])
                store._save_product_file([{
                    "id": "product-1",
                    "name": "公式商品",
                    "tcg_key": "onepiece",
                    "release_date": "2099-01-01",
                    "auto_monitored": True,
                    "sites": [],
                }])
                return ([{"id": "source-1"}], ["source-1"])

            source.check_all.side_effect = check_all
            auto_search = Mock()
            def run_due(**kwargs):
                callback = kwargs.get("progress_callback")
                if callback:
                    callback({
                        "id": "candidate-1",
                        "name": "公式商品",
                    }, 1)
                return {
                    "searched_count": 1,
                    "new_hit_candidates": [],
                }
            auto_search.run_due.side_effect = run_due
            bootstrap = InitialDataBootstrap(
                config_manager=config,
                product_store=store,
                candidate_manager=candidates,
                source_manager=source,
                candidate_auto_search=auto_search,
            )

            self.assertTrue(bootstrap.should_run())
            phases = []
            progress = []
            result = bootstrap.run(
                on_official_loaded=phases.append,
                on_retail_progress=progress.append,
            )
            self.assertEqual(1, result["product_count"])
            self.assertEqual(1, result["candidate_count"])
            self.assertEqual({"onepiece": 1}, result["per_tcg"])
            self.assertEqual(1, result["retail_searched_count"])
            self.assertEqual("official", phases[0]["phase"])
            self.assertEqual(0, phases[0]["retail_searched_count"])
            self.assertEqual("completed", result["phase"])
            self.assertEqual(1, progress[0]["searched"])
            self.assertEqual(1, progress[0]["total"])
            self.assertFalse(bootstrap.should_run())

    def test_initial_bootstrap_respects_disabled_auto_fetch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = ConfigManager(root)
            values = config.load()
            values["general"]["setup_completed"] = True
            values["general"]["new_product_auto_fetch"] = False
            config.save(values)
            source = Mock()
            auto_search = Mock()
            bootstrap = InitialDataBootstrap(
                config_manager=config,
                product_store=ProductStore(root),
                candidate_manager=CandidateManager(root),
                source_manager=source,
                candidate_auto_search=auto_search,
            )

            self.assertFalse(bootstrap.should_run())
            self.assertFalse(bootstrap.run()["started"])
            source.check_all.assert_not_called()
            auto_search.run_due.assert_not_called()

    def test_product_and_dashboard_diagnostics_explain_zero_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = ProductStore(root)
            store._save_product_file([{
                "id": "product-only",
                "name": "通常販売商品",
                "tcg_key": "gundam",
                "release_date": "2099-01-01",
                "sites": [{
                    "site_key": "shop",
                    "name": "通常店舗",
                    "url": "https://example.com/product",
                    "product_url": "https://example.com/product",
                    "status": "商品掲載あり",
                }],
            }])

            self.assertEqual(1, len(store.load_products()))
            self.assertEqual(1, store.last_load_diagnostics["raw_count"])
            self.assertEqual({"gundam": 1}, store.last_load_diagnostics["per_tcg"])

            data = ApplicationDashboard(store=store).build(
                state_filter="すべて",
                show_ended=True,
            )
            diagnostics = data["diagnostics"]
            self.assertEqual(1, diagnostics["loaded_products"])
            self.assertEqual(1, diagnostics["loaded_sites"])
            self.assertEqual(1, diagnostics["excluded_no_application_evidence"])
            self.assertEqual(0, diagnostics["displayed_rows"])

    def test_initial_retail_search_is_limited_to_promoted_candidates(self):
        search = CandidateAutoSearch()
        search.candidates = Mock()
        search.candidates.load_candidates.return_value = [
            {"id": "target", "name": "対象", "last_searched": ""},
            {"id": "unrelated", "name": "対象外", "last_searched": ""},
        ]
        search.candidates.update_search_result.side_effect = (
            lambda candidate_id, **_kwargs: {"id": candidate_id}
        )
        search.searcher = Mock()
        search.searcher.search_candidate.return_value = ([], ["確認済み"])
        progress = []

        result = search.run_due(
            candidate_ids={"target"},
            progress_callback=lambda candidate, count: progress.append(
                (candidate["id"], count)
            ),
        )

        self.assertEqual(1, result["searched_count"])
        search.searcher.search_candidate.assert_called_once_with(
            {"id": "target", "name": "対象", "last_searched": ""}
        )
        self.assertEqual([("target", 1)], progress)

    def test_tcg_pipeline_diagnostics_separates_all_data_stages(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = ConfigManager(root)
            values = config.load()
            values["general"]["auto_monitor_days_before"] = 30
            config.save(values)
            (root / "config" / "sources.json").write_text(
                json.dumps([{
                    "tcg_key": "onepiece",
                    "last_detected_count": 16,
                    "check_state": "checked",
                }]),
                encoding="utf-8",
            )
            today = date.today()
            candidates = CandidateManager(root)
            candidates.save_candidates([
                {
                    "id": "eligible",
                    "name": "応募対象",
                    "tcg_key": "onepiece",
                    "release_date": (today + timedelta(days=10)).isoformat(),
                    "official_url": "https://example.com/eligible",
                    "retail_hits": [{"site_key": "shop"}],
                },
                {
                    "id": "past",
                    "name": "発売済み",
                    "tcg_key": "onepiece",
                    "release_date": (today - timedelta(days=1)).isoformat(),
                    "official_url": "https://example.com/past",
                    "retail_hits": [],
                },
                {
                    "id": "future",
                    "name": "将来商品",
                    "tcg_key": "onepiece",
                    "release_date": (today + timedelta(days=31)).isoformat(),
                    "official_url": "https://example.com/future",
                    "retail_hits": [],
                },
            ])
            store = ProductStore(root)
            store._save_product_file([{
                "id": "saved",
                "name": "応募対象",
                "tcg_key": "onepiece",
                "release_date": (today + timedelta(days=10)).isoformat(),
                "sites": [{"site_key": "shop"}],
            }])
            visible = store.load_products()

            snapshot = DataPipelineDiagnostics(root).build(
                visible_products=visible
            )
            onepiece = snapshot["by_tcg"]["onepiece"]
            self.assertEqual(16, onepiece["official_acquired"])
            self.assertEqual(3, onepiece["candidate_saved"])
            self.assertEqual(1, onepiece["shop_acquired"])
            self.assertEqual(1, onepiece["product_saved"])
            self.assertEqual(1, onepiece["site_saved"])
            self.assertEqual(1, onepiece["product_displayed"])
            self.assertEqual(1, onepiece["promotion_eligible"])
            self.assertEqual(
                {"already_released": 1, "beyond_monitor_window": 1},
                onepiece["promotion_excluded"],
            )
            line = next(
                value
                for value in DataPipelineDiagnostics.format_lines(snapshot)
                if value.startswith("TCG pipeline onepiece:")
            )
            self.assertIn("official=16", line)
            self.assertIn("displayed=1", line)

    def test_dashboard_diagnostics_are_reported_per_tcg(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ProductStore(Path(directory))
            store._save_product_file([
                {
                    "id": "pokemon",
                    "name": "ポケモン応募",
                    "tcg_key": "pokemon",
                    "release_date": "2099-01-01",
                    "sites": [{
                        "site_key": "apply",
                        "url": "https://example.com/apply",
                        "application_url": "https://example.com/apply",
                        "status": "抽選受付中",
                    }],
                },
                {
                    "id": "gundam",
                    "name": "ガンダム商品",
                    "tcg_key": "gundam",
                    "release_date": "2099-01-01",
                    "sites": [{
                        "site_key": "product",
                        "url": "https://example.com/product",
                        "product_url": "https://example.com/product",
                    }],
                },
            ])

            data = ApplicationDashboard(store=store).build(
                state_filter="すべて",
                show_ended=True,
            )
            by_tcg = data["diagnostics_by_tcg"]
            self.assertEqual(1, by_tcg["pokemon"]["displayed_rows"])
            self.assertEqual(
                1, by_tcg["gundam"]["excluded_no_application_evidence"]
            )

    def test_official_candidate_merge_records_rejection_reasons(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = CandidateManager(Path(directory))
            release = (date.today() + timedelta(days=5)).isoformat()
            discovered = [
                {
                    "name": "ワンピース新商品",
                    "tcg_key": "onepiece",
                    "release_date": release,
                    "product_kind": "ブースターパック",
                    "official_url": "https://example.com/valid",
                },
                {
                    "name": "公式アクセサリー",
                    "tcg_key": "onepiece",
                    "release_date": release,
                    "product_kind": "アクセサリー",
                    "official_url": "https://example.com/accessory",
                },
                {
                    "name": "",
                    "tcg_key": "onepiece",
                    "release_date": release,
                },
            ]

            _items, added = manager.merge_official_candidates(
                discovered,
                source_id="source",
                source_name="公式",
                source_url="https://example.com/",
            )
            diagnostics = manager.last_merge_diagnostics
            self.assertEqual(1, added)
            self.assertEqual(3, diagnostics["detected"])
            self.assertEqual(1, diagnostics["reasons"]["added"])
            self.assertEqual(
                1, diagnostics["reasons"]["not_new_release_product"]
            )
            self.assertEqual(1, diagnostics["reasons"]["missing_name"])
            self.assertNotIn(
                "products", diagnostics.get("promotion", {})
            )


if __name__ == "__main__":
    unittest.main()
