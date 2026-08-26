from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from core.discovery_infrastructure import DiscoveryInfrastructure
from core.x_recent_search import XRecentSearch


ROOT = Path(__file__).resolve().parents[1]
JST = timezone(timedelta(hours=9))


def test_official_x_registry_has_verification_metadata():
    accounts = DiscoveryInfrastructure(ROOT).official_x_accounts()
    required = {
        "chain", "branch", "account_id", "screen_name", "official_source_url",
        "verification_status", "last_checked_at",
    }
    assert len(accounts) == 22
    assert all(required <= set(item) for item in accounts)
    assert all(item["screen_name"] == item["username"] for item in accounts)
    assert {item["tcg"] for item in accounts} >= {"yugioh", "gundam"}
    assert all(
        item["official_source_url"]
        for item in accounts if item["verification_status"] == "VERIFIED_OFFICIAL"
    )


def test_x_no_token_is_gracefully_disabled_without_secret_output(monkeypatch):
    monkeypatch.delenv("POKEYOYA_X_BEARER_TOKEN", raising=False)
    result = DiscoveryInfrastructure.x_source_status()
    assert result["source_status"] == "DISABLED_NO_CREDENTIAL"
    assert result["execution_scope"] == "ADMIN_SERVER_SIDE_ONLY"
    assert "token" not in json.dumps(result).casefold()
    client_result = XRecentSearch(ROOT).search("pokemon")
    assert client_result["status"] == "disabled"
    assert client_result["source_status"] == "DISABLED_NO_CREDENTIAL"


def test_mock_token_only_enables_server_side_adapter_metadata():
    result = DiscoveryInfrastructure.x_source_status("mock-token-value")
    assert result == {
        "source_type": "OFFICIAL_X", "source_status": "ENABLED_SERVER_SIDE",
        "execution_scope": "ADMIN_SERVER_SIDE_ONLY", "web_scraping": False,
    }
    assert "mock-token-value" not in repr(result)


def test_frozen_user_runtime_never_uses_injected_x_token(monkeypatch):
    monkeypatch.setattr("core.x_recent_search.sys.frozen", True, raising=False)
    monkeypatch.setenv("POKEYOYA_X_BEARER_TOKEN", "must-not-be-used")
    monkeypatch.delenv("POKEYOYA_DISCOVERY_EXECUTION_SCOPE", raising=False)
    result = XRecentSearch(ROOT).search("pokemon")
    assert result["status"] == "disabled"
    assert result["source_status"] == "DISABLED_CLIENT_RUNTIME"
    assert DiscoveryInfrastructure.x_source_status()["source_status"] == "DISABLED_CLIENT_RUNTIME"


def test_app_line_and_in_store_sources_remain_candidates():
    infrastructure = DiscoveryInfrastructure(ROOT)
    sources = infrastructure.sources()
    assert sum(item["source_type"] == "OFFICIAL_APP_ONLY" for item in sources) == 3
    assert sum(item["source_type"] == "OFFICIAL_LINE_ONLY" for item in sources) == 2
    assert sum(item["source_type"] == "IN_STORE_QR" for item in sources) == 1
    for source_id in ("bookoff_app", "tsutaya_line", "tsutaya_store_qr"):
        item = infrastructure.closed_source_candidate(
            source_id, {"product_text": "商品", "missing_fields": ["受付終了"]},
        )
        assert item["verification_status"] == "candidate"
        assert item["confirmed"] is False
        assert item["ui_hint"]


def test_commercial_facility_source_maps_to_store_candidate_without_confirming():
    infrastructure = DiscoveryInfrastructure(ROOT)
    assert sum(
        item["source_type"] == "COMMERCIAL_FACILITY" for item in infrastructure.sources()
    ) == 5
    candidate = infrastructure.facility_to_store_candidate({
        "facility_name": "公式モール", "store_name": "カード店", "branch_name": "本店",
        "tcg": "pokemon", "product_text": "商品", "source_url": "https://mall.example/news",
        "application_start_at": "2026-08-28T10:00:00+09:00",
        "application_end_at": "2026-08-30T20:00:00+09:00",
    })
    assert candidate["store_text"] == "カード店"
    assert candidate["missing_fields"] == []
    assert candidate["confirmed"] is False


