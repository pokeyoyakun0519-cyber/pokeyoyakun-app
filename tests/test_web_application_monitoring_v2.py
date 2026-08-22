import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

from core.application_dashboard import ApplicationDashboard
from core.application_filters import (
    DEADLINE_SOON_HOURS,
    REGION_PREFECTURES,
    UNKNOWN_REGION,
    application_identity,
    canonical_branch_name,
    canonical_application_url,
    deadline_state,
    is_deadline_soon,
    region_for_prefecture,
    sales_channel_matches,
    stable_store_key,
)
from core.application_site import expand_application_branches
from core.application_status import JST
from core.chain_application_extractors import BatorocoApplicationExtractor
from core.config_manager import ConfigManager
from core.application_notifications import ApplicationNotificationService
from core.web_application_sources import SOURCE_CLASSES, WebApplicationSourceRegistry
from ui.application_dashboard_page import ApplicationDashboardPage
from ui.sources_page import SourcesPage


NOW = datetime(2026, 8, 22, 12, tzinfo=JST)


def row(key, tcg, mode, prefecture, *, state="未応募", end_hours=48, new=True):
    value = {
        "product_id": f"p-{tcg}", "product_name": f"{tcg} 商品", "tcg_key": tcg,
        "site_key": key, "site_name": f"{key}店", "site_url": f"https://example.com/{key}",
        "application_url": f"https://example.com/{key}/apply", "sales_mode": mode,
        "prefecture": prefecture, "region": region_for_prefecture(prefecture),
        "application_state": state, "dashboard_state": state, "period_ended": False,
        "product_category": "CARD", "is_new": new,
        "deadline_soon": end_hours <= DEADLINE_SOON_HOURS,
        "application_end_at": (NOW + timedelta(hours=end_hours)).isoformat(),
    }
    value["store_key"] = stable_store_key(value)
    return value


class RegionAndSalesModeTest(unittest.TestCase):
    def test_all_47_prefectures_map_exactly(self):
        seen = set()
        for expected, prefectures in REGION_PREFECTURES.items():
            for prefecture in prefectures:
                seen.add(prefecture)
                self.assertEqual(expected, region_for_prefecture(prefecture))
        self.assertEqual(47, len(seen))
        self.assertEqual(UNKNOWN_REGION, region_for_prefecture("UNKNOWN"))
        self.assertEqual(UNKNOWN_REGION, region_for_prefecture("新宿"))

    def test_sales_tabs_include_hybrid_in_both_but_unknown_only_all(self):
        expected = {
            "ONLINE": (True, False), "STORE": (False, True),
            "HYBRID": (True, True), "UNKNOWN": (False, False),
        }
        for mode, (online, store) in expected.items():
            self.assertTrue(sales_channel_matches(mode, "all"))
            self.assertEqual(online, sales_channel_matches(mode, "online"))
            self.assertEqual(store, sales_channel_matches(mode, "store"))

    def test_deadline_states(self):
        self.assertEqual("today", deadline_state({"application_end_at": (NOW + timedelta(hours=2)).isoformat()}, now=NOW))
        self.assertEqual("within_24h", deadline_state({"application_end_at": (NOW + timedelta(days=1, hours=23)).isoformat()}, now=NOW + timedelta(days=1)))
        self.assertEqual("within_72h", deadline_state({"application_end_at": (NOW + timedelta(hours=50)).isoformat()}, now=NOW))
        self.assertEqual("expired", deadline_state({"application_end_at": (NOW - timedelta(seconds=1)).isoformat()}, now=NOW))
        self.assertEqual("unknown", deadline_state({}, now=NOW))
        self.assertTrue(is_deadline_soon({"application_end_at": (NOW + timedelta(hours=70)).isoformat()}, now=NOW))


