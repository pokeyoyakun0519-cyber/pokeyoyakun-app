from __future__ import annotations

from datetime import datetime, timedelta

from core.application_discovery import CANDIDATE, CONFIRMED
from core.application_status import JST
from core.autonomous_source_registry import OfficialSourceCandidateStore
from core.cardchusen_discovery import (
    ADOPTION_STATUS,
    SOURCE_URLS,
    CardchusenDiscovery,
)
from core.nyuka_now_discovery import (
    TIER_B_DISCOVERY,
    discovery_source_diagnostics,
    merge_discovery_candidates,
)
from core.restricted_application import UNVERIFIED_RESTRICTED
from core.production_coverage import build_production_coverage
from core.source_inventory_view import build_source_inventory_view


NOW = datetime(2026, 8, 23, 12, 0, tzinfo=JST)


def _card(
    *,
    product: str = "ストームエメラルダ",
    store: str = "カードボックス船橋駅前店",
    deadline: str = "2026/08/30 23:59",
    destination: str = "https://livepocket.jp/e/example?utm_source=cardchusen",
    method: str = "オンライン抽選 店舗受取",
    branch: str = "船橋駅前店",
    prefecture: str = "千葉県",
) -> str:
    return f"""
    <article class="lottery-card" data-product="{product}" data-store="{store}"
      data-branch="{branch}" data-prefecture="{prefecture}"
      data-deadline="{deadline}" data-application-type="{method}">
      <span class="product-name">{product}</span>
      <span class="shop-name">{store}</span>
      <span class="deadline">締切 {deadline}</span>
      <span class="application-type">{method}</span>
      <a href="{destination}">抽選に応募する</a>
    </article>
    """


def _sensor() -> CardchusenDiscovery:
    return CardchusenDiscovery(now=lambda: NOW)


def test_parser_extracts_concrete_candidate_without_confirming():
    rows = _sensor().parse_listing(_card(), SOURCE_URLS["pokemon"])
    assert len(rows) == 1
    row = rows[0]
    assert row["tcg_key"] == "pokemon"
    assert row["product_name"] == "ストームエメラルダ"
    assert row["store_name"] == "カードボックス船橋駅前店"
    assert row["branch"] == "船橋駅前店"
    assert row["prefecture"] == "千葉県"
    assert row["application_end_at"] == "2026-08-30T23:59:00+09:00"
    assert row["application_url"] == "https://livepocket.jp/e/example"
    assert row["trust_tier"] == TIER_B_DISCOVERY
    assert row["verification_status"] == CANDIDATE
    assert row["confirmed"] is False


def test_four_required_tcg_pages_are_classified_from_bounded_source_paths():
    for key in ("pokemon", "onepiece", "yugioh", "dragon_ball_fusion_world"):
        rows = _sensor().parse_listing(_card(product=f"{key} test product"), SOURCE_URLS[key])
        assert rows[0]["tcg_key"] == key


def test_date_without_time_uses_end_of_day_but_marks_time_unconfirmed():
    row = _sensor().parse_listing(
        _card(deadline="8月30日"), SOURCE_URLS["pokemon"],
    )[0]
    assert row["application_end_at"] == "2026-08-30T23:59:59+09:00"
    assert row["application_end_time_confirmed"] is False


def test_application_provider_and_x_links_are_kept_separate():
    provider = _sensor().parse_listing(
        _card(destination="https://shoplottery.e-starbox.com/apply/123"),
        SOURCE_URLS["pokemon"],
    )[0]
    assert provider["application_url_candidates"][0]["candidate_type"] == "APPLICATION_PROVIDER"

    x_only = _sensor().parse_listing(
        _card(destination="https://x.com/example/status/123"),
        SOURCE_URLS["pokemon"],
    )[0]
    assert x_only["application_url"] == ""
    assert x_only["x_url_candidates"][0]["candidate_type"] == "X_API_ONLY"
    promoted = _sensor().promote(
        x_only, official_url="https://x.com/example/status/123",
    )
    assert promoted["verification_status"] == CANDIDATE
    assert promoted["verification_error"] == "X_API_REQUIRED"


