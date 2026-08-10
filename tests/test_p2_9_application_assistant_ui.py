from __future__ import annotations

import copy
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QTabBar

from core.application_change_tracker import ApplicationChangeTracker
from core.application_condition_detector import ApplicationConditionDetector
from core.application_dashboard import ApplicationDashboard
from core.application_reminder import ApplicationDeadlineReminder
from core.application_status import JST
from core.config_manager import ConfigManager
from core.notification_store import NotificationStore
from core.product_store import ProductStore


def product(end: datetime, *, site_key: str = "shop", tcg_key: str = "pokemon") -> dict:
    return {
        "id": "p1", "name": "新商品", "tcg_key": tcg_key,
        "release_date": "2026-08-10",
        "sites": [{
            "site_key": site_key, "name": "テスト店舗",
            "url": "https://www.yodobashi.com/product/1",
            "application_url": "https://www.yodobashi.com/application/1",
            "application_start_at": "2026-07-01T00:00:00+09:00",
            "application_end_at": end.isoformat(),
            "application_method": "Web抽選",
            "application_conditions": "会員登録必須",
            "status": "抽選受付中", "result_status": "未確認",
        }],
    }


class ReminderTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = ProductStore(self.root)
        self.config = ConfigManager(self.root)
        self.end = datetime(2026, 8, 2, 12, tzinfo=JST)
        self.store._save_product_file([product(self.end)])
        self.reminder = ApplicationDeadlineReminder(self.store, self.config, self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_24h_3h_30m_and_duplicate_prevention(self):
        checks = ((1440, self.end - timedelta(hours=24)),
                  (180, self.end - timedelta(hours=3)),
                  (30, self.end - timedelta(minutes=30)))
        for expected, now in checks:
            due = self.reminder.collect_due(now=now)
            self.assertEqual([item["offset_minutes"] for item in due], [expected])
            sent = self.reminder.run(lambda _item: True, now=now)
            self.assertEqual(len(sent), 1)
            self.assertEqual(self.reminder.collect_due(now=now), [])
        self.assertEqual(len(self.reminder._load_history()["history"]), 3)

    def test_applied_ended_final_and_disabled_are_suppressed(self):
        self.store.save_site_application_state(
            "p1", "shop", "https://www.yodobashi.com/product/1", True, "pokemon"
        )
        self.assertEqual(self.reminder.collect_due(now=self.end - timedelta(hours=3)), [])
        self.store.save_site_application_state(
            "p1", "shop", "https://www.yodobashi.com/product/1", False, "pokemon"
        )
        self.assertEqual(self.reminder.collect_due(now=self.end + timedelta(seconds=1)), [])
        self.store.save_site_result(
            "p1", "shop", "https://www.yodobashi.com/product/1", "当選"
        )
        self.assertEqual(self.reminder.collect_due(now=self.end - timedelta(hours=3)), [])
        config = self.config.load()
        config["application_assistant"]["deadline_reminders_enabled"] = False
        self.config.save(config)
        self.assertEqual(self.reminder.collect_due(now=self.end - timedelta(hours=3)), [])

    def test_individual_timing_can_be_disabled_and_structure_is_extensible(self):
        config = self.config.load()
        config["application_assistant"]["reminders"] = [
            {"minutes": 180, "enabled": False, "label": "3時間前"},
            {"minutes": 45, "enabled": True, "label": "45分前"},
        ]
        self.config.save(config)
        self.assertEqual(self.reminder.collect_due(now=self.end - timedelta(hours=3)), [])
        due = self.reminder.collect_due(now=self.end - timedelta(minutes=45))
        self.assertEqual(due[0]["offset_minutes"], 45)


class DashboardPhase2Test(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = ProductStore(self.root)
        self.config = ConfigManager(self.root)
        now = datetime(2026, 7, 18, 12, tzinfo=JST)
        first = product(now + timedelta(hours=5), site_key="late", tcg_key="pokemon")
        first["sites"].append({
            **copy.deepcopy(first["sites"][0]),
            "site_key": "soon", "name": "近い店舗",
            "url": "https://www.biccamera.com/item/1",
            "application_url": "https://www.biccamera.com/apply/1",
            "application_end_at": (now + timedelta(hours=1)).isoformat(),
        })
        second = product(now + timedelta(days=2), site_key="op", tcg_key="onepiece")
        second["id"] = "p2"
        second["name"] = "別商品"
        self.store._save_product_file([first, second])
        self.dashboard = ApplicationDashboard(self.store, self.config)
        self.now = now

    def tearDown(self):
        self.temp.cleanup()

    def test_deadline_sort_state_and_tcg_tabs_can_be_combined(self):
        data = self.dashboard.build(
            state_filter="本日締切", tcg_filter="pokemon", now=self.now
        )
        self.assertEqual([row["site_key"] for row in data["rows"]], ["soon", "late"])
        self.assertEqual(data["state_counts"]["本日締切"], 2)
        self.assertEqual(data["tcg_counts"]["onepiece"], 1)

    def test_product_group_and_individual_rows(self):
        data = self.dashboard.build(state_filter="本日締切", now=self.now)
        self.assertEqual(len(data["rows"]), 2)
        self.assertEqual(len(data["groups"]), 1)
        self.assertEqual(len(data["groups"][0]["rows"]), 2)

    def test_ended_is_hidden_by_default_and_has_ended_state(self):
        hidden = self.dashboard.build(now=self.now + timedelta(days=3))
        self.assertEqual(hidden["rows"], [])
        ended = self.dashboard.build(
            state_filter="終了済み", show_ended=True, now=self.now + timedelta(days=3)
        )
        self.assertEqual(len(ended["rows"]), 3)
        self.assertTrue(all(row["dashboard_state"] == "終了済み" for row in ended["rows"]))


class ConditionAndChangeTest(unittest.TestCase):
    def test_all_condition_types_and_low_confidence_confirmation(self):
        text = (
            "専用アプリから応募。会員登録必須。クレジットカード登録必須。店舗受取限定。"
            "本人確認書類が必須。過去の購入履歴が必要。東京都居住者限定。18歳以上。"
            "店頭受付のみ。対象商品との同時購入が必須。支払方法は現金のみ。キャンセル不可。"
        )
        detected = ApplicationConditionDetector.detect({"application_conditions": text})
        self.assertEqual(len({item["key"] for item in detected}), 12)
        self.assertTrue(all(not item["requires_confirmation"] for item in detected))
        weak = ApplicationConditionDetector.detect({"application_conditions": "会員について案内があります"})
        self.assertEqual(weak[0]["display"], "会員登録必須（要確認）")

    def test_deadline_change_is_recorded_once_and_identical_content_is_silent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tracker = ApplicationChangeTracker(root)
            end = datetime(2026, 8, 2, 12, tzinfo=JST)
            initial = [product(end)]
            self.assertEqual(tracker.compare_and_update(initial), [])
            changed = copy.deepcopy(initial)
            changed[0]["sites"][0]["application_end_at"] = (
                end + timedelta(hours=2)
            ).isoformat()
            events = tracker.compare_and_update(changed)
            self.assertEqual(len(events), 1)
            self.assertIn("application_end_at", events[0]["changes"])
            self.assertEqual(tracker.compare_and_update(changed), [])
            self.assertEqual(len(tracker.pending_notifications(important_only=True)), 1)
            tracker.mark_notified([events[0]["id"]])
            self.assertEqual(tracker.pending_notifications(important_only=True), [])

    def test_notification_history_keeps_application_action(self):
        with tempfile.TemporaryDirectory() as directory:
            store = NotificationStore(Path(directory))
            store.add(
                "締切", "残り30分", "応募締切",
                action_url="https://www.yodobashi.com/apply/1",
                action_label="応募ページを開く",
            )
            item = store.load()[0]
            self.assertEqual(item["action_label"], "応募ページを開く")
            self.assertTrue(item["action_url"].startswith("https://"))


class CommonEditionAndUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_user_and_owner_share_main_window_assistant(self):
        from ui.main_window import MainWindow
        from ui.owner_main_window import OwnerMainWindow
        self.assertTrue(issubclass(OwnerMainWindow, MainWindow))
        self.assertTrue(hasattr(MainWindow, "_setup_application_assistant"))
        self.assertTrue(hasattr(MainWindow, "_check_application_assistant"))

    def test_dashboard_has_state_and_tcg_tabs_group_toggle(self):
        from ui.application_dashboard_page import ApplicationDashboardPage
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            "os.environ", {"POKEYOYA_DATA_ROOT": directory}, clear=False
        ):
            page = ApplicationDashboardPage()
            tabs = page.findChildren(QTabBar)
            tab_sets = [
                [tab.tabData(i) for i in range(tab.count())]
                for tab in tabs
            ]
            self.assertIn(
                [
                    "all", "pokemon", "onepiece", "yugioh", "gundam",
                    "duelmasters", "weiss", "mtg", "other",
                ],
                tab_sets,
            )
            self.assertIn(
                [
                    "すべて", "未応募", "応募済み", "本日締切",
                    "結果待ち", "当選", "落選", "終了済み",
                ],
                tab_sets,
            )
            self.assertTrue(page.group_by_product.isChecked())
            self.assertEqual(page.sort_mode.currentText(), "応募締切順")
            page.close()

    def test_settings_exposes_phase1_and_phase2_switches(self):
        from ui.settings_page import SettingsPage
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            "os.environ", {"POKEYOYA_DATA_ROOT": directory}, clear=False
        ):
            page = SettingsPage()
            self.assertTrue(page.deadline_24h.isChecked())
            self.assertTrue(page.deadline_3h.isChecked())
            self.assertTrue(page.deadline_30m.isChecked())
            self.assertTrue(page.group_applications_by_product.isChecked())
            self.assertTrue(page.notify_important_application_changes.isChecked())
            page.close()


if __name__ == "__main__":
    unittest.main()