class FilterCompositionTest(unittest.TestCase):
    def setUp(self):
        self.rows = [
            row("tokyo", "pokemon", "STORE", "東京都"),
            row("osaka", "pokemon", "STORE", "大阪府"),
            row("hybrid", "pokemon", "HYBRID", "神奈川県"),
            row("online", "onepiece", "ONLINE", "福岡県"),
            row("db", "dragon_ball_fusion_world", "ONLINE", "UNKNOWN", end_hours=100),
            row("unknown", "pokemon", "UNKNOWN", "UNKNOWN"),
        ]

    def filtered(self, **kwargs):
        return ApplicationDashboard.filter_cached(self.rows, **kwargs)

    def test_store_kanto_pokemon_active(self):
        rows = self.filtered(sales_channel_filter="store", region_filter="関東", tcg_filter="pokemon")
        self.assertEqual({"tokyo", "hybrid"}, {item["site_key"] for item in rows})

    def test_online_onepiece_active(self):
        rows = self.filtered(sales_channel_filter="online", tcg_filter="onepiece")
        self.assertEqual(["online"], [item["site_key"] for item in rows])

    def test_new_and_deadline_filters_compose(self):
        rows = self.filtered(new_only=True, deadline_soon_only=True)
        self.assertNotIn("db", {item["site_key"] for item in rows})

    def test_application_states(self):
        for state in ("未応募", "応募済み", "結果待ち", "当選", "落選"):
            sample = row(state, "pokemon", "STORE", "東京都", state=state)
            self.assertEqual([sample], ApplicationDashboard.filter_cached([sample], state_filter=state))

    def test_favorite_prefecture_and_store_filters(self):
        tokyo_key = self.rows[0]["store_key"]
        by_region = self.filtered(favorites_filter="prefecture", favorite_prefectures={"東京都"})
        by_store = self.filtered(favorites_filter="store", favorite_store_keys={tokyo_key})
        either = self.filtered(favorites_filter="any", favorite_prefectures={"大阪府"},
                               favorite_store_keys={tokyo_key})
        self.assertEqual({"tokyo"}, {item["site_key"] for item in by_region})
        self.assertEqual({"tokyo"}, {item["site_key"] for item in by_store})
        self.assertEqual({"tokyo", "osaka"}, {item["site_key"] for item in either})


