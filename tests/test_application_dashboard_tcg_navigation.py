from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QLabel

from core.application_dashboard import ApplicationDashboard
from core.application_status import JST
from core.config_manager import ConfigManager
from core.product_store import ProductStore
from core.tcg_categories import categories, normalize_key
from ui.application_dashboard_page import ApplicationDashboardPage, ApplicationRow


NOW = datetime(2026, 8, 22, 12, tzinfo=JST)


def application_site(key: str, *, mode: str, ended: bool = False) -> dict:
    return {
        "site_key": key,
        "name": f"{key}公式店",
        "url": f"https://example.com/{key}",
        "application_url": f"https://example.com/{key}/apply",
        "status": "抽選受付中",
        "application_end_at": (
            NOW - timedelta(days=2) if ended else NOW + timedelta(days=2)
        ).isoformat(),
        "sales_mode": mode,
        "verification_status": "confirmed",
    }


def four_tcg_products() -> list[dict]:
    return [
        {
            "id": "pokemon-product", "name": "ポケモン商品", "tcg_key": "pokemon",
            "sites": [application_site("pokemon", mode="ONLINE")],
        },
        {
            "id": "onepiece-product", "name": "ONE PIECE商品", "tcg_key": "onepiece",
            "sites": [
                application_site("onepiece", mode="STORE"),
                application_site("onepiece-ended", mode="STORE", ended=True),
            ],
        },
        {
            "id": "union-product", "name": "UNION ARENA商品", "tcg_key": "union_arena",
            "sites": [application_site("union-arena", mode="HYBRID")],
        },
        {
            "id": "dragon-ball-product", "name": "DBFW商品",
            "tcg_key": "dragon_ball_fusion_world",
            "sites": [application_site("dragon-ball", mode="UNKNOWN")],
        },
    ]


class ApplicationDashboardTcgTabsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        ProductStore(self.root)._save_product_file(four_tcg_products())
        self.environment = patch.dict(
            os.environ, {"POKEYOYA_DATA_ROOT": str(self.root)}, clear=False
        )
        self.environment.start()
        self.page = ApplicationDashboardPage()
        self.page.period_timer.stop()
        self.page._snapshot = ApplicationDashboard(
            ProductStore(self.root), ConfigManager(self.root)
        ).build(now=NOW, show_ended=True)
        self.page._apply_filters()

    def tearDown(self):
        self.page.close()
        self.environment.stop()
        self.temp.cleanup()

    def _select_tcg(self, key: str) -> None:
        index = next(
            index for index in range(self.page.tcg_tabs.tab_bar.count())
            if self.page.tcg_tabs.tab_bar.tabData(index) == key
        )
        self.page.tcg_tabs.tab_bar.setCurrentIndex(index)
        self.app.processEvents()

    def _displayed_site_keys(self) -> set[str]:
        return {
            card.row["site_key"]
            for card in self.page.scroll.widget().findChildren(ApplicationRow)
        }

    def test_tabs_are_generated_from_enabled_categories_with_all_first(self):
        keys = [
            self.page.tcg_tabs.tab_bar.tabData(index)
            for index in range(self.page.tcg_tabs.tab_bar.count())
        ]
        self.assertEqual("all", keys[0])
        self.assertEqual(
            ["all"] + [item.key for item in categories(enabled_only=True)], keys
        )
        for key in (
            "pokemon", "onepiece", "union_arena", "dragon_ball_fusion_world"
        ):
            self.assertIn(key, keys)

    def test_all_and_each_tcg_switch_rows_immediately(self):
        self.assertEqual(
            {"pokemon", "onepiece", "union-arena", "dragon-ball"},
            self._displayed_site_keys(),
        )
        expected = {
            "pokemon": {"pokemon"},
            "onepiece": {"onepiece"},
            "union_arena": {"union-arena"},
            "dragon_ball_fusion_world": {"dragon-ball"},
        }
        for key, site_keys in expected.items():
            with self.subTest(key=key):
                self._select_tcg(key)
                self.assertEqual(site_keys, self._displayed_site_keys())

    def test_period_sales_mode_and_tcg_filters_combine(self):
        self._select_tcg("onepiece")
        self.page.period_tabs.setCurrentIndex(1)
        self.assertEqual({"onepiece-ended"}, self._displayed_site_keys())
        self.page.period_tabs.setCurrentIndex(0)
        self.page.sales_mode_filter.setCurrentIndex(
            self.page.sales_mode_filter.findData("ONLINE")
        )
        self.assertEqual(set(), self._displayed_site_keys())
        self._select_tcg("pokemon")
        self.assertEqual({"pokemon"}, self._displayed_site_keys())

    def test_tab_counts_follow_period_and_fine_filters(self):
        texts = {
            self.page.tcg_tabs.tab_bar.tabData(index):
            self.page.tcg_tabs.tab_bar.tabText(index)
            for index in range(self.page.tcg_tabs.tab_bar.count())
        }
        self.assertIn("(4)", texts["all"])
        for key in (
            "pokemon", "onepiece", "union_arena", "dragon_ball_fusion_world"
        ):
            self.assertIn("(1)", texts[key])
        self.page.period_tabs.setCurrentIndex(1)
        texts = {
            self.page.tcg_tabs.tab_bar.tabData(index):
            self.page.tcg_tabs.tab_bar.tabText(index)
            for index in range(self.page.tcg_tabs.tab_bar.count())
        }
        self.assertIn("(1)", texts["all"])
        self.assertIn("(1)", texts["onepiece"])
        self.assertIn("(0)", texts["pokemon"])

    def test_description_no_longer_depends_on_product_list(self):
        text = "\n".join(label.text() for label in self.page.findChildren(QLabel))
        self.assertIn("各店舗・公式サイトの抽選、予約、応募受付情報", text)
        self.assertNotIn("商品一覧にある店舗ごとの応募状況", text)


