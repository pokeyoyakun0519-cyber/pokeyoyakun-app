from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton

from core.global_search import GlobalSearchService


def sample_data():
    return {
        "products": [{
            "product_id": "p1", "canonical_name": "ブラックボルト BOX",
            "aliases": ["ブラックボルト ボックス"], "tcg_key": "pokemon",
            "tcg": "ポケモンカード", "category": "拡張パック",
            "sites": [{
                "site_key": "geo", "name": "ゲオ",
                "status": "抽選受付中", "application_method": "アプリ抽選",
                "application_conditions": "会員登録必須",
            }],
        }],
        "stores": [{
            "id": "geo", "name": "ゲオ", "aliases": ["GEO"],
            "tcg_keys": ["pokemon"], "sales_type": "抽選・予約",
            "application_method": "公式アプリ",
        }],
        "notifications": [{
            "title": "ゲオ抽選の締切変更", "message": "締切が延長されました",
            "category": "応募情報変更", "created_at": "2026/07/18 10:00:00",
        }],
        "sources": [{
            "id": "pokemon-official", "name": "ポケモンカード公式",
            "tcg": "ポケモンカード", "last_title": "新商品ニュース",
            "last_status": "正常", "url": "https://www.pokemon-card.com/",
        }],
        "favorites": {"products": ["p1"], "stores": ["geo"]},
    }


class GlobalSearchServiceTest(unittest.TestCase):
    def setUp(self):
        self.service = GlobalSearchService(limit_per_group=20)
        self.data = sample_data()

    def test_detailed_search_groups_all_supported_types(self):
        results = self.service.search("ポケモン", mode="detailed", datasets=self.data)
        self.assertEqual(
            set(results),
            {"products", "applications", "stores", "favorites", "sources"},
        )
        notification_results = self.service.search("締切変更", mode="detailed", datasets=self.data)
        self.assertEqual(notification_results["notifications"][0]["target"], "notifications")

    def test_multiple_keywords_alias_and_category_are_searchable(self):
        results = self.service.search("ポケモン ゲオ", mode="simple", datasets=self.data)
        self.assertEqual(results["applications"][0]["item_id"], "p1")
        alias_results = self.service.search("ブラックボルト ボックス", mode="simple", datasets=self.data)
        self.assertIn("products", alias_results)
        category_results = self.service.search("拡張パック", mode="simple", datasets=self.data)
        self.assertEqual(category_results["products"][0]["title"], "ブラックボルト BOX")

    def test_simple_hides_sources_and_detailed_shows_them(self):
        simple = self.service.search("ポケモンカード公式", mode="simple", datasets=self.data)
        detailed = self.service.search("ポケモンカード公式", mode="detailed", datasets=self.data)
        self.assertNotIn("sources", simple)
        self.assertIn("sources", detailed)

    def test_favorites_and_group_limit_with_large_data(self):
        favorites = self.service.search("お気に入り", mode="simple", datasets=self.data)
        self.assertEqual(len(favorites["favorites"]), 2)
        large = sample_data()
        large["products"] = [
            {"product_id": f"p{index}", "name": f"大量商品 {index}", "sites": []}
            for index in range(5000)
        ]
        results = self.service.search("大量商品", mode="detailed", datasets=large)
        self.assertEqual(len(results["products"]), 20)


class GlobalSearchWidgetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def wait_for_search(self, widget):
        for _ in range(100):
            self.app.processEvents()
            if widget.status_label.text() not in {"検索中…", "商品・応募・店舗・通知などを検索できます"}:
                return
            QTest.qWait(10)
        self.fail("検索処理が完了しませんでした")

    def test_typing_shows_loading_then_grouped_results_and_click_navigates(self):
        from ui.global_search_widget import GlobalSearchWidget

        class Service:
            def search(self, query, *, mode):
                self.query = query
                self.mode = mode
                return {
                    "products": [{
                        "title": "ブラックボルト", "detail": "ポケモンカード",
                        "target": "product", "item_id": "p1",
                    }]
                }

        service = Service()
        widget = GlobalSearchWidget(lambda: "simple", service=service)
        self.addCleanup(widget.close)
        destinations = []
        widget.result_activated.connect(lambda target, item_id: destinations.append((target, item_id)))
        widget.search_input.setText("ブラック")
        self.assertEqual(widget.status_label.text(), "検索中…")
        self.assertFalse(widget.results_panel.isHidden())
        widget.search_now()
        self.wait_for_search(widget)
        self.assertEqual(widget.status_label.text(), "1件")
        self.assertEqual(service.query, "ブラック")
        buttons = widget.result_scroll.widget().findChildren(QPushButton, "GlobalSearchResultButton")
        self.assertEqual(len(buttons), 1)
        buttons[0].click()
        self.assertEqual(destinations, [("product", "p1")])
        self.assertTrue(widget.results_panel.isHidden())

    def test_zero_results_and_failure_are_shown_inline(self):
        from ui.global_search_widget import GlobalSearchWidget

        class EmptyService:
            def search(self, query, *, mode):
                return {}

        empty = GlobalSearchWidget(lambda: "simple", service=EmptyService())
        self.addCleanup(empty.close)
        empty.search_input.setText("見つからない")
        empty.search_now()
        self.wait_for_search(empty)
        self.assertEqual(empty.status_label.text(), "0件")
        self.assertIn("一致する結果はありません", empty.result_scroll.widget().findChild(type(empty.status_label)).text())

        class BrokenService:
            def search(self, query, *, mode):
                raise OSError("データを読み込めません")

        broken = GlobalSearchWidget(lambda: "detailed", service=BrokenService())
        self.addCleanup(broken.close)
        broken.search_input.setText("商品")
        broken.search_now()
        self.wait_for_search(broken)
        self.assertEqual(broken.status_label.text(), "検索エラー")
        error = broken.result_scroll.widget().findChild(type(broken.status_label), "GlobalSearchError")
        self.assertIn("OSError", error.text())
        self.assertIn("データを読み込めません", error.text())

    def test_user_and_owner_both_include_global_search(self):
        from ui.main_window import MainWindow
        from ui.owner_main_window import OwnerMainWindow

        with tempfile.TemporaryDirectory() as directory, patch.dict(
            "os.environ", {"POKEYOYA_DATA_ROOT": directory}, clear=False
        ):
            for window_type in (MainWindow, OwnerMainWindow):
                with self.subTest(window=window_type.__name__):
                    window = window_type()
                    self.assertIsNotNone(window.global_search)
                    self.assertEqual(window.global_search.mode_provider(), window.ui_mode)
                    window.close()


if __name__ == "__main__":
    unittest.main()
