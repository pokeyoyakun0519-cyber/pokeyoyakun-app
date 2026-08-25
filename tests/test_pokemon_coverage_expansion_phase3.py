from __future__ import annotations

import tempfile
import json
from datetime import datetime, timedelta
from pathlib import Path

from core.application_dashboard import ApplicationDashboard
from core.candidate_manager import CandidateManager
from core.product_store import ProductStore
from core.pokemon_restricted_campaigns import (
    JST,
    PokemonRestrictedCampaignMonitor,
)


NOW = datetime(2026, 8, 23, 12, 0, tzinfo=JST)
DEFINITIONS = Path(__file__).resolve().parents[1] / "app" / "resources" / "pokemon_restricted_campaigns.json"


def _campaign_count_at(now: datetime) -> int:
    payload = json.loads(DEFINITIONS.read_text(encoding="utf-8"))
    return sum(
        datetime.fromisoformat(item["application_start_at"]) <= now
        <= datetime.fromisoformat(item["application_end_at"]) + timedelta(days=14)
        for item in payload["campaigns"]
    )


class _RobotsFetcher:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def fetch(self, url: str, **_kwargs):
        self.calls.append(url)
        return {"ok": False, "status": "ROBOTS_BLOCKED", "url": url, "html": ""}

    def diagnostics(self):
        return {"request_count": len(self.calls)}


class _ConfirmedFetcher(_RobotsFetcher):
    def fetch(self, url: str, **_kwargs):
        self.calls.append(url)
        return {
            "ok": True,
            "status": "OK",
            "url": url,
            "html": (
                "<main>ポケモンカード 30th CELEBRATION "
                "プレイヤーズクラブ本人認証済み枠 抽選応募受付期間</main>"
            ),
        }


def _restricted_scan(root: Path):
    monitor = PokemonRestrictedCampaignMonitor(
        root, fetcher=_RobotsFetcher(), now=lambda: NOW,
    )
    return monitor.scan(force=True), monitor.diagnostics


def test_concrete_robots_limited_campaigns_remain_restricted_and_finite():
    with tempfile.TemporaryDirectory() as folder:
        discoveries, diagnostics = _restricted_scan(Path(folder))

    expected = _campaign_count_at(NOW)
    assert len(discoveries) == expected
    assert diagnostics["restricted"] == expected
    assert diagnostics["confirmed"] == 0
    assert all(
        item["hit"]["verification_status"] == "unverified_restricted"
        for item in discoveries
    )
    assert all(item["hit"]["confirmed"] is False for item in discoveries)
    assert all(item["hit"]["official_detail_url"].startswith("https://") for item in discoveries)
    assert {
        (item["hit"]["site_key"], item["hit"]["branch"])
        for item in discoveries
    } == {
        ("pokemon_center_online", "プレイヤーズクラブ本人認証済み枠"),
        ("pokemon_center_online", "プレイヤーズクラブ本人未認証枠"),
        ("fullcomp", "対象店舗"),
        ("sanyodo", "対象店舗"),
        ("hareruya2", "通販"),
        ("hareruya2", "秋葉原タワー店"),
        ("pokeca_club", "通販"),
        ("cardbox", "ブックスジュピター店"),
        ("cardbox", "本の王国大垣店"),
        ("dandan", "BASE店"),
        ("kiddyland", "ららぽーと富士見店"),
    }


def test_official_content_must_contain_every_required_term_to_confirm():
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        monitor = PokemonRestrictedCampaignMonitor(
            root, fetcher=_ConfirmedFetcher(), now=lambda: NOW,
        )
        discoveries = monitor.scan(force=True)

    confirmed = [
        item for item in discoveries
        if item["hit"]["verification_status"] == "confirmed"
    ]
    assert len(confirmed) == 1
    assert confirmed[0]["record"]["product_name"].endswith("30th CELEBRATION BOX")


def test_restricted_rows_reach_product_store_with_warning_only_action():
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        discoveries, _ = _restricted_scan(root)
        merged = CandidateManager(root).merge_application_discoveries(
            discoveries, matcher=lambda _candidate, _record: False,
        )
        assert merged["created"] == _campaign_count_at(NOW)

        dashboard = ApplicationDashboard(ProductStore(root)).build(
            show_ended=True, now=NOW,
        )
        rows = [row for row in dashboard["rows"] if row.get("is_restricted")]
        assert rows
        assert all(row["verification_status"] == "unverified_restricted" for row in rows)
        assert all(row["application_action_enabled"] is True for row in rows)
        assert all(row["application_action_label"] == "公式情報を確認する" for row in rows)
        assert all("応募前に公式ページ" in row["application_action_guidance"] for row in rows)


def test_campaigns_expire_after_normal_fourteen_day_retention():
    stale_now = datetime(2026, 9, 16, 0, 0, tzinfo=JST)
    with tempfile.TemporaryDirectory() as folder:
        monitor = PokemonRestrictedCampaignMonitor(
            Path(folder), fetcher=_RobotsFetcher(), now=lambda: stale_now,
        )
        discoveries = monitor.scan(force=True)

    assert discoveries == []
    total_definitions = len(json.loads(DEFINITIONS.read_text(encoding="utf-8"))["campaigns"])
    assert monitor.diagnostics["outcome_counts"]["STALE"] == total_definitions


def test_future_campaign_is_not_mislabeled_as_active(tmp_path: Path):
    definitions = tmp_path / "campaigns.json"
    definitions.write_text(
        '{"schema_version":1,"campaigns":[{'
        '"id":"future","chain":"geo","store_name":"GEO","branch":"対象店舗",'
        '"product_name":"ポケモンカード 30th CELEBRATION",'
        '"official_url":"https://geo-online.co.jp/news/779",'
        '"application_start_at":"2026-08-31T11:00:00+09:00",'
        '"application_end_at":"2026-09-03T17:59:00+09:00"}]}'
        , encoding="utf-8",
    )
    monitor = PokemonRestrictedCampaignMonitor(
        tmp_path,
        fetcher=_RobotsFetcher(),
        now=lambda: NOW,
        definitions_path=definitions,
    )
    assert monitor.scan(force=True) == []
    assert monitor.diagnostics["outcome_counts"]["FUTURE"] == 1
