from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "app"))

from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from core.application_action import application_action
from core.application_dashboard import ApplicationDashboard
from core.application_notifications import ApplicationNotificationService
from core.application_status import JST
from core.autonomous_source_registry import OfficialSourceCandidateStore
from core.autonomous_web_discovery import AutonomousApplicationSourceDiscovery
from core.candidate_manager import CandidateManager
from core.config_manager import ConfigManager
from core.product_store import ProductStore
from core.restricted_application import UNVERIFIED_RESTRICTED, restrict_discovery
from core.source_inventory_view import build_source_inventory_view
from ui.application_dashboard_page import ApplicationRow


NOW = datetime(2026, 8, 23, 12, tzinfo=JST)


class _Fetcher:
    def __init__(self, article_url: str, official_url: str) -> None:
        self.article_url = article_url
        self.official_url = official_url

    def fetch(self, url: str, **_kwargs):
        if url == self.article_url:
            return {"ok": True, "status": 200, "url": url, "html": (
                '<article><h1>ポケモンカード「新弾テスト」抽選販売</h1>'
                '<p>応募受付 2026年8月23日から2026年8月30日まで</p>'
                f'<a href="{self.official_url}">Joshin公式店舗 応募情報</a></article>'
            )}
        return {"ok": False, "status": "ROBOTS_BLOCKED", "url": url, "html": ""}

    def mark_parsed(self, _url):
        return None

    def diagnostics(self):
        return {}


def _seed(path: Path, url: str) -> Path:
    path.write_text(json.dumps({"schema_version": 1, "seeds": [{
        "id": "trusted_discovery", "name": "信頼Discovery", "base_url": url,
        "official_domains": ["discovery.example"], "seed_type": "DISCOVERY",
        "trust_tier": "TIER_B_DISCOVERY", "supported_tcg": ["pokemon"],
        "discovery_paths": [], "enabled": True,
    }]}), encoding="utf-8")
    return path


def _site(status: str, *, detected_at: str | None = None, deadline=True):
    value = {
        "site_key": "joshin", "name": "Joshin", "url": "https://joshinweb.jp/lottery/1",
        "application_url": "https://joshinweb.jp/lottery/1",
        "official_detail_url": "https://joshinweb.jp/lottery/1",
        "status": "抽選情報候補", "application_method": "抽選応募",
        "verification_status": status, "confirmed": status == "confirmed",
        "detected_at": detected_at or NOW.isoformat(), "prefecture": "UNKNOWN",
        "sales_mode": "UNKNOWN", "evidence": [{"source_type": "GENERAL_INFORMATION"}],
    }
    if deadline:
        value["application_end_at"] = (NOW + timedelta(days=5)).isoformat()
    return value


class RestrictedApplicationsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = ProductStore(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def _dashboard(self, sites):
        self.store._save_product_file([{
            "id": "p1", "name": "新弾テスト", "tcg_key": "pokemon", "sites": sites,
        }])
        return ApplicationDashboard(self.store, ConfigManager(self.root)).build(
            now=NOW, show_ended=True
        )

    def test_a_restricted_candidate_is_visible_with_text_warning(self):
        result = self._dashboard([_site(UNVERIFIED_RESTRICTED)])
        self.assertEqual(1, len(result["rows"]))
        row = result["rows"][0]
        self.assertTrue(row["is_restricted"])
        card = ApplicationRow(row, self.store, lambda: None, lambda _row: None)
        text = " ".join(label.text() for label in card.findChildren(QLabel))
        self.assertIn("⚠ 要公式確認", text)
        self.assertIn("自動確認できない情報", text)
        card.close()

    def test_b_official_candidate_url_uses_enabled_check_action(self):
        row = {**_site(UNVERIFIED_RESTRICTED), "is_candidate": True, "is_restricted": True}
        action = application_action(row)
        self.assertEqual("公式情報を確認する", action["application_action_label"])
        self.assertTrue(action["application_action_enabled"])

    def test_restricted_action_is_generic_for_four_requested_chains(self):
        urls = {
            "joshin": "https://joshinweb.jp/lottery/1",
            "biccamera": "https://www.biccamera.com/bc/c/sale/special/lottery/",
            "rakuten_books": "https://books.rakuten.co.jp/event/game/pokemon-card/",
            "dragon_star": "https://www.dragonstar.co.jp/news/lottery/",
        }
        for chain, url in urls.items():
            with self.subTest(chain=chain):
                row = {**_site(UNVERIFIED_RESTRICTED), "site_key": chain,
                       "official_detail_url": url, "is_candidate": True,
                       "is_restricted": True}
                action = application_action(row)
                self.assertEqual("公式情報を確認する", action["application_action_label"])
                self.assertTrue(action["application_action_enabled"])

    def test_c_discovery_only_url_is_marked_non_official(self):
        row = {**_site(UNVERIFIED_RESTRICTED), "is_candidate": True, "is_restricted": True,
               "official_detail_url": "", "application_url": "",
               "discovery_source_url": "https://nyuka-now.com/article/123",
               "url": "https://nyuka-now.com/article/123"}
        action = application_action(row)
        self.assertEqual("情報元を確認する", action["application_action_label"])
        self.assertIn("公式情報ではありません", action["application_action_guidance"])
        self.assertTrue(action["application_action_enabled"])

    def test_d_restricted_is_promoted_to_confirmed_without_duplicate(self):
        manager = CandidateManager(self.root)
        record = {"source_id": "test", "source_name": "Joshin", "article_url":
                  "https://joshinweb.jp/lottery/1", "product_name": "新弾テスト",
                  "tcg_key": "pokemon"}
        manager.merge_application_discoveries(
            [{"record": record, "hit": _site(UNVERIFIED_RESTRICTED)}],
            matcher=lambda _candidate, _record: False,
        )
        candidate = manager.load_candidates()[0]
        confirmed = _site("confirmed")
        confirmed["status"] = "抽選受付中"
        manager.merge_application_discoveries(
            [{"record": record, "hit": confirmed}],
            matcher=lambda item, _record: item["id"] == candidate["id"],
        )
        products = self.store._load_product_file()
        self.assertEqual(1, len(products[0]["sites"]))
        self.assertEqual("confirmed", products[0]["sites"][0]["verification_status"])

    def test_e_old_unknown_deadline_restricted_is_stale(self):
        old = (NOW - timedelta(days=15, seconds=1)).isoformat()
        result = self._dashboard([_site(UNVERIFIED_RESTRICTED, detected_at=old, deadline=False)])
        self.assertEqual([], result["rows"])
        self.assertEqual(1, result["diagnostics"]["excluded_stale_unknown"])

    def test_f_confirmed_has_no_warning(self):
        row = self._dashboard([_site("confirmed")])["rows"][0]
        card = ApplicationRow(row, self.store, lambda: None, lambda _row: None)
        text = " ".join(label.text() for label in card.findChildren(QLabel))
        self.assertIn("✅ 公式確認済み", text)
        self.assertNotIn("自動確認できない情報", text)
        card.close()

    def test_g_counts_and_notifications_are_separate(self):
        result = self._dashboard([_site("confirmed"), {
            **_site(UNVERIFIED_RESTRICTED), "site_key": "biccamera",
            "name": "ビックカメラ", "url": "https://biccamera.com/lottery/1",
            "application_url": "https://biccamera.com/lottery/1",
            "sales_mode": "ONLINE",
        }])
        self.assertEqual({"confirmed": 1, "restricted": 1}, result["verification_counts"])
        events = ApplicationNotificationService(ConfigManager(self.root)).collect(
            self.store.load_products(), now=NOW
        )
        restricted = next(event for event in events if event["verification_status"] == UNVERIFIED_RESTRICTED)
        self.assertEqual("⚠ 要公式確認", restricted["verification_label"])

    def test_trusted_discovery_plus_robots_creates_restricted_not_confirmed(self):
        article = "https://discovery.example/article"
        official = "https://joshinweb.jp/lottery/1"
        registry = OfficialSourceCandidateStore(self.root, _seed(self.root / "seeds.json", article))
        engine = AutonomousApplicationSourceDiscovery(
            self.root, registry=registry, fetcher=_Fetcher(article, official),
            max_depth=1, max_urls_per_source=3,
        )
        result = engine.run({"pokemon"})
        self.assertEqual(1, len(result["discoveries"]))
        hit = result["discoveries"][0]["hit"]
        self.assertEqual(UNVERIFIED_RESTRICTED, hit["verification_status"])
        self.assertFalse(hit["confirmed"])
        self.assertEqual(official, hit["official_detail_url"])

    def test_unknown_rumor_is_not_admitted_as_restricted(self):
        discovery = {
            "record": {"product_name": "噂の商品", "source_name": "出所不明"},
            "hit": {"name": "不明店", "application_type": "LOTTERY",
                    "verification_status": "candidate", "evidence": []},
        }
        result = restrict_discovery(
            discovery, official_url="https://joshinweb.jp/lottery/rumor",
            reason="ROBOTS_BLOCKED",
        )
        self.assertEqual("candidate", result["hit"]["verification_status"])

    def test_source_inventory_keeps_restricted_separate_but_dashboard_listed(self):
        view = build_source_inventory_view({
            "inventory": [{"tcg": "pokemon", "chain": "joshin", "state": "ROBOTS_BLOCKED"}],
            "applications": [{
                "tcg": "pokemon", "chain": "joshin", "branch": "Web",
                "state": "CURRENT_APPLICATION",
                "verification_status": UNVERIFIED_RESTRICTED,
            }],
        })
        row = view["rows"][0]
        self.assertEqual("UNVERIFIED_RESTRICTED", row["state"])
        self.assertEqual("要公式確認", row["status_label"])
        self.assertTrue(row["dashboard_listed"])
        self.assertFalse(row["verified_official"])
        self.assertEqual(1, view["summary"]["current"])
        self.assertEqual(1, view["summary"]["restricted"])


if __name__ == "__main__":
    unittest.main()
