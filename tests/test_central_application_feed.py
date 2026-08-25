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

    assert len(pokemon) == 43
    assert len({(item["chain_key"], item["branch_name"]) for item in pokemon}) == 31
    assert sum(item["application_status"] == "UPCOMING" for item in pokemon) == 2
    assert len([item for item in pokemon if item["chain_key"] == "furuichi"]) == 4
    one_piece = [item for item in feed["records"] if item["tcg"] == "one-piece"]
    assert len(one_piece) == 24
    assert sum(item["application_status"] == "UPCOMING" for item in one_piece) == 1
    assert sum(item["application_status"] == "ACTIVE" for item in one_piece) == 2
    assert all(item["verification_state"] == "CONFIRMED" for item in one_piece)
    assert len({item["branch_name"] for item in one_piece}) == 22
    dbfw = [item for item in feed["records"] if item["tcg"] == "dbfw"]
    assert len(dbfw) == 1
    assert dbfw[0]["application_status"] == "ENDED_WITHIN_14_DAYS"
    assert dbfw[0]["verification_state"] == "CONFIRMED"
    assert dbfw[0]["application_url"] == "https://p-bandai.jp/item/item-1000255641/"
    gundam = [item for item in feed["records"] if item["tcg"] == "gundam"]
    assert len(gundam) == 3
    assert sum(item["application_status"] == "ACTIVE" for item in gundam) == 2
    assert all(item["sales_mode"] == "ONLINE" for item in gundam)
    assert all(item["verification_state"] == "CONFIRMED" for item in gundam)
    union_arena = [item for item in feed["records"] if item["tcg"] == "union-arena"]
    assert len(union_arena) == 1
    assert union_arena[0]["application_status"] == "ACTIVE"
    assert feed["metrics"]["application_count"] == 73
    assert feed["metrics"]["upcoming"] == 3
    assert feed["metrics"]["pokemon_unique_branches"] == 31
    assert feed["metrics"]["pokemon_unique_chains"] == 15
    assert feed["metrics"]["confirmed"] >= 22
    assert feed["metrics"]["restricted"] == 16
    assert all(item["application_end_at"] for item in feed["records"])
    assert len({item["id"] for item in feed["records"]}) == len(feed["records"])


def test_official_campaign_provider_url_is_not_onepiece_specific():
    official = {"campaigns": [{
        "tcg": "gundam", "chain": "provider", "product_name": "Official product",
        "official_url": "https://official.example/news", "application_start_at": "2026-08-20T00:00:00+09:00",
        "application_end_at": "2026-08-30T23:59:00+09:00", "sales_mode": "ONLINE",
        "stores": [["オンライン", "全国", "https://provider.example/apply"]],
    }]}
    feed = build_central_feed(
        {"generated_at": "2026-08-24T12:00:00+09:00", "rows": []},
        {"campaigns": []}, official, now=datetime(2026, 8, 24, 12, 0, tzinfo=JST),
    )
    assert feed["records"][0]["application_url"] == "https://provider.example/apply"


def test_one_piece_official_campaign_expires_after_fourteen_days():
    coverage = {"generated_at": "2026-08-31T00:00:00+09:00", "rows": []}
    restricted = {"campaigns": []}
    official = {"campaigns": [{
        "tcg": "onepiece", "chain": "official", "product_name": "OP-17",
        "official_url": "https://official.example/op17",
        "application_end_at": "2026-08-16T23:59:00+09:00",
        "stores": [["店舗", "東京都", "https://official.example/apply"]],
    }]}
    feed = build_central_feed(
        coverage, restricted, official, now=datetime(2026, 8, 31, 0, 0, tzinfo=JST),
    )
    assert not [item for item in feed["records"] if item["tcg"] == "one-piece"]


def test_verified_future_campaign_is_exported_as_upcoming():
    official = {"campaigns": [{
        "tcg": "pokemon", "chain": "official", "product_name": "Future",
        "official_url": "https://official.example/future",
        "application_start_at": "2026-08-28T00:00:00+09:00",
        "application_end_at": "2026-08-30T23:59:00+09:00",
        "stores": [["店舗", "東京都", "https://official.example/apply"]],
    }]}
    feed = build_central_feed(
        {"generated_at": "2026-08-24T12:00:00+09:00", "rows": []},
        {"campaigns": []}, official, now=datetime(2026, 8, 24, 12, 0, tzinfo=JST),
    )
    assert len(feed["records"]) == 1
    assert feed["records"][0]["application_status"] == "UPCOMING"
    assert feed["records"][0]["application_start_at"] == "2026-08-28T00:00:00+09:00"
    assert feed["metrics"]["upcoming"] == 1


def test_future_restricted_is_upcoming_but_future_candidate_is_rejected():
    restricted = {"campaigns": [{
        "tcg": "onepiece", "chain": "restricted", "branch": "対象店舗", "product_name": "Future restricted",
        "official_url": "https://official.example/restricted", "application_url": "https://official.example/apply",
        "application_start_at": "2026-08-28T00:00:00+09:00",
        "application_end_at": "2026-08-30T23:59:00+09:00",
    }]}
    coverage = {"generated_at": "2026-08-24T12:00:00+09:00", "rows": [{
        "confirmed": False, "tcg": "gundam", "chain": "candidate", "branch": "対象店舗", "product": "Candidate",
        "application_start_at": "2026-08-29T00:00:00+09:00", "deadline": "2026-08-30T23:59:00+09:00",
    }]}
    feed = build_central_feed(coverage, restricted, now=datetime(2026, 8, 24, 12, 0, tzinfo=JST))
    assert len(feed["records"]) == 1
    assert feed["records"][0]["tcg"] == "one-piece"
    assert feed["records"][0]["application_status"] == "UPCOMING"
    assert feed["records"][0]["verification_state"] == "UNVERIFIED_RESTRICTED"
    assert feed["metrics"]["rejected"] == {"future_candidate": 1}


def test_status_transitions_use_jst_server_time_and_fourteen_day_retention():
    official = {"campaigns": [{
        "tcg": "gundam", "chain": "official", "product_name": "Transitions",
        "official_url": "https://official.example/transitions",
        "application_start_at": "2026-08-28T10:00:00+09:00",
        "application_end_at": "2026-08-30T18:00:00+09:00",
        "stores": [["オンライン", "全国", "https://official.example/apply"]],
    }]}
    empty = {"generated_at": "2026-08-24T12:00:00+09:00", "rows": []}
    assert build_central_feed(empty, {"campaigns": []}, official, now=datetime(2026, 8, 28, 9, 59, tzinfo=JST))["records"][0]["application_status"] == "UPCOMING"
    assert build_central_feed(empty, {"campaigns": []}, official, now=datetime(2026, 8, 28, 10, 0, tzinfo=JST))["records"][0]["application_status"] == "ACTIVE"
    assert build_central_feed(empty, {"campaigns": []}, official, now=datetime(2026, 8, 30, 18, 1, tzinfo=JST))["records"][0]["application_status"] == "ENDED_WITHIN_14_DAYS"
    assert build_central_feed(empty, {"campaigns": []}, official, now=datetime(2026, 9, 13, 18, 1, tzinfo=JST))["records"] == []


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
