from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "app"))

from core.application_notifications import ApplicationNotificationService
from core.application_reminder import ApplicationDeadlineReminder
from core.application_status import JST
from core.config_manager import ConfigManager
from core.notification_store import NotificationStore
from core.product_store import ProductStore


NOW = datetime(2026, 8, 20, 12, 0, tzinfo=JST)


def product(*, verification="confirmed", state="未応募", result="未確認", **site_overrides):
    site = {
        "id": "site-1",
        "site_key": "shop-1",
        "name": "公式ショップ",
        "application_url": "https://official.example/apply",
        "application_status": "抽選受付開始",
        "application_state": state,
        "result_status": result,
        "sales_mode": "ONLINE",
        "prefecture": "東京都",
        "verification_status": verification,
        "confirmed": verification == "confirmed",
        "detected_at": (NOW - timedelta(hours=1)).isoformat(),
        "application_end_at": (NOW + timedelta(hours=24)).isoformat(),
    }
    site.update(site_overrides)
    return {
        "id": "product-1",
        "name": "テスト商品",
        "tcg_key": "pokemon",
        "product_category": "CARD",
        "sites": [site],
    }


class ApplicationNotificationServiceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config = ConfigManager(self.root)
        self.service = ApplicationNotificationService(self.config)

    def tearDown(self):
        self.temp.cleanup()

    def test_confirmed_application_start_is_notified(self):
        events = self.service.collect([product()], now=NOW)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "APPLICATION_START")
        self.assertTrue(events[0]["dedupe_key"])

    def test_candidate_is_never_notified(self):
        self.assertEqual(self.service.collect([product(verification="pending")], now=NOW), [])

    def test_notification_off_and_filters(self):
        settings = self.config.load()
        settings["notification"]["application_events_enabled"] = False
        self.config.save(settings)
        self.assertEqual(self.service.collect([product()], now=NOW), [])

        settings["notification"]["application_events_enabled"] = True
        settings["notification"]["tcg"]["pokemon"] = False
        self.config.save(settings)
        self.assertEqual(self.service.collect([product()], now=NOW), [])

        settings["notification"]["tcg"]["pokemon"] = True
        settings["notification"]["prefectures"] = ["大阪府"]
        self.config.save(settings)
        self.assertEqual(self.service.collect([product()], now=NOW), [])

    def test_applied_and_final_result_are_suppressed(self):
        self.assertEqual(self.service.collect([product(state="応募済み")], now=NOW), [])
        self.assertEqual(self.service.collect([product(result="当選")], now=NOW), [])

    def test_old_records_do_not_flood_first_start(self):
        value = product()
        value["sites"][0]["detected_at"] = (NOW - timedelta(days=3)).isoformat()
        self.assertEqual(self.service.collect([value], now=NOW), [])

    def test_history_deduplicates_stable_event_key(self):
        store = NotificationStore(self.root)
        event = self.service.collect([product()], now=NOW)[0]
        first = store.add(
            "通知", "本文", application_id=event["application_id"],
            event_type=event["event_type"], dedupe_key=event["dedupe_key"],
        )
        second = store.add(
            "通知", "本文", application_id=event["application_id"],
            event_type=event["event_type"], dedupe_key=event["dedupe_key"],
        )
        self.assertTrue(first)
        self.assertFalse(second)
        self.assertEqual(len(store.load()), 1)
        self.assertFalse(store.load()[0]["read"])

    def test_deadline_24h_and_3h_and_candidate_exclusion(self):
        self.root.joinpath("data").mkdir(parents=True)
        values = [product()]
        self.root.joinpath("data", "products.json").write_text(
            json.dumps(values, ensure_ascii=False), encoding="utf-8"
        )
        reminder = ApplicationDeadlineReminder(
            ProductStore(self.root), self.config, self.root
        )
        due_24h = reminder.collect_due(now=NOW)
        self.assertEqual(due_24h[0]["offset_minutes"], 1440)

        values[0]["sites"][0]["application_end_at"] = (NOW + timedelta(hours=3)).isoformat()
        self.root.joinpath("data", "products.json").write_text(
            json.dumps(values, ensure_ascii=False), encoding="utf-8"
        )
        due_3h = reminder.collect_due(now=NOW)
        self.assertEqual(due_3h[0]["offset_minutes"], 180)

        values[0]["sites"][0]["verification_status"] = "pending"
        values[0]["sites"][0]["confirmed"] = False
        self.root.joinpath("data", "products.json").write_text(
            json.dumps(values, ensure_ascii=False), encoding="utf-8"
        )
        self.assertEqual(reminder.collect_due(now=NOW), [])

    def test_settings_ui_preserves_notification_filters(self):
        source = (PROJECT_ROOT / "app" / "ui" / "settings_page.py").read_text(
            encoding="utf-8"
        )
        for marker in (
            "application_events_enabled",
            "notification_tcg_checks",
            "notification_sales_checks",
            "notification_prefectures",
            "notification_product_category_checks",
            '**dict(config.get("notification", {}))',
        ):
            self.assertIn(marker, source)


if __name__ == "__main__":
    unittest.main()
