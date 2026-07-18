import json
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from core.application_dashboard import ApplicationDashboard
from core.application_period import ApplicationPeriodParser, JST
from core.application_status import evaluate_application_period
from core.auto_monitor_manager import AutoMonitorManager
from core.config_manager import ConfigManager
from core.product_store import ProductStore
from core.site_master_manager import SiteMasterManager
from core.site_monitor_sync import SiteMonitorSync


class DummyNotificationStore:
    def __init__(self):
        self.items = []

    def add(self, title, message, category="情報"):
        self.items.append((title, message, category))


class ApplicationPeriodTest(unittest.TestCase):
    NOW = datetime(2026, 7, 18, 12, 0, tzinfo=JST)

    def parse(self, text):
        return ApplicationPeriodParser.parse(
            text, now=self.NOW, release_date="2026-08-01"
        )

    def test_full_range_is_jst(self):
        value = self.parse("応募期間 2026年7月20日 10:00〜7月25日 23:59")
        self.assertEqual(value["application_start_at"][:16], "2026-07-20T10:00")
        self.assertEqual(value["application_end_at"][:16], "2026-07-25T23:59")
        self.assertTrue(value["application_end_at"].endswith("+09:00"))

    def test_omitted_year_uses_current_and_release_context(self):
        value = self.parse("抽選受付期間 7/20(月)〜7/25(土)")
        self.assertTrue(value["application_start_at"].startswith("2026-07-20"))
        self.assertEqual(value["application_method"], "抽選")

    def test_end_only_and_unknown(self):
        self.assertTrue(self.parse("応募締切 7月25日まで")["application_end_at"])
        self.assertTrue(self.parse("受付期間 未定")["period_unknown"])

    def test_start_only_and_result(self):
        value = self.parse("予約開始 7月20日 10:00\n結果発表予定 7月27日 12:00")
        self.assertTrue(value["application_start_at"])
        self.assertTrue(value["result_announcement_at"])

    def test_price_and_release_date_are_not_deadlines(self):
        value = self.parse("価格 7,200円　発売日 7月25日")
        self.assertFalse(value["application_end_at"])

    def test_evidence_removes_personal_identifiers(self):
        value = self.parse("応募締切 7月25日 user@example.com ABCDEFGHIJKLMNOPQRSTUVWXYZ")
        self.assertNotIn("user@example.com", value["period_evidence"])

    def test_period_statuses(self):
        base = {"application_start_at": "2026-07-20T10:00:00+09:00", "application_end_at": "2026-07-25T23:59:00+09:00"}
        self.assertEqual(evaluate_application_period(base, now=self.NOW)["period_status"], "受付前")
        self.assertEqual(evaluate_application_period(base, now=datetime(2026, 7, 22, tzinfo=JST))["period_status"], "受付中")
        self.assertEqual(evaluate_application_period(base, now=datetime(2026, 7, 25, 12, tzinfo=JST))["period_status"], "本日締切")
        self.assertTrue(evaluate_application_period(base, now=datetime(2026, 7, 26, tzinfo=JST))["period_ended"])


class AutoMonitorTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config = ConfigManager(self.root)
        self.store = ProductStore(self.root)
        self.manager = AutoMonitorManager(self.config, self.store)
        self.today = date(2026, 7, 18)

    def tearDown(self):
        self.temp.cleanup()

    def candidate(self, tcg="pokemon", offset=30, name="新弾ブースターパック"):
        return {
            "name": name,
            "tcg_key": tcg,
            "release_date": (self.today + timedelta(days=offset)).isoformat(),
            "product_kind": "ブースターパック",
            "official_url": "https://example.jp/products/new",
            "source_name": "公式",
        }

    def test_default_30_days_and_all_tcg(self):
        values = [self.candidate(tcg, index + 1, f"{tcg} 新弾") for index, tcg in enumerate(("pokemon", "onepiece", "yugioh", "gundam", "other"))]
        result = self.manager.add_due_candidates(values, today=self.today)
        self.assertEqual(result["added"], 5)
        self.assertEqual({item["tcg_key"] for item in result["products"]}, {"pokemon", "onepiece", "yugioh", "gundam", "other"})

    def test_setting_days_and_off(self):
        config = self.config.load()
        config["general"]["auto_monitor_days_before"] = 7
        self.config.save(config)
        self.assertEqual(self.manager.add_due_candidates([self.candidate(offset=8)], today=self.today)["added"], 0)
        config = self.config.load()
        config["general"]["auto_monitor_new_releases"] = False
        self.config.save(config)
        self.assertEqual(self.manager.add_due_candidates([self.candidate(offset=1)], today=self.today)["added"], 0)

    def test_duplicate_and_released_are_excluded(self):
        candidate = self.candidate(offset=1)
        self.assertEqual(self.manager.add_due_candidates([candidate, candidate], today=self.today)["added"], 1)
        self.assertEqual(self.manager.add_due_candidates([candidate], today=self.today)["added"], 0)
        self.assertEqual(self.manager.add_due_candidates([self.candidate(offset=-1)], today=self.today)["added"], 0)

    def test_accessory_and_non_https_are_excluded(self):
        self.assertEqual(self.manager.add_due_candidates([self.candidate(name="公式スリーブ")], today=self.today)["added"], 0)
        item = self.candidate()
        item["official_url"] = "http://example.jp/item"
        self.assertEqual(self.manager.add_due_candidates([item], today=self.today)["added"], 0)

    def test_user_exclusion_prevents_readdition(self):
        candidate = self.candidate(offset=1)
        result = self.manager.add_due_candidates([candidate], today=self.today)
        product_id = result["products"][0]["id"]
        self.assertTrue(self.store.exclude_auto_monitored_product(product_id))
        self.assertEqual(self.manager.add_due_candidates([candidate], today=self.today)["added"], 0)

    def test_saved_metadata_and_backup(self):
        self.manager.add_due_candidates([self.candidate(offset=1)], today=self.today)
        item = self.store._load_product_file()[0]
        for key in ("tcg_key", "name", "release_date", "product_kind", "official_url", "source_name", "auto_added_at"):
            self.assertTrue(item.get(key))
        self.manager.add_due_candidates([self.candidate(offset=2, name="別商品")], today=self.today)
        self.assertTrue(self.store.products_path.with_suffix(".json.bak").exists())


class SiteSyncAndDashboardTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config = ConfigManager(self.root)
        self.sites = SiteMasterManager(self.root)
        self.notifications = DummyNotificationStore()

    def tearDown(self):
        self.temp.cleanup()

    def test_new_site_defaults_off_and_notifies(self):
        SiteMonitorSync(self.config, self.sites, self.notifications).sync(notify=False)
        self.sites.add_site({"id": "new_shop", "name": "新店舗", "active": True, "tcg_keys": ["pokemon", "gundam"], "site_url": "https://shop.example.jp/"})
        result = SiteMonitorSync(self.config, self.sites, self.notifications).sync()
        self.assertFalse(result["settings"]["new_shop"])
        self.assertIn("new_shop", result["new_site_ids"])
        self.assertEqual(len(self.notifications.items), 1)

    def test_existing_choice_and_renamed_site_id_are_preserved(self):
        SiteMonitorSync(self.config, self.sites, self.notifications).sync(notify=False)
        config = self.config.load()
        first_id = self.sites.load_sites()[0]["id"]
        config["sites"][first_id] = True
        self.config.save(config)
        self.sites.update_site(first_id, {"name": "名称変更"})
        result = SiteMonitorSync(self.config, self.sites, self.notifications).sync(notify=False)
        self.assertTrue(result["settings"][first_id])
        self.assertEqual(sum(site["id"] == first_id for site in result["sites"]), 1)

    def test_disabled_site_is_retained(self):
        first_id = self.sites.load_sites()[0]["id"]
        self.sites.delete_site(first_id)
        result = SiteMonitorSync(self.config, self.sites, self.notifications).sync(notify=False)
        site = next(item for item in result["sites"] if item["id"] == first_id)
        self.assertFalse(site["active"])

    def test_ended_application_hidden_but_history_retained(self):
        store = ProductStore(self.root)
        store._save_product_file([{
            "id": "p", "name": "商品", "tcg_key": "pokemon", "release_date": "2026-08-01",
            "sites": [{"site_key": "s", "name": "店舗", "url": "https://example.jp/", "application_end_at": "2026-07-17T23:59:00+09:00", "application_state": "当選", "result_status": "当選"}],
        }])
        dashboard = ApplicationDashboard(store, self.config)
        now = datetime(2026, 7, 18, 12, tzinfo=JST)
        self.assertEqual(dashboard.build(show_ended=False, now=now)["rows"], [])
        visible = dashboard.build(show_ended=True, now=now)
        self.assertEqual(len(visible["rows"]), 1)
        self.assertEqual(visible["rows"][0]["application_state"], "当選")
        self.assertEqual(visible["ended_rows"], 1)

    def test_backup_and_rollback(self):
        config = self.config.load()
        config["general"]["auto_monitor_days_before"] = 7
        self.config.save(config)
        config["general"]["auto_monitor_days_before"] = 60
        self.config.save(config)
        self.assertTrue(self.config.rollback())
        self.assertEqual(self.config.load()["general"]["auto_monitor_days_before"], 7)


class SettingsP28UiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_settings_exposes_auto_monitor_period_history_and_dynamic_sites(self):
        from ui.settings_page import SettingsPage
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            "os.environ", {"POKEYOYA_DATA_ROOT": directory}, clear=False
        ):
            page = SettingsPage()
            self.assertEqual(
                [page.auto_monitor_days.itemData(i) for i in range(page.auto_monitor_days.count())],
                [7, 14, 30, 60],
            )
            self.assertTrue(page.site_checks)
            self.assertEqual(page.site_tcg_filter.itemData(0), "all")
            self.assertIsNotNone(page.show_ended_applications)
            self.assertIsNotNone(page.notify_new_sites)
            page.close()


if __name__ == "__main__":
    unittest.main()
