from __future__ import annotations

import hashlib
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable
from urllib.parse import urlsplit, urlunsplit


JST = timezone(timedelta(hours=9))
RETENTION_DAYS = 14
TCG_KEYS = {
    "pokemon": "pokemon",
    "onepiece": "one-piece",
    "one_piece": "one-piece",
    "one piece": "one-piece",
    "dragon_ball_fusion_world": "dbfw",
    "dragon ball fusion world": "dbfw",
    "dbfw": "dbfw",
    "yugioh": "yugioh",
    "gundam": "gundam",
    "union_arena": "union-arena",
    "union arena": "union-arena",
}
CHAIN_LABELS = {
    "pokemon_card_store": "ポケモンカードストア",
    "pokemon_center_online": "ポケモンセンターオンライン",
    "aeon_toy": "イオン玩具売場",
    "furuichi": "ふるいち／古本市場",
    "yellow_submarine": "イエローサブマリン",
    "otakarasouko": "お宝創庫",
    "card_labo": "カードラボ",
    "fullcomp": "フルコンプ",
    "sanyodo": "三洋堂書店",
    "hareruya2": "晴れる屋2",
    "pokeca_club": "ポケカ専門店『N』",
    "onepiece_official_shop": "ONE PIECEカードゲーム 公式ショップ",
    "premium_bandai": "プレミアムバンダイ",
    "geo": "GEO",
    "furuichi": "ふるいち／古本市場",
}
REGIONS = {
    "北海道": "北海道・東北", "青森県": "北海道・東北", "岩手県": "北海道・東北",
    "宮城県": "北海道・東北", "秋田県": "北海道・東北", "山形県": "北海道・東北",
    "福島県": "北海道・東北", "茨城県": "関東", "栃木県": "関東", "群馬県": "関東",
    "埼玉県": "関東", "千葉県": "関東", "東京都": "関東", "神奈川県": "関東",
    "新潟県": "中部", "富山県": "中部", "石川県": "中部", "福井県": "中部",
    "山梨県": "中部", "長野県": "中部", "岐阜県": "中部", "静岡県": "中部",
    "愛知県": "中部", "三重県": "近畿", "滋賀県": "近畿", "京都府": "近畿",
    "大阪府": "近畿", "兵庫県": "近畿", "奈良県": "近畿", "和歌山県": "近畿",
    "鳥取県": "中国・四国", "島根県": "中国・四国", "岡山県": "中国・四国",
    "広島県": "中国・四国", "山口県": "中国・四国", "徳島県": "中国・四国",
    "香川県": "中国・四国", "愛媛県": "中国・四国", "高知県": "中国・四国",
    "福岡県": "九州・沖縄", "佐賀県": "九州・沖縄", "長崎県": "九州・沖縄",
    "熊本県": "九州・沖縄", "大分県": "九州・沖縄", "宮崎県": "九州・沖縄",
    "鹿児島県": "九州・沖縄", "沖縄県": "九州・沖縄", "全国": "全国",
}


