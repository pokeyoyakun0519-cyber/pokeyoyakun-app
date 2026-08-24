from datetime import datetime
import json
from pathlib import Path

from core.central_application_feed import JST, build_central_feed


ROOT = Path(__file__).resolve().parents[1]


def test_isolated_feed_uses_deadline_evidence_and_current_retention():
    coverage = json.loads((ROOT / "reports" / "coverage_phase2.json").read_text(encoding="utf-8"))
    restricted = json.loads(
        (ROOT / "app" / "resources" / "pokemon_restricted_campaigns.json").read_text(encoding="utf-8")
    )
    official = json.loads(
        (ROOT / "app" / "resources" / "official_central_campaigns.json").read_text(encoding="utf-8")
    )
    feed = build_central_feed(
        coverage, restricted, official, now=datetime(2026, 8, 24, 12, 0, tzinfo=JST),
    )
    pokemon = [item for item in feed["records"] if item["tcg"] == "pokemon"]

    assert len(pokemon) == 38
    one_piece = [item for item in feed["records"] if item["tcg"] == "one-piece"]
    assert len(one_piece) == 20
    assert all(item["application_status"] == "ENDED_WITHIN_14_DAYS" for item in one_piece)
    assert all(item["verification_state"] == "CONFIRMED" for item in one_piece)
    assert len({item["branch_name"] for item in one_piece}) == 20
    assert feed["metrics"]["pokemon_unique_branches"] == 30
    assert feed["metrics"]["pokemon_unique_chains"] == 14
    assert feed["metrics"]["confirmed"] >= 22
    assert feed["metrics"]["restricted"] == 16
    assert all(item["application_end_at"] for item in feed["records"])


def test_feed_excludes_deadline_missing_and_stale_rows():
    coverage = {"generated_at": "2026-08-24T12:00:00+09:00", "rows": [
        {"confirmed": True, "tcg": "pokemon", "chain": "x", "branch": "A", "product": "P"},
        {"confirmed": True, "tcg": "pokemon", "chain": "x", "branch": "B", "product": "P",
         "deadline": "2026-07-01T23:59:59+09:00", "official_url": "https://shop.example/official",
         "application_url": "https://shop.example/apply"},
    ]}
    feed = build_central_feed(
        coverage, {"campaigns": []}, now=datetime(2026, 8, 24, 12, 0, tzinfo=JST),
    )

    assert feed["records"] == []
    assert feed["metrics"]["rejected"] == {"deadline_missing": 1, "stale": 1}
