from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from core.activity_timeline import ActivityTimeline
from core.application_status import JST
from core.favorites_manager import FavoritesManager
from core.phase3_dashboard import (
    ApplicationStatistics, CalendarService, HomeDashboardService,
    is_new, product_priority,
)
from core.product_image_cache import ProductImageCache
from core.product_master import ProductMasterManager
from core.product_store import ProductStore
from core.site_master_manager import SiteMasterManager
from core.store_history import StoreHistoryManager


def sample_product(now: datetime, *, name="ブラックボルト", product_id="p1"):
    return {
        "id": product_id, "name": name, "tcg_key": "pokemon",
        "release_date": (now + timedelta(days=5)).date().isoformat(),
        "created_at": now.isoformat(), "official_url": "https://www.pokemon-card.com/x",
        "sites": [{
            "site_key": "geo", "name": "ゲオ", "status": "抽選受付中",
            "url": "https://geo-online.co.jp/x", "application_url": "https://geo-online.co.jp/apply/x",
            "application_start_at": now.replace(hour=8).isoformat(),
            "application_end_at": (now + timedelta(hours=2)).isoformat(),
            "result_announcement_at": now.replace(hour=20).isoformat(),
            "reservation_start_at": now.isoformat(),
            "pickup_deadline_at": (now + timedelta(days=4)).isoformat(),
            "payment_deadline_at": (now + timedelta(days=3)).isoformat(),
            "application_state": "未応募", "result_status": "未確認",
        }],
    }


