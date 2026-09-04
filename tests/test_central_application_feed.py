from datetime import datetime
import json
from pathlib import Path

from core.central_application_feed import (
    JST, _application_branch_key, _product_identity, build_central_feed,
)


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

    assert len(pokemon) == 72
    assert len({(item["chain_key"], item["branch_name"]) for item in pokemon}) == 46
    assert sum(item["application_status"] == "UPCOMING" for item in pokemon) == 19
    assert len([item for item in pokemon if item["chain_key"] == "furuichi"]) == 5
    one_piece = [item for item in feed["records"] if item["tcg"] == "one-piece"]
    assert len(one_piece) == 24
    assert sum(item["application_status"] == "UPCOMING" for item in one_piece) == 1
    assert sum(item["application_status"] == "ACTIVE" for item in one_piece) == 2
    assert all(item["verification_state"] == "CONFIRMED" for item in one_piece)
    assert len({item["branch_name"] for item in one_piece}) == 22
    dbfw = [item for item in feed["records"] if item["tcg"] == "dbfw"]
    assert len(dbfw) == 2
    assert {item["application_status"] for item in dbfw} == {"UPCOMING", "ENDED_WITHIN_14_DAYS"}
    assert all(item["verification_state"] == "CONFIRMED" for item in dbfw)
    assert any(item["application_url"] == "https://p-bandai.jp/item/item-1000255641/" for item in dbfw)
    gundam = [item for item in feed["records"] if item["tcg"] == "gundam"]
    assert len(gundam) == 3
    assert sum(item["application_status"] == "ACTIVE" for item in gundam) == 2
    assert all(item["sales_mode"] == "ONLINE" for item in gundam)
    assert all(item["verification_state"] == "CONFIRMED" for item in gundam)
    union_arena = [item for item in feed["records"] if item["tcg"] == "union-arena"]
    assert len(union_arena) == 1
    assert union_arena[0]["application_status"] == "ACTIVE"
    assert feed["metrics"]["application_count"] == 106
    assert feed["metrics"]["upcoming"] == 23
    assert feed["metrics"]["unique_applications"] == 104
    assert feed["metrics"]["unique_campaigns"] == 81
    assert feed["metrics"]["unique_branches"] == 69
    assert feed["metrics"]["unique_chains"] == 27
    assert feed["metrics"]["pokemon_unique_branches"] == 46
    assert feed["metrics"]["pokemon_unique_chains"] == 23
    assert feed["metrics"]["confirmed"] == 79
    assert feed["metrics"]["restricted"] == 27
    assert feed["metrics"]["duplicate_records_removed"] == 5
    assert sum(
        item["duplicate_count"] for item in feed["metrics"]["source_effectiveness"].values()
    ) == 5
    assert feed["metrics"]["by_tcg"]["yugioh"]["total"] == 4
    hobby_station = next(item for item in feed["records"] if item["chain_key"] == "hobby_station")
    assert hobby_station["eligibility_conditions"]["application_channel"] == "LivePocket"
    assert hobby_station["eligibility_conditions"]["payment_method_requirement"] == "事前支払いは現金のみ"
    assert all(item["application_end_at"] for item in feed["records"])
    assert len({item["id"] for item in feed["records"]}) == len(feed["records"])
    assert all(item["campaign_id"] for item in feed["records"])
    assert all(item["application_id"] for item in feed["records"])
    assert all(item["source_tier"] == "TIER_A" for item in feed["records"])