def test_ssrf_like_destination_is_rejected_as_an_application_candidate():
    row = _sensor().parse_listing(
        _card(destination="https://127.0.0.1/private"), SOURCE_URLS["pokemon"],
    )[0]
    assert row["application_url"] == ""
    assert row["application_url_candidates"] == []


def test_same_application_dedupes_across_discovery_sources_and_keeps_evidence():
    first = _sensor().parse_listing(_card(), SOURCE_URLS["pokemon"])[0]
    second = dict(first)
    second["source_article_url"] = "https://nyuka-now.com/archives/999"
    second["source_url"] = second["source_article_url"]
    second["evidence_sources"] = [second["source_article_url"]]
    second["evidence"] = [{
        "source_type": "DISCOVERY_SOURCE",
        "source_url": second["source_article_url"],
        "observed_at": NOW.isoformat(),
        "trust": 60,
        "verification_status": CANDIDATE,
    }]
    merged = merge_discovery_candidates([first, second])
    assert len(merged) == 1
    assert len(merged[0]["evidence_sources"]) == 2


def test_official_document_can_promote_but_source_alone_never_does():
    deadline = datetime.now(JST) + timedelta(days=7)
    deadline_text = deadline.strftime("%Y/%m/%d %H:%M")
    candidate = _sensor().parse_listing(
        _card(deadline=deadline_text), SOURCE_URLS["pokemon"],
    )[0]
    assert _sensor().promote(candidate, official_url=candidate["application_url"])[
        "verification_status"
    ] == CANDIDATE
    official = _sensor().promote(
        candidate,
        official_url=candidate["application_url"],
        official_html=(
            "<article>ポケモンカード ストームエメラルダ "
            f"オンライン抽選受付 {deadline_text}</article>"
        ),
    )
    assert official["verification_status"] == CONFIRMED
    assert official["confirmed"] is True


def test_robots_failure_can_only_promote_concrete_candidate_to_restricted():
    candidate = _sensor().parse_listing(_card(), SOURCE_URLS["pokemon"])[0]
    restricted = _sensor().promote(
        candidate,
        official_url=candidate["application_url"],
        failure_status="ROBOTS_BLOCKED",
    )
    assert restricted["verification_status"] == UNVERIFIED_RESTRICTED
    assert restricted["confirmed"] is False
    assert restricted["discovery_source_url"] == SOURCE_URLS["pokemon"]


def test_stale_listing_is_excluded_and_unknown_store_is_quarantined():
    sensor = _sensor()
    assert sensor.parse_listing(
        _card(deadline="2026/08/08 23:59"), SOURCE_URLS["pokemon"],
    ) == []
    unknown = sensor.parse_listing(
        _card(store="新規カードショップ未知店", branch="", prefecture=""),
        SOURCE_URLS["pokemon"],
    )[0]
    assert unknown["chain"] == ""
    assert unknown["prefecture"] == "UNKNOWN"
    assert unknown["store_registry_status"] == "quarantine"
    assert unknown["discovered_store_candidate"] is True


def test_terms_policy_registers_source_but_prevents_live_polling(tmp_path):
    sensor = _sensor()
    assert sensor.poll() == []
    diagnostics = sensor.diagnostics()
    assert diagnostics["adoption_status"] == ADOPTION_STATUS
    assert diagnostics["auto_enabled"] is False
    assert diagnostics["prevented_fetch_count"] == 1

    tiers = discovery_source_diagnostics()
    source = next(item for item in tiers["sources"] if item["key"] == "cardchusen")
    assert source["trust_tier"] == TIER_B_DISCOVERY
    assert source["auto_enabled"] is False
    registry = OfficialSourceCandidateStore(tmp_path)
    bundled = next(item for item in registry.records if item["id"] == "cardchusen")
    assert bundled["source_state"] == "TERMS_RESTRICTED"

    coverage = build_production_coverage(
        [], autonomous_registry=registry, now=NOW,
    )
    view = build_source_inventory_view(coverage)
    rows = [row for row in view["rows"] if row["chain"] == "cardchusen"]
    assert rows
    assert {row["state"] for row in rows} == {"TERMS_RESTRICTED"}
    assert {row["discovered_from"] for row in rows} == {"カード抽選まとめ"}
    assert all(row["dashboard_listed"] is False for row in rows)