class ProductMasterAndFavoriteTest(unittest.TestCase):
    def test_aliases_merge_into_stable_product_id(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = ProductMasterManager(Path(directory))
            products = manager.synchronize([
                {"id": "original", "name": "ブラックボルト", "tcg_key": "pokemon", "release_date": "2026-08-01", "sites": []},
                {"id": "variant", "name": "ブラックボルト BOX", "tcg_key": "pokemon", "release_date": "2026-08-01", "sites": []},
                {"name": "ブラックボルト ボックス", "tcg_key": "pokemon", "release_date": "2026-08-01", "sites": []},
            ])
            self.assertEqual(len(products), 1)
            self.assertEqual(products[0]["product_id"], "original")
            self.assertEqual(products[0]["canonical_name"], "ブラックボルト")
            self.assertEqual(len(products[0]["aliases"]), 3)
            record = manager.load()[0]
            for key in ("canonical_name", "aliases", "product_id", "release_date", "tcg_key", "official_url", "image_url", "price"):
                self.assertIn(key, record)

    def test_product_and_store_favorites(self):
        with tempfile.TemporaryDirectory() as directory:
            favorites = FavoritesManager(Path(directory))
            favorites.set_favorite("product", "p1", True)
            favorites.set_favorite("store", "geo", True)
            self.assertTrue(favorites.is_favorite("product", "p1"))
            self.assertTrue(favorites.is_favorite("store", "geo"))
            favorites.set_favorite("product", "p1", False)
            self.assertFalse(favorites.is_favorite("product", "p1"))


class ImageCacheTest(unittest.TestCase):
    def test_first_fetch_is_cached_version_change_refetches_and_cleanup_removes(self):
        with tempfile.TemporaryDirectory() as directory:
            calls = []
            def download(url):
                calls.append(url)
                return b"image", "image/png"
            cache = ProductImageCache(Path(directory), download)
            first = cache.get("p1", "https://images.example.jp/p.png", version="1")
            second = cache.get("p1", "https://images.example.jp/p.png", version="1")
            third = cache.get("p1", "https://images.example.jp/p.png", version="2")
            self.assertEqual(first, second)
            self.assertNotEqual(second, third)
            self.assertEqual(len(calls), 2)
            self.assertEqual(cache.cleanup(active_product_ids=set()), 1)
            self.assertFalse(third.exists())

    def test_unsafe_image_url_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = ProductImageCache(Path(directory), lambda _url: (b"x", "image/png"))
            self.assertIsNone(cache.get("p", "http://127.0.0.1/a.png"))


class DashboardLogicTest(unittest.TestCase):
    NOW = datetime(2026, 7, 18, 12, tzinfo=JST)

    def test_priority_and_new_badge(self):
        product = sample_product(self.NOW)
        self.assertEqual(product_priority(product, now=self.NOW)["level"], 5)
        self.assertTrue(is_new(product["created_at"], now=self.NOW))
        self.assertFalse(is_new((self.NOW - timedelta(days=8)).isoformat(), now=self.NOW))

    def test_calendar_has_all_event_types_and_icons(self):
        events = CalendarService().build_events([sample_product(self.NOW)])
        types = {event["event_type"] for event in events}
        self.assertTrue({"応募開始", "応募締切", "結果発表", "発売日", "予約開始", "店頭受取期限", "支払期限"} <= types)
        self.assertTrue(all(event["icon"] for event in events))

    def test_statistics_excludes_waiting_from_denominator(self):
        product = sample_product(self.NOW)
        base = product["sites"][0]
        product["sites"] = [
            {**base, "site_key": "win", "name": "A", "applied": True, "result_status": "当選", "applied_at": "2026-07-01"},
            {**base, "site_key": "loss", "name": "B", "applied": True, "result_status": "落選", "applied_at": "2026-07-01"},
            {**base, "site_key": "wait", "name": "C", "applied": True, "result_status": "未確認", "applied_at": "2026-07-01"},
        ]
        data = ApplicationStatistics().build([product])
        self.assertEqual(data["total"], 3)
        self.assertEqual(data["waiting"], 1)
        self.assertEqual(data["win_rate"], 50.0)
        self.assertTrue(data["reference"])

    def test_today_actions_are_prioritized_and_monitoring_is_aggregated(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ProductStore(root)._save_product_file([sample_product(self.NOW)])
            data = HomeDashboardService(root).build(now=self.NOW)
            self.assertEqual(data["actions"][0]["kind"], "today_deadline")
            self.assertEqual(data["metrics"]["today_deadlines"], 1)
            self.assertIn("stores", data["monitoring"])


class TimelineAndHistoryTest(unittest.TestCase):
    def test_timeline_keeps_latest_twenty_and_store_history_deduplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            timeline = ActivityTimeline(root)
            for index in range(25):
                timeline.add("新商品", f"商品{index}", product_id=str(index), occurred_at=f"2026-07-{(index % 20) + 1:02d}T00:00:00")
            self.assertEqual(len(timeline.load()), 20)
            history = StoreHistoryManager(root)
            history.record("geo", "抽選追加", "商品", occurred_at="2026-07-18T00:00:00")
            history.record("geo", "抽選追加", "商品", occurred_at="2026-07-18T12:00:00")
            self.assertEqual(len(history.history("geo")), 1)

    def test_site_addition_records_history_and_created_at(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manager = SiteMasterManager(root)
            manager.add_site({"id": "new_shop", "name": "新店舗", "site_url": "https://shop.example.jp/"})
            site = next(item for item in manager.load_sites() if item["id"] == "new_shop")
            self.assertTrue(site["created_at"])
            self.assertEqual(StoreHistoryManager(root).history("new_shop")[0]["action"], "店舗追加")


class CommonUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_user_and_owner_share_calendar_statistics_and_home(self):
        from ui.main_window import MainWindow
        from ui.owner_main_window import OwnerMainWindow
        self.assertTrue(issubclass(OwnerMainWindow, MainWindow))
        labels = dict(MainWindow._navigation_labels(MainWindow.__new__(MainWindow)))
        self.assertEqual(labels["calendar_button"], "カレンダー")
        self.assertEqual(labels["statistics_button"], "応募統計")

    def test_pages_construct_with_temporary_data_root(self):
        from ui.calendar_page import CalendarPage
        from ui.home_page import HomePage
        from ui.statistics_page import StatisticsPage
        class Scheduler:
            class Event:
                def connect(self, _callback): pass
            status_changed = Event()
            run_completed = Event()
            def run_now(self): pass
        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", {"POKEYOYA_DATA_ROOT": directory}, clear=False):
            pages = [HomePage(Scheduler()), CalendarPage(), StatisticsPage()]
            for page in pages:
                page.close()


if __name__ == "__main__":
    unittest.main()