def test_release_calendar_and_product_first_queries_use_release_window_only():
    infrastructure = DiscoveryInfrastructure(ROOT)
    calendar = infrastructure.release_calendar()
    assert {item["tcg"] for item in calendar["tcgs"]} == {
        "pokemon", "one-piece", "yugioh", "dragon-ball-fusion-world",
        "gundam", "union-arena",
    }
    triggers = infrastructure.release_triggers(datetime(2026, 8, 26, 12, tzinfo=JST))
    assert len(triggers) == 5
    queries = infrastructure.product_first_queries(
        datetime(2026, 8, 26, 12, tzinfo=JST), ["TSUTAYA"],
    )
    assert len(queries) == 20
    assert all(item["how_discovered"] == "PRODUCT_REVERSE_SEARCH" for item in queries)
    assert all("application_start_at" not in item for item in queries)


def test_source_priority_uses_conversion_current_and_duplicate_rate():
    strong = DiscoveryInfrastructure.source_priority(
        "OFFICIAL_APPLICATION_PAGE",
        {"candidate_discovered_count": 10, "confirmed_promoted_count": 8,
         "active_upcoming_count": 6, "duplicate_rate": 0},
    )
    weak = DiscoveryInfrastructure.source_priority(
        "TIER_C_REFERENCE",
        {"candidate_discovered_count": 10, "confirmed_promoted_count": 0,
         "active_upcoming_count": 0, "duplicate_rate": 0.8},
    )
    assert strong > weak


def test_backlog_scheduler_prioritizes_due_release_window_without_over_polling():
    infrastructure = DiscoveryInfrastructure(ROOT)
    candidates = [{
        "candidate_shop": "A", "status": "STILL_CANDIDATE",
        "source_type": "OFFICIAL_APP_ONLY", "last_checked_at": "2026-08-26T00:00:00+09:00",
        "next_check_at": "2026-08-29T00:00:00+09:00",
        "products_checked": ["30th CELEBRATION"],
    }]
    planned = infrastructure.prioritized_backlog(
        candidates, {}, datetime(2026, 8, 29, 12, tzinfo=JST),
    )
    assert planned[0]["rediscovery_due"] is True
    assert planned[0]["release_window_priority"] is True
    assert planned[0]["discovery_priority_score"] > 20


def test_candidate_aging_preserves_record_and_marks_stale():
    item = {"id": "keep", "status": "STILL_CANDIDATE", "last_checked_at": "2026-07-01T00:00:00+09:00"}
    aged = DiscoveryInfrastructure.age_candidate(
        item, datetime(2026, 8, 26, tzinfo=JST), stale_after_days=30,
    )
    assert aged["id"] == "keep"
    assert aged["status"] == "STALE_CANDIDATE"
    assert item["status"] == "STILL_CANDIDATE"


def test_discovery_method_analytics_reports_conversion():
    analytics = DiscoveryInfrastructure.method_analytics([
        {"how_discovered": "OFFICIAL_X", "status": "STILL_CANDIDATE"},
        {"how_discovered": "OFFICIAL_X", "status": "PROMOTED_CONFIRMED", "application_status": "ACTIVE"},
        {"how_discovered": "OFFICIAL_APP", "status": "STILL_CANDIDATE"},
    ])
    assert analytics["OFFICIAL_X"] == {
        "candidates": 2, "confirmed": 1, "active_upcoming": 1, "conversion_rate": 0.5,
    }
    assert analytics["OFFICIAL_APP"]["conversion_rate"] == 0


def test_current_backlog_analytics_includes_historical_promotion():
    payload = json.loads(
        (ROOT / "app" / "resources" / "coverage_candidate_backlog.json").read_text(
            encoding="utf-8"
        )
    )
    analytics = DiscoveryInfrastructure.method_analytics(
        payload["candidates"] + payload["resolved_candidates"]
    )
    assert analytics["SEARCH_ENGINE"]["confirmed"] == 1
    assert analytics["SEARCH_ENGINE"]["active_upcoming"] == 1
    assert sum(item["candidates"] for item in analytics.values()) == 11


def test_evidence_submission_schema_requires_review_and_hash_not_image_contents():
    schema = DiscoveryInfrastructure(ROOT).evidence_submission_schema()
    assert schema["properties"]["verification_status"]["const"] == "PENDING_ADMIN_REVIEW"
    assert "evidence_file_sha256" in schema["required"]
    assert "image_data" not in schema["properties"]
