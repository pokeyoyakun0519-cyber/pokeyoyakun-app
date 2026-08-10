from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QWidget

from core.application_status import JST
from core.notification_store import NotificationStore
from core.phase3_dashboard import HomeDashboardService


class SchedulerStub:
    class Event:
        def connect(self, _callback):
            pass

    status_changed = Event()
    run_completed = Event()

    def run_now(self):
        pass


class DashboardServiceStub:
    def build(self, *, now=None):
        timestamp = (now or datetime.now(JST)).isoformat()
        return {
            "actions": [{
                "kind": "today_deadline", "lead": "あと2時間",
                "title": "ゲオ応募締切", "product_id": "p1",
                "store_id": "geo", "completed": False,
            }],
            "events": [{
                "starts_at": timestamp, "icon": "⏰", "title": "商品A",
                "event_type": "応募締切", "site_name": "ゲオ", "product_id": "p1",
            }],
            "metrics": {"new_products": 1, "new_stores": 0},
            "favorite_products": [{"product_id": "p1", "canonical_name": "商品A", "tcg_key": "pokemon"}],
            "new_products": [{"product_id": "p2", "canonical_name": "商品B", "tcg_key": "onepiece"}],
            "notifications": [{"title": f"通知{i}", "category": "情報", "created_at": timestamp, "read": i > 0} for i in range(5)],
            "timeline": [{"title": "商品A追加", "event_type": "新商品", "occurred_at": timestamp, "product_id": "p1"}],
        }


class HomeDashboardRenewalTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_greeting_changes_by_time_of_day(self):
        from ui.home_page import HomePage

        self.assertEqual(HomePage._greeting(6), "おはようございます")
        self.assertEqual(HomePage._greeting(12), "こんにちは")
        self.assertEqual(HomePage._greeting(20), "こんばんは")

    def test_home_has_required_cards_counts_and_navigation(self):
        from ui.home_page import HomePage

        with tempfile.TemporaryDirectory() as directory, patch.dict(
            "os.environ", {"POKEYOYA_DATA_ROOT": directory}, clear=False
        ), patch("ui.home_page.HomeDashboardService", return_value=DashboardServiceStub()):
            page = HomePage(SchedulerStub())
            self.assertTrue(page.greeting_label.text())
            self.assertRegex(page.date_label.text(), r"\d+年\d+月\d+日")
            self.assertEqual(page.summary_values["deadlines"].text(), "1件")
            self.assertEqual(page.summary_values["releases"].text(), "0件")
            self.assertEqual(page.summary_values["new_items"].text(), "1件")
            for card in (
                page.actions_card, page.calendar_card, page.timeline_card,
                page.notifications_card, page.favorites_card,
                page.new_products_card, page.changes_card,
            ):
                self.assertGreater(card.body.count(), 0)

            destinations = []
            page.navigate_requested.connect(lambda target, item_id: destinations.append((target, item_id)))
            product_button = next(
                page.new_products_card.body.itemAt(index).widget()
                for index in range(page.new_products_card.body.count())
                if isinstance(page.new_products_card.body.itemAt(index).widget(), QPushButton)
            )
            product_button.click()
            self.assertEqual(destinations[-1], ("product", "p2"))
            page.close()

    def test_empty_data_uses_clear_placeholders(self):
        from ui.home_page import HomePage

        class EmptyService:
            def build(self, *, now=None):
                return {
                    "actions": [], "events": [], "metrics": {"new_products": 0, "new_stores": 0},
                    "favorite_products": [], "new_products": [], "notifications": [], "timeline": [],
                }

        with tempfile.TemporaryDirectory() as directory, patch.dict(
            "os.environ", {"POKEYOYA_DATA_ROOT": directory}, clear=False
        ), patch("ui.home_page.HomeDashboardService", return_value=EmptyService()):
            page = HomePage(SchedulerStub())
            texts = [
                widget.text()
                for card in (page.actions_card, page.calendar_card, page.timeline_card, page.notifications_card, page.favorites_card, page.new_products_card, page.changes_card)
                for index in range(card.body.count())
                if isinstance((widget := card.body.itemAt(index).widget()), QLabel)
            ]
            self.assertEqual(len(texts), 7)
            self.assertTrue(all(text.strip() for text in texts))
            page.close()

    def test_responsive_columns_switch_between_two_columns_and_stack(self):
        from ui.home_page import ResponsiveColumns

        columns = ResponsiveColumns(QWidget(), QWidget())
        columns._reflow(1000)
        self.assertFalse(columns._stacked)
        left_index = columns.grid.indexOf(columns.left)
        right_index = columns.grid.indexOf(columns.right)
        self.assertEqual(columns.grid.getItemPosition(left_index)[:2], (0, 0))
        self.assertEqual(columns.grid.getItemPosition(right_index)[:2], (0, 1))
        columns._reflow(600)
        self.assertTrue(columns._stacked)
        right_index = columns.grid.indexOf(columns.right)
        self.assertEqual(columns.grid.getItemPosition(right_index)[:2], (1, 0))
        columns.close()

    def test_service_returns_latest_five_notifications_and_new_products(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            now = datetime.now(JST)
            products_path = root / "data" / "products.json"
            products_path.parent.mkdir(parents=True)
            products_path.write_text(json.dumps([{
                "id": "new-product", "name": "新着商品",
                "created_at": now.isoformat(), "sites": [],
            }], ensure_ascii=False), encoding="utf-8")
            notifications = NotificationStore(root)
            for index in range(6):
                notifications.add(f"通知{index}", "本文")

            data = HomeDashboardService(root).build(now=now)
            self.assertEqual(len(data["notifications"]), 5)
            self.assertEqual(data["notifications"][0]["title"], "通知5")
            self.assertEqual(len(data["new_products"]), 1)


if __name__ == "__main__":
    unittest.main()