class ApplicationDashboardSalesModeEvidenceTest(unittest.TestCase):
    def test_explicit_evidence_propagates_and_ambiguous_stays_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = ProductStore(root)
            modes = [
                ("store", {"application_method": "店頭抽選"}, "STORE"),
                ("online", {"application_method": "Web抽選"}, "ONLINE"),
                (
                    "hybrid",
                    {"application_method": "Web応募", "conditions": ["店舗受取限定"]},
                    "HYBRID",
                ),
                ("unknown", {"application_method": "抽選"}, "UNKNOWN"),
            ]
            sites = []
            for key, evidence, _expected in modes:
                item = application_site(key, mode="UNKNOWN")
                item.pop("sales_mode")
                item.update(evidence)
                sites.append(item)
            store._save_product_file([{
                "id": "sales-modes", "name": "販売方式商品", "tcg_key": "pokemon",
                "sites": sites,
            }])
            rows = ApplicationDashboard(store, ConfigManager(root)).build(
                now=NOW, show_ended=True
            )["rows"]
        actual = {row["site_key"]: row["sales_mode"] for row in rows}
        self.assertEqual({key: expected for key, _evidence, expected in modes}, actual)

    def test_tcg_notation_variants_use_official_normalization(self):
        expected = {
            "ONE PIECE": "onepiece",
            "ワンピース": "onepiece",
            "union_arena": "union_arena",
            "UNION ARENA": "union_arena",
            "ユニオンアリーナ": "union_arena",
            "dragon_ball_fusion_world": "dragon_ball_fusion_world",
            "DBFW": "dragon_ball_fusion_world",
            "FUSION WORLD": "dragon_ball_fusion_world",
        }
        for value, key in expected.items():
            with self.subTest(value=value):
                self.assertEqual(key, normalize_key(value)[0])


class SourcesNavigationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_monitoring_navigation_keeps_scheduler_and_opens_sources_without_x_token(self):
        from ui.main_window import MainWindow

        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ,
            {"POKEYOYA_DATA_ROOT": directory, "POKEYOYA_X_BEARER_TOKEN": ""},
            clear=False,
        ):
            window = MainWindow()
            window.application_dashboard_page.period_timer.stop()
            self.assertIs(
                window.scheduler_button.parentWidget(),
                window.sources_button.parentWidget(),
            )
            self.assertFalse(window.scheduler_button.isHidden())
            self.assertFalse(window.sources_button.isHidden())
            self.assertEqual("自動監視", window.scheduler_button.text())
            self.assertEqual("公式情報ソース", window.sources_button.text())
            window.sources_button.click()
            self.app.processEvents()
            self.assertIs(window.sources_page, window.pages.currentWidget())
            self.assertIn("X情報 最終更新", window.sources_page.x_monitoring_summary.text())
            self.assertIn("状態: 未設定", window.sources_page.x_monitoring_summary.text())
            window.close()


if __name__ == "__main__":
    unittest.main()