def test_public_monitoring_sources_separate_chain_store_online_and_platform():
    coverage = {"generated_at": "2026-09-04T14:00:00+09:00", "rows": []}
    official = {"campaigns": [{
        "id": "plant", "tcg": "pokemon", "chain": "plant", "product_name": "Product",
        "official_url": "https://official.example/news", "application_end_at": "2026-09-10T23:59:00+09:00",
        "source_type": "OFFICIAL_RETAILER_APPLICATION_NOTICE", "sales_mode": "STORE",
        "observed_at": "2026-09-04T12:00:00+09:00",
        "stores": [
            ["津幡店", "石川県", "https://official.example/apply"],
            ["津幡店", "石川県", "https://official.example/apply"],
        ],
    }]}
    discovery = {"known_source_memory": [{
        "source_id": "plant_campaign_lottery", "retailer_id": "plant",
        "application_platform": "LivePocket", "source_type": "OFFICIAL_RETAILER_APPLICATION_NOTICE",
        "source_effectiveness": "ACTIVE_CONFIRMED", "last_successful_discovery": "2026-09-04T12:00:00+09:00",
    }]}
    feed = build_central_feed(
        coverage, {"campaigns": []}, official, discovery,
        now=datetime(2026, 9, 4, 14, 0, tzinfo=JST),
    )
    sources = feed["monitoring_sources"]
    assert len([item for item in sources if item["entry_type"] == "PHYSICAL_STORE"]) == 1
    assert len([item for item in sources if item["entry_type"] == "RETAILER_CHAIN"]) == 1
    assert len([item for item in sources if item["entry_type"] == "APPLICATION_PLATFORM"]) == 1
    assert next(item for item in sources if item["entry_type"] == "PHYSICAL_STORE")["active_count"] == 1
    serialized = json.dumps(sources, ensure_ascii=False)
    assert "discovery_queries" not in serialized
    assert "official_domains" not in serialized
    assert "source_url" not in serialized


def test_no_start_campaign_is_not_visible_before_first_official_observation():
    official = {"campaigns": [{
        "tcg": "pokemon", "chain": "plant", "product_name": "Future observed",
        "official_url": "https://official.example/news", "application_start_at": "",
        "application_end_at": "2026-09-10T23:59:00+09:00",
        "observed_at": "2026-09-04T12:00:00+09:00",
        "stores": [["店舗", "東京都", "https://official.example/apply"]],
    }]}
    feed = build_central_feed(
        {"generated_at": "2026-09-01T00:00:00+09:00", "rows": []},
        {"campaigns": []}, official, now=datetime(2026, 9, 1, 0, 0, tzinfo=JST),
    )
    assert feed["records"] == []
    assert feed["metrics"]["rejected"] == {"not_observed_yet": 1}


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


def test_campaign_application_and_branch_identity_are_distinct():
    official = {"campaigns": [{
        "id": "shared-campaign", "tcg": "pokemon", "chain": "official",
        "product_name": "Shared form", "official_url": "https://official.example/notice",
        "application_start_at": "2026-08-20T00:00:00+09:00",
        "application_end_at": "2026-08-30T23:59:00+09:00",
        "application_method": "公式アプリ抽選", "eligibility_conditions": {"app_required": True},
        "stores": [
            ["A店", "東京都", "https://official.example/apply"],
            ["B店", "神奈川県", "https://official.example/apply"],
        ],
    }]}
    feed = build_central_feed(
        {"generated_at": "2026-08-24T12:00:00+09:00", "rows": []},
        {"campaigns": []}, official, now=datetime(2026, 8, 24, 12, 0, tzinfo=JST),
    )

    assert len(feed["records"]) == 2
    assert len({item["id"] for item in feed["records"]}) == 2
    assert len({item["campaign_id"] for item in feed["records"]}) == 1
    assert len({item["application_id"] for item in feed["records"]}) == 1
    assert feed["metrics"]["unique_branches"] == 2
    assert feed["records"][0]["eligibility_conditions"] == {"app_required": True}
    assert feed["records"][0]["application_method"] == "公式アプリ抽選"


