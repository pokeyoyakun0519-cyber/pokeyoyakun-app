import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path

from core.nationwide_web_monitor import NationwideWebApplicationMonitor
from core.retail_search_manager import _ascii_safe_url


JST = timezone(timedelta(hours=9))


class _Registry:
    def __init__(self):
        self.records = {
            "pokemon": [
                {
                    "chain": "sample", "display_name": "Sample", "source_class": "WEB_DIRECT",
                    "official_url": "https://example.test/news/", "branch_count": 3,
                    "extractor": "safe_public_html",
                },
                {
                    "chain": "app_only", "source_class": "APP_REQUIRED",
                    "official_url": "https://app.test/", "branch_count": 2, "extractor": "none",
                },
                {
                    "chain": "sns_only", "source_class": "SNS_ONLY",
                    "official_url": "https://sns.test/", "branch_count": 4, "extractor": "none",
                },
            ],
            "onepiece": [
                {
                    "chain": "sample", "display_name": "Sample", "source_class": "WEB_DIRECT",
                    "official_url": "https://example.test/news/", "branch_count": 3,
                    "extractor": "safe_public_html",
                }
            ],
            "dragon_ball_fusion_world": [],
        }

    def sources(self, tcg):
        return [dict(item) for item in self.records.get(tcg, [])]