class PersistenceAndDataQualityTest(unittest.TestCase):
    def test_favorites_save_reload_and_remove(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = ConfigManager(Path(directory))
            config = manager.load()
            config["application_assistant"]["favorite_prefectures"] = ["東京都", "大阪府"]
            config["application_assistant"]["favorite_stores"] = ["chain|branch|url"]
            manager.save(config)
            loaded = ConfigManager(Path(directory)).load()["application_assistant"]
            self.assertEqual(["東京都", "大阪府"], loaded["favorite_prefectures"])
            self.assertEqual(["chain|branch|url"], loaded["favorite_stores"])
            loaded["favorite_stores"].remove("chain|branch|url")
            config["application_assistant"] = loaded
            manager.save(config)
            self.assertEqual([], manager.load()["application_assistant"]["favorite_stores"])

    def test_parent_page_expands_explicit_branches_only(self):
        site = {
            "site_key": "chain", "name": "チェーン", "application_url": "https://example.com/apply",
            "target_store_details": [
                {"branch": "東京店", "prefecture": "東京都", "city": "千代田区"},
                {"branch": "大阪店", "prefecture": "大阪府", "city": "大阪市"},
            ],
        }
        expanded = expand_application_branches(site)
        self.assertEqual(["東京店", "大阪店"], [item["branch"] for item in expanded])
        self.assertEqual(["東京都", "大阪府"], [item["prefecture"] for item in expanded])

    def test_url_canonicalization_and_identity_dedupe(self):
        left = canonical_application_url("https://EXAMPLE.com/apply/?id=1&utm_source=x#top")
        right = canonical_application_url("https://example.com/apply?id=1")
        self.assertEqual(left, right)
        base = {"tcg_key": "pokemon", "product_name": "商品", "chain": "店", "branch": "本店",
                "application_end_at": "2026-08-23T12:00:00+09:00"}
        self.assertEqual(application_identity({**base, "application_url": left}),
                         application_identity({**base, "application_url": right}))
        self.assertEqual("秋葉原店", canonical_branch_name("card_labo", "カードラボ 秋葉原店"))


class SourceRegistryAndExtractorTest(unittest.TestCase):
    def test_uncapped_registry_has_all_classes_and_priority_candidates(self):
        registry = WebApplicationSourceRegistry()
        report = registry.diagnostics()
        self.assertGreater(report["total_sources"], 50)
        self.assertEqual(set(SOURCE_CLASSES), set(report["by_class"]))
        names = {item["display_name"] for item in registry.sources()}
        for expected in ("カードラボ", "ホビーステーション", "バトロコ", "プレイズ",
                         "お宝創庫", "カードボックス", "TSUTAYA", "ふるいち／古本市場",
                         "ブックオフ／BOOKOFF SUPER BAZAAR", "プレミアムバンダイ"):
            self.assertIn(expected, names)

    def test_chain_extractor_returns_candidate_and_url_delta(self):
        html = '<a href="/news/apply?id=1&utm_source=x">ポケモンカード 抽選販売</a>'
        extractor = BatorocoApplicationExtractor()
        first = extractor.extract_index(html, "https://bato-loco.com/news/")
        self.assertEqual("candidate", first["rows"][0]["verification_status"])
        self.assertFalse(first["rows"][0]["confirmed"])
        second = extractor.extract_index(html, "https://bato-loco.com/news/",
                                         known_urls=first["new_urls"])
        self.assertEqual([], second["new_urls"])


class UserSnsUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_user_ui_hides_account_and_trust_details(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {"POKEYOYA_DATA_ROOT": directory, "POKEYOYA_X_BEARER_TOKEN": ""}, clear=False
        ), patch("ui.sources_page.XMonitoringStatus") as monitor:
            monitor.return_value.summary.return_value = {
                "last_success": "2026-08-22 12:00", "state": "正常",
                "message": "SNS情報監視は補助情報源です",
            }
            monitor.return_value.rows.return_value = [{"username": "secret_account", "trust_level": "OFFICIAL"}]
            page = SourcesPage()
            text = page.x_monitoring_summary.text()
            web_text = page.web_monitoring_summary.text()
            self.assertIn("SNS情報 最終更新", text)
            self.assertNotIn("secret_account", text)
            self.assertNotIn("OFFICIAL", text)
            monitor.return_value.rows.assert_not_called()
            self.assertIn("補助情報ソース", web_text)
            self.assertIn("公式ページで確認できるまで", web_text)
            page.close()

    def test_dashboard_has_sales_tabs_and_store_only_region_tabs(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {"POKEYOYA_DATA_ROOT": directory}, clear=False
        ):
            page = ApplicationDashboardPage()
            self.assertEqual(["all", "online", "store"], [
                page.sales_tabs.tabData(index) for index in range(page.sales_tabs.count())
            ])
            self.assertTrue(page.region_tabs.isHidden())
            page.sales_tabs.setCurrentIndex(2)
            self.app.processEvents()
            self.assertFalse(page.region_tabs.isHidden())
            page.period_timer.stop()
            page.close()


class NotificationFilterV2Test(unittest.TestCase):
    def test_region_favorite_new_deadline_and_hybrid_matching(self):
        settings = {
            "tcg": {"pokemon": True}, "sales_modes": ["STORE"],
            "prefectures": [], "regions": ["関東"], "product_categories": ["CARD"],
            "favorite_store_only": True, "favorite_stores": ["fav"],
            "new_only": True, "deadline_soon_only": True,
        }
        self.assertTrue(ApplicationNotificationService._matches(
            settings, "pokemon", "HYBRID", "東京都", "CARD", region="関東",
            store_key="fav", is_new=True, deadline_soon=True,
        ))
        self.assertFalse(ApplicationNotificationService._matches(
            settings, "pokemon", "HYBRID", "大阪府", "CARD", region="近畿",
            store_key="fav", is_new=True, deadline_soon=True,
        ))


if __name__ == "__main__":
    unittest.main()