def test_same_application_branch_from_two_sources_is_not_counted_twice():
    coverage = {"generated_at": "2026-08-24T12:00:00+09:00", "rows": [{
        "confirmed": True, "tcg": "pokemon", "chain": "pokemon_card_store",
        "branch": "ポケモンカードストア in ららぽーと沼津", "product": "商品（10パックまで）",
        "deadline": "2026-09-08T23:59:00+09:00", "prefecture": "静岡県",
        "official_url": "https://official.example/notice", "application_url": "https://apply.example/event/1/?b=2&utm_source=discovery&a=1",
        "eligibility_conditions": {"app_required": True},
    }]}
    official = {"campaigns": [{
        "id": "official-campaign", "tcg": "pokemon", "chain": "pokemon_card_store",
        "product_name": "商品", "official_url": "https://official.example/notice",
        "application_start_at": "2026-08-21T14:00:00+09:00",
        "application_end_at": "2026-09-08T23:59:00+09:00",
        "application_method": "公式LINEミニアプリ抽選",
        "eligibility_conditions": {"membership_required": True},
        "stores": [["ららぽーと沼津", "静岡県", "https://apply.example/event/1?a=1&b=2"]],
    }]}
    feed = build_central_feed(
        coverage, {"campaigns": []}, official, now=datetime(2026, 8, 24, 12, 0, tzinfo=JST),
    )

    assert len(feed["records"]) == 1
    assert feed["records"][0]["application_start_at"] == "2026-08-21T14:00:00+09:00"
    assert feed["records"][0]["application_method"] == "公式LINEミニアプリ抽選"
    assert feed["records"][0]["eligibility_conditions"] == {
        "app_required": True, "membership_required": True,
    }
    assert feed["metrics"]["duplicate_records_removed"] == 1
    effectiveness = feed["metrics"]["source_effectiveness"]
    assert sum(item["candidate_discovered_count"] for item in effectiveness.values()) == 2
    assert sum(item["duplicate_count"] for item in effectiveness.values()) == 1
    assert any(item["duplicate_rate"] > 0 for item in effectiveness.values())


def test_application_method_identity_normalizes_width_spacing_and_punctuation():
    base = {
        "tcg": "pokemon", "chain_key": "shop", "branch_name": "本店",
        "product_name": "商品", "application_end_at": "2026-09-08T23:59:00+09:00",
        "application_url": "",
    }
    assert _application_branch_key({**base, "application_method": "公式 ＷＥＢ・抽選"}) == (
        _application_branch_key({**base, "application_method": "公式web抽選"})
    )


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


def test_product_identity_folds_reviewed_aliases_without_merging_other_30th_products():
    box = _product_identity("ポケモンカードゲーム MEGA 拡張パック『30th Celebration』BOX")
    alias = _product_identity("ポケモンカードゲーム MEGA 拡張パック 30th CELEBRATION BOX")
    deck = _product_identity(
        "ポケモンカードゲーム MEGA 30th CELEBRATION プレミアムデッキセット エーフィ・ブラッキー"
    )
    assert box["product_id"] == alias["product_id"]
    assert box["product_id"] != deck["product_id"]
    assert box["image"]["url"] == ""
    assert box["image"]["rights_status"] == "NOT_CLEARED"


def test_verified_hareruya_livepocket_and_ministop_are_active_and_linked():
    official = json.loads(
        (ROOT / "app" / "resources" / "official_central_campaigns.json").read_text(encoding="utf-8")
    )
    feed = build_central_feed(
        {"generated_at": "2026-09-03T12:00:00+09:00", "rows": []},
        {"campaigns": []}, official, now=datetime(2026, 9, 3, 12, 0, tzinfo=JST),
    )
    items = [item for item in feed["records"] if item["chain_key"] in {"hareruya2", "ministop_online"}]
    assert len(items) == 3
    assert all(item["application_status"] == "ACTIVE" for item in items)
    assert {item["chain_name"] for item in items} == {"晴れる屋2", "ミニストップオンライン"}
    hareruya = [item for item in items if item["chain_key"] == "hareruya2"]
    assert all(item["application_url"] == "https://livepocket.jp/e/wrb86" for item in hareruya)
    assert all(item["eligibility_conditions"]["application_platform"] == "LivePocket" for item in hareruya)
    assert len({item["product_id"] for item in items}) == 2