def build_central_feed(
    coverage_payload: dict[str, Any],
    restricted_payload: dict[str, Any],
    official_payload: dict[str, Any] | None = None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = (now or datetime.now(JST)).astimezone(JST)
    generated_at = _iso(coverage_payload.get("generated_at")) or current.isoformat(timespec="seconds")
    records = []
    rejected = Counter()
    enriched_rows = {
        _coverage_key(item): item
        for item in coverage_payload.get("production_coverage", {}).get("applications", [])
    }
    for row in coverage_payload.get("rows", []):
        base = dict(enriched_rows.get(_coverage_key(row), {}))
        base.update({key: value for key, value in row.items() if value not in (None, "")})
        record, reason = _from_coverage_row(base, current, generated_at)
        if record:
            records.append(record)
        else:
            rejected[reason or "invalid"] += 1
    for campaign in restricted_payload.get("campaigns", []):
        record, reason = _from_restricted_campaign(campaign, current)
        if record:
            records.append(record)
        else:
            rejected[reason or "invalid"] += 1
    for campaign in (official_payload or {}).get("campaigns", []):
        for store in campaign.get("stores", []):
            record, reason = _from_official_campaign(campaign, store, current)
            if record:
                records.append(record)
            else:
                rejected[reason or "invalid"] += 1
    records = _deduplicate(records)
    pokemon = [item for item in records if item["tcg"] == "pokemon"]
    branches = {(item["chain_key"], item["branch_name"]) for item in pokemon}
    chains = {item["chain_key"] for item in pokemon}
    branch_counts = Counter(chain for chain, _branch in branches)
    dominant = max(branch_counts.values(), default=0) / len(branches) if branches else 0.0
    return {
        "schema_version": 1,
        "feed_type": "CENTRAL_APPLICATION_FEED",
        "generated_at": current.isoformat(timespec="seconds"),
        "source_generated_at": generated_at,
        "records": records,
        "metrics": {
            "application_count": len(records),
            "upcoming": sum(item["application_status"] == "UPCOMING" for item in records),
            "active": sum(item["application_status"] == "ACTIVE" for item in records),
            "ended_within_14_days": sum(
                item["application_status"] == "ENDED_WITHIN_14_DAYS" for item in records
            ),
            "confirmed": sum(item["verification_state"] == "CONFIRMED" for item in records),
            "restricted": sum(
                item["verification_state"] == "UNVERIFIED_RESTRICTED" for item in records
            ),
            "pokemon_unique_branches": len(branches),
            "pokemon_unique_chains": len(chains),
            "pokemon_dominant_chain_ratio": round(dominant, 3),
            "rejected": dict(rejected),
        },
    }


def _from_coverage_row(
    row: dict[str, Any], current: datetime, generated_at: str,
) -> tuple[dict[str, Any] | None, str]:
    start_at = _iso(row.get("application_start_at"))
    if not row.get("confirmed"):
        if start_at and datetime.fromisoformat(start_at) > current:
            return None, "future_candidate"
        return None, "not_confirmed"
    deadline = _iso(row.get("deadline"))
    if not deadline:
        return None, "deadline_missing"
    end = datetime.fromisoformat(deadline)
    status = _window_status(end, current, datetime.fromisoformat(start_at) if start_at else None)
    if not status:
        return None, "stale"
    official_url = _public_url(row.get("official_url"))
    application_url = _public_url(row.get("application_url")) or official_url
    if not official_url or not application_url:
        return None, "url_invalid"
    tcg = TCG_KEYS.get(str(row.get("tcg") or "").casefold())
    if not tcg:
        return None, "tcg_unknown"
    chain = str(row.get("chain") or "").strip()
    branch = str(row.get("branch") or "").strip()
    product = str(row.get("product") or "").strip()
    if not chain or not branch or not product:
        return None, "identity_missing"
    prefecture = str(row.get("prefecture") or "地域不明").strip() or "地域不明"
    route = str(row.get("application_route") or "").upper()
    sales_mode = "ONLINE" if route in {"ONLINE", "WEB", "EC"} else "STORE"
    return _record(
        tcg=tcg, chain=chain, branch=branch, product=product,
        prefecture=prefecture, sales_mode=sales_mode,
        start_at=start_at, end_at=deadline, status=status,
        verification="CONFIRMED", application_url=application_url,
        official_url=official_url, source_label=str(row.get("source") or chain),
        last_verified_at=generated_at,
    ), ""


def _from_restricted_campaign(
    campaign: dict[str, Any], current: datetime,
) -> tuple[dict[str, Any] | None, str]:
    start_at = _iso(campaign.get("application_start_at"))
    end_at = _iso(campaign.get("application_end_at"))
    if not end_at:
        return None, "deadline_missing"
    start = datetime.fromisoformat(start_at) if start_at else None
    end = datetime.fromisoformat(end_at)
    status = _window_status(end, current, start)
    if not status:
        return None, "stale"
    official_url = _public_url(campaign.get("official_url"))
    application_url = _public_url(campaign.get("application_url")) or official_url
    if not official_url or not application_url:
        return None, "url_invalid"
    chain = str(campaign.get("chain") or "").strip()
    branch = str(campaign.get("branch") or "").strip()
    product = str(campaign.get("product_name") or "").strip()
    if not chain or not branch or not product:
        return None, "identity_missing"
    tcg = TCG_KEYS.get(str(campaign.get("tcg") or "pokemon").casefold())
    if not tcg:
        return None, "tcg_unknown"
    prefecture = str(campaign.get("prefecture") or "地域不明").strip() or "地域不明"
    return _record(
        tcg=tcg,
        chain=chain, branch=branch, product=product,
        prefecture=prefecture, sales_mode=str(campaign.get("sales_mode") or "STORE").upper(),
        start_at=start_at, end_at=end_at, status=status,
        verification="UNVERIFIED_RESTRICTED", application_url=application_url,
        official_url=official_url,
        source_label=str(campaign.get("source_type") or "公式再確認対象"),
        last_verified_at=str(campaign.get("observed_at") or current.isoformat(timespec="seconds")),
    ), ""


def _from_official_campaign(
    campaign: dict[str, Any], store: list[Any], current: datetime,
) -> tuple[dict[str, Any] | None, str]:
    if len(store) != 3:
        return None, "identity_missing"
    tcg = TCG_KEYS.get(str(campaign.get("tcg") or "").casefold())
    start_at, end_at = _iso(campaign.get("application_start_at")), _iso(campaign.get("application_end_at"))
    if not tcg or not end_at:
        return None, "tcg_unknown" if not tcg else "deadline_missing"
    start = datetime.fromisoformat(start_at) if start_at else None
    status = _window_status(datetime.fromisoformat(end_at), current, start)
    if not status:
        return None, "stale"
    official_url = _public_url(campaign.get("official_url"))
    application_value = str(store[2])
    if application_value.startswith("https://"):
        application_url = _public_url(application_value)
    else:
        base = str(campaign.get("application_url_base") or "https://parks2.bandainamco-am.co.jp/category/ECCL00000054/")
        application_url = _public_url(base + application_value)
    if not official_url or not application_url:
        return None, "url_invalid"
    return _record(
        tcg=tcg, chain=str(campaign.get("chain") or ""), branch=str(store[0]),
        product=str(campaign.get("product_name") or ""), prefecture=str(store[1]),
        sales_mode=str(campaign.get("sales_mode") or "STORE"), start_at=start_at,
        end_at=end_at, status=status, verification="CONFIRMED",
        application_url=application_url, official_url=official_url,
        source_label=str(campaign.get("source_type") or "OFFICIAL_APPLICATION_PAGE"),
        last_verified_at=str(campaign.get("observed_at") or current.isoformat(timespec="seconds")),
    ), ""


def _record(**values: Any) -> dict[str, Any]:
    identity = "|".join(str(values[key]) for key in (
        "tcg", "chain", "branch", "product", "end_at", "application_url",
    ))
    record_id = "app-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
    prefecture = str(values["prefecture"])
    return {
        "id": record_id,
        "tcg": values["tcg"],
        "product_name": values["product"],
        "chain_key": values["chain"],
        "chain_name": CHAIN_LABELS.get(values["chain"], values["chain"]),
        "branch_name": values["branch"],
        "prefecture": prefecture,
        "region": REGIONS.get(prefecture, "地域不明"),
        "sales_mode": values["sales_mode"] if values["sales_mode"] in {"ONLINE", "STORE"} else "STORE",
        "application_start_at": values["start_at"],
        "application_end_at": values["end_at"],
        "application_status": values["status"],
        "verification_state": values["verification"],
        "application_url": values["application_url"],
        "official_url": values["official_url"],
        "source_label": values["source_label"],
        "is_new": True,
        "last_verified_at": values["last_verified_at"],
    }


def _window_status(end: datetime, current: datetime, start: datetime | None = None) -> str:
    if start and current < start.astimezone(JST):
        return "UPCOMING"
    end = end.astimezone(JST)
    if current <= end:
        return "ACTIVE"
    if current <= end + timedelta(days=RETENTION_DAYS):
        return "ENDED_WITHIN_14_DAYS"
    return ""


def _iso(value: Any) -> str:
    try:
        parsed = datetime.fromisoformat(str(value or ""))
    except ValueError:
        return ""
    if parsed.tzinfo is None:
        return ""
    return parsed.astimezone(JST).isoformat(timespec="seconds")


def _public_url(value: Any) -> str:
    try:
        parsed = urlsplit(str(value or "").strip())
    except ValueError:
        return ""
    if parsed.scheme.casefold() != "https" or not parsed.hostname or parsed.username or parsed.password:
        return ""
    return urlunsplit(("https", parsed.netloc.casefold(), parsed.path, parsed.query, ""))


def _deduplicate(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in records:
        if record["id"] not in seen:
            seen.add(record["id"])
            output.append(record)
    return sorted(output, key=lambda item: (item["application_end_at"], item["id"]))


def _coverage_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
    return tuple(str(row.get(key) or "").strip() for key in ("tcg", "chain", "branch", "product"))