class Test5NationwideWebMonitorTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.state_path = Path(self.temporary.name) / "state.json"
        self.fetches = []

    def tearDown(self):
        self.temporary.cleanup()

    def _fetch(self, url):
        self.fetches.append(url)
        return {
            "ok": True,
            "status": "HTTP 200",
            "html": (
                '<a href="/lottery/1">ポケモンカード 新商品 WEB抽選販売 応募受付</a>'
            ),
        }

    def _monitor(self):
        return NationwideWebApplicationMonitor(
            self._fetch,
            registry=_Registry(),
            robots_allowed=lambda _url: True,
            state_path=self.state_path,
            now=lambda: datetime(2026, 8, 22, 12, 0, tzinfo=JST),
        )

    def test_monitorable_inventory_reaches_fetch_and_candidate(self):
        monitor = self._monitor()
        discoveries = monitor.scan({"pokemon", "onepiece"})
        self.assertEqual(["https://example.test/news/"], self.fetches)
        self.assertEqual(1, len(discoveries))
        self.assertEqual("candidate", discoveries[0]["hit"]["verification_status"])
        self.assertFalse(discoveries[0]["hit"]["confirmed"])
        self.assertEqual(1, monitor.diagnostics["checked_sources"])
        self.assertEqual(1, monitor.diagnostics["application_candidates"])

    def test_non_ascii_official_url_is_safely_percent_encoded(self):
        self.assertEqual(
            "https://seagullonline.jp/category/%E4%BA%88%E7%B4%84%E6%83%85%E5%A0%B1/",
            _ascii_safe_url("https://seagullonline.jp/category/予約情報/"),
        )

    def test_app_and_sns_only_are_not_fetched(self):
        monitor = self._monitor()
        monitor.scan({"pokemon"})
        statuses = monitor.diagnostics["status_counts"]
        self.assertEqual(1, statuses["APP_REQUIRED"])
        self.assertEqual(1, statuses["SNS_ONLY"])
        self.assertNotIn("https://app.test/", self.fetches)
        self.assertNotIn("https://sns.test/", self.fetches)

    def test_parent_page_expands_to_target_branches(self):
        monitor = self._monitor()
        monitor.scan({"pokemon"})
        pokemon = monitor.diagnostics["by_tcg"]["pokemon"]
        self.assertEqual(3, pokemon["actual_checked_branch_count"])
        self.assertEqual(3, pokemon["monitorable_branch_count"])
        self.assertEqual(100.0, pokemon["coverage_percent"])

    def test_diagnostics_are_saved_and_ttl_prevents_duplicate_fetch(self):
        first = self._monitor()
        first.scan({"pokemon"})
        self.fetches.clear()
        second = self._monitor()
        cached = second.scan({"pokemon"})
        self.assertEqual([], self.fetches)
        self.assertTrue(second.diagnostics["cache_hit"])
        self.assertEqual(1, len(cached))
        loaded = NationwideWebApplicationMonitor.load_saved_diagnostics(self.state_path)
        self.assertEqual(100.0, loaded["coverage_percent"])

    def test_external_adapter_can_confirm_without_generic_fetch(self):
        registry = _Registry()
        registry.records["pokemon"] = [{
            "chain": "card_labo", "display_name": "カードラボ",
            "source_class": "WEB_DIRECT", "official_url": "https://www.c-labo.jp/",
            "branch_count": 5, "extractor": "card_labo",
        }]
        monitor = NationwideWebApplicationMonitor(
            self._fetch, registry=registry, robots_allowed=lambda _url: True,
            state_path=self.state_path,
            now=lambda: datetime(2026, 8, 22, 12, 0, tzinfo=JST),
        )
        discovery = {
            "record": {"article_url": "https://www.c-labo.jp/news/1", "tcg_key": "pokemon"},
            "hit": {"site_key": "card_labo", "verification_status": "confirmed"},
        }
        rows = monitor.scan({"pokemon"}, external_results={"card_labo": {
            "checked": True, "success": True, "discoveries": [discovery],
        }})
        self.assertEqual([], self.fetches)
        self.assertEqual(1, len(rows))
        self.assertEqual(1, monitor.diagnostics["confirmed"])
        self.assertEqual(5, monitor.diagnostics["actual_checked_branch_count"])

    def test_robots_denial_is_access_restricted(self):
        monitor = NationwideWebApplicationMonitor(
            self._fetch, registry=_Registry(), robots_allowed=lambda _url: False,
            state_path=self.state_path,
            now=lambda: datetime(2026, 8, 22, 12, 0, tzinfo=JST),
        )
        monitor.scan({"onepiece"})
        self.assertEqual([], self.fetches)
        self.assertEqual(1, monitor.diagnostics["status_counts"]["ACCESS_RESTRICTED"])

    def test_bandai_parent_results_are_assigned_to_matching_tcg(self):
        registry = _Registry()
        registry.records = {
            "pokemon": [],
            "onepiece": [{
                "chain": "bandai_official_shop", "source_class": "STORE_DIRECT",
                "official_url": "https://bandainamco-am.co.jp/official_shop/onepiece-cardgame/index.html",
                "branch_count": 20, "extractor": "none",
            }],
            "dragon_ball_fusion_world": [{
                "chain": "bandai_official_shop", "source_class": "STORE_DIRECT",
                "official_url": "https://bandainamco-am.co.jp/official_shop/dbs-cardgame/index.html",
                "branch_count": 2, "extractor": "none",
            }],
        }
        external = []
        for tcg, suffix in (("onepiece", "op"), ("dragon_ball_fusion_world", "db")):
            external.append({
                "record": {"article_url": f"https://parks.example/{suffix}", "tcg_key": tcg},
                "hit": {"site_key": "bandai_official_shop", "verification_status": "confirmed"},
            })
        monitor = NationwideWebApplicationMonitor(
            self._fetch, registry=registry, state_path=self.state_path,
            now=lambda: datetime(2026, 8, 22, 12, 0, tzinfo=JST),
        )
        monitor.scan(
            {"onepiece", "dragon_ball_fusion_world"},
            external_results={"bandai_official_shop": {
                "checked": True, "success": True, "discoveries": external,
            }},
        )
        by_tcg = monitor.diagnostics["by_tcg"]
        self.assertEqual(1, by_tcg["onepiece"]["confirmed_count"])
        self.assertEqual(1, by_tcg["dragon_ball_fusion_world"]["confirmed_count"])
        self.assertEqual(20, by_tcg["onepiece"]["actual_checked_branch_count"])
        self.assertEqual(2, by_tcg["dragon_ball_fusion_world"]["actual_checked_branch_count"])


if __name__ == "__main__":
    unittest.main()
