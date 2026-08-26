import json
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_candidate_backlog_is_not_central_feed_data():
    payload = json.loads(
        (ROOT / "app" / "resources" / "coverage_candidate_backlog.json").read_text(encoding="utf-8")
    )
    feed_ids = {
        item["id"]
        for path in (
            ROOT / "app" / "resources" / "official_central_campaigns.json",
            ROOT / "app" / "resources" / "pokemon_restricted_campaigns.json",
        )
        for item in json.loads(path.read_text(encoding="utf-8"))["campaigns"]
    }

    assert len(payload["candidates"]) >= 10
    assert payload["schema_version"] == 2
    assert payload["rediscovery_policy"]["minimum_interval_hours"] >= 72
    assert payload["rediscovery_policy"]["over_polling_prohibited"] is True
    assert all(item["candidate_shop"] for item in payload["candidates"])
    assert all(item["status"] == "STILL_CANDIDATE" for item in payload["candidates"])
    assert all(item["reason"] for item in payload["candidates"])
    assert all(item["failure_reason"] for item in payload["candidates"])
    assert all(item["missing_evidence"] for item in payload["candidates"])
    assert all(item["products_checked"] for item in payload["candidates"])
    assert all(item["official_sources_checked"] for item in payload["candidates"])
    assert all(item["next_action"] for item in payload["candidates"])
    assert all(
        datetime.fromisoformat(item["next_check_at"]) > datetime.fromisoformat(item["last_checked_at"])
        for item in payload["candidates"]
    )
    assert not ({item.get("id") for item in payload["candidates"]} - {None}) & feed_ids
    assert payload["resolved_candidates"][0]["result"] == "PROMOTED_CONFIRMED"
    assert payload["resolved_candidates"][0]["campaign_id"] in feed_ids
