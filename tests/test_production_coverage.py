from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from core.application_status import JST
from core.autonomous_source_registry import OfficialSourceCandidateStore
from core.production_coverage import PREFECTURES, build_production_coverage
from core.web_application_sources import PRIORITY_TCG, WebApplicationSourceRegistry


def _discovery(chain: str, end: str, *, prefecture: str = "東京都", tcg: str = "pokemon"):
    return {
        "record": {
            "tcg_key": tcg, "source_id": chain, "product_name": "商品A",
            "article_url": f"https://{chain}.example/news/1",
        },
        "hit": {
            "tcg_key": tcg, "site_key": chain, "branch": "本店",
            "prefecture": prefecture,
            "application_url": f"https://{chain}.example/apply/1",
            "application_end_at": end, "verification_status": "confirmed",
        },
    }


def test_inventory_covers_all_supported_tcg_and_47_prefectures():
    report = build_production_coverage([], now=datetime(2026, 8, 23, tzinfo=JST))
    assert set(report["by_tcg"]) == set(PRIORITY_TCG)
    assert set(report["by_prefecture"]) == set(PREFECTURES)
    assert len(report["by_prefecture"]) == 47


def test_active_and_recently_ended_are_separate_and_old_is_excluded():
    report = build_production_coverage([
        _discovery("active", "2026-08-30T23:59:59+09:00"),
        _discovery("recent", "2026-08-18T23:59:59+09:00", prefecture="大阪府"),
        _discovery("old", "2026-08-01T23:59:59+09:00"),
    ], now=datetime(2026, 8, 23, tzinfo=JST))
    assert report["totals"]["active_branch_count"] == 1
    assert report["totals"]["recently_ended_branch_count"] == 1
    assert report["totals"]["active_plus_recently_ended_branch_count"] == 2
    assert report["by_prefecture"]["東京都"]["active"] == 1
    assert report["by_prefecture"]["大阪府"]["recently_ended"] == 1


def test_candidate_is_never_counted_as_application():
    item = _discovery("candidate", "2026-08-30T23:59:59+09:00")
    item["hit"]["verification_status"] = "candidate"
    report = build_production_coverage([item], now=datetime(2026, 8, 23, tzinfo=JST))
    assert report["totals"]["active_plus_recently_ended_branch_count"] == 0


def test_branch_specific_bandai_keys_count_as_one_chain():
    first = _discovery("bandai_official_shop_aaaaaaaaaaaa", "2026-08-18T23:59:59+09:00", tcg="onepiece")
    second = _discovery("bandai_official_shop_bbbbbbbbbbbb", "2026-08-18T23:59:59+09:00", tcg="onepiece")
    second["hit"]["branch"] = "2号店"
    report = build_production_coverage(
        [first, second], now=datetime(2026, 8, 23, tzinfo=JST)
    )
    value = report["by_tcg"]["onepiece"]
    assert value["recently_ended_chain_count"] == 1
    assert value["recently_ended_branch_count"] == 2


def test_blocked_source_keeps_official_alternative_path_in_inventory():
    registry = WebApplicationSourceRegistry()
    diagnostics = {"sources": [{
        "chain": "rakuten", "source": "https://books.rakuten.co.jp/",
        "monitor_type": "WEB_DIRECT", "status": "ACCESS_RESTRICTED",
        "error_code": "ROBOTS_DISALLOWED", "last_check": "2026-08-23T00:00:00+09:00",
    }]}
    report = build_production_coverage(
        [], registry=registry, nationwide_diagnostics=diagnostics,
        now=datetime(2026, 8, 23, tzinfo=JST),
    )
    rows = [row for row in report["inventory"] if row["chain"] == "rakuten"]
    assert rows
    assert all(row["state"] == "ROBOTS_BLOCKED" for row in rows)
    assert any(
        path["url"] == "https://books.rakuten.co.jp/event/game/card/entry/"
        for row in rows for path in row["official_alternative_paths"]
    )


def test_verified_official_index_can_remain_monitorable_between_campaigns(tmp_path: Path):
    seeds = tmp_path / "seeds.json"
    seeds.write_text('{"seeds": []}', encoding="utf-8")
    registry = OfficialSourceCandidateStore(tmp_path, seeds)
    candidate = registry.discover(
        name="公式ニュース", url="https://official.example/news/",
        source_url="https://manufacturer.example/shop/", provenance="verified_official_link",
        trust_tier="TIER_A_OFFICIAL", supported_tcg=["pokemon"],
    )
    registry.begin_verification(candidate["id"])
    updated = registry.complete_verification(candidate["id"], {
        "official_provenance": True, "https": True, "robots_allowed": True,
        "fetch_success": True, "parser_success": True, "redirect_safe": True,
        "tcg_confidence": 0.0, "application_relevance": 0.0,
        "source_monitorable": True,
    })
    assert updated["source_state"] == "MONITORABLE"
    assert updated["enabled"] is True
