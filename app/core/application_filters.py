from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from core.application_status import JST, parse_jst_datetime


DEADLINE_SOON_HOURS = 72
UNKNOWN_REGION = "地域未確認"
REGION_ALL = "全国"
REGION_PREFECTURES = {
    "北海道・東北": ("北海道", "青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県"),
    "関東": ("茨城県", "栃木県", "群馬県", "埼玉県", "千葉県", "東京都", "神奈川県"),
    "中部": ("新潟県", "富山県", "石川県", "福井県", "山梨県", "長野県", "岐阜県", "静岡県", "愛知県"),
    "近畿": ("三重県", "滋賀県", "京都府", "大阪府", "兵庫県", "奈良県", "和歌山県"),
    "中国": ("鳥取県", "島根県", "岡山県", "広島県", "山口県"),
    "四国": ("徳島県", "香川県", "愛媛県", "高知県"),
    "九州・沖縄": ("福岡県", "佐賀県", "長崎県", "熊本県", "大分県", "宮崎県", "鹿児島県", "沖縄県"),
}
REGION_NAMES = (REGION_ALL, *REGION_PREFECTURES, UNKNOWN_REGION)
_PREFECTURE_TO_REGION = {
    prefecture: region
    for region, prefectures in REGION_PREFECTURES.items()
    for prefecture in prefectures
}
_TRACKING_KEYS = {"fbclid", "gclid", "ref_src", "ref_url", "twclid", "xclid"}
_CHAIN_BRANCH_PREFIXES = {
    "card_labo": ("カードラボ",), "hobby_station": ("ホビーステーション",),
    "batoroco": ("トーナメントセンターバトロコ", "バトロコ"),
    "plays": ("プレイズ", "playze"), "cardbox": ("カードボックス", "cardbox"),
    "furuichi": ("ふるいち", "古本市場"), "bookoff": ("bookoff", "ブックオフ"),
}


def region_for_prefecture(value: Any) -> str:
    """保存済みの完全な都道府県名だけを地方へ変換する。"""
    return _PREFECTURE_TO_REGION.get(str(value or "").strip(), UNKNOWN_REGION)


def sales_channel_matches(mode: Any, channel: str) -> bool:
    value = str(mode or "UNKNOWN").upper()
    if channel == "online":
        return value in {"ONLINE", "HYBRID"}
    if channel == "store":
        return value in {"STORE", "HYBRID"}
    return channel == "all"


def canonical_application_url(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parsed = urlsplit(text)
        if parsed.scheme.casefold() not in {"http", "https"} or not parsed.hostname:
            return ""
        query = [
            (key, item)
            for key, item in parse_qsl(parsed.query, keep_blank_values=True)
            if key.casefold() not in _TRACKING_KEYS
            and not key.casefold().startswith("utm_")
        ]
        return urlunsplit((
            parsed.scheme.casefold(), parsed.netloc.casefold(),
            parsed.path.rstrip("/") or "/", urlencode(query, doseq=True), "",
        ))
    except (TypeError, ValueError):
        return ""


def canonical_branch_name(chain: Any, branch: Any) -> str:
    value = unicodedata.normalize("NFKC", str(branch or "")).casefold()
    value = re.sub(r"[\s　・_-]+", "", value)
    chain_key = str(chain or "").strip().casefold()
    prefixes = (*_CHAIN_BRANCH_PREFIXES.get(chain_key, ()), str(chain or ""))
    for prefix in prefixes:
        normalized = re.sub(
            r"[\s　・_-]+", "", unicodedata.normalize("NFKC", prefix).casefold()
        )
        if normalized and value.startswith(normalized):
            value = value[len(normalized):]
            break
    return value


def stable_store_key(row: dict[str, Any]) -> str:
    chain = str(row.get("chain") or row.get("site_key") or "").strip().casefold()
    branch = canonical_branch_name(
        chain, row.get("branch") or row.get("site_name") or row.get("name")
    )
    url = canonical_application_url(
        row.get("site_url") or row.get("url") or row.get("source_url")
    )
    return "|".join((chain, branch, url))


def deadline_state(row: dict[str, Any], *, now: datetime | None = None) -> str:
    if row.get("period_ended"):
        return "expired"
    end = parse_jst_datetime(row.get("application_end_at") or row.get("application_end"))
    if end is None:
        return "unknown"
    current = now or datetime.now(JST)
    current = current.replace(tzinfo=JST) if current.tzinfo is None else current.astimezone(JST)
    remaining = end - current
    if remaining.total_seconds() < 0:
        return "expired"
    if end.date() == current.date():
        return "today"
    if remaining <= timedelta(hours=24):
        return "within_24h"
    if remaining <= timedelta(hours=DEADLINE_SOON_HOURS):
        return "within_72h"
    return "normal"


def is_deadline_soon(row: dict[str, Any], *, now: datetime | None = None) -> bool:
    return str(row.get("deadline_state") or deadline_state(row, now=now)) in {
        "today", "within_24h", "within_72h",
    }


def application_identity(row: dict[str, Any]) -> str:
    explicit = str(row.get("application_id") or row.get("source_event_id") or "").strip()
    if explicit:
        return explicit
    product = str(row.get("product_id") or row.get("product_name") or "").strip().casefold()
    chain = str(row.get("chain") or row.get("site_key") or "").strip().casefold()
    branch = str(row.get("branch") or row.get("site_name") or "").strip().casefold()
    end = str(row.get("application_end_at") or row.get("application_end") or "").strip()
    url = canonical_application_url(row.get("application_url") or row.get("source_url"))
    # URLが異なる別案件を誤統合しない。list/detail/form間の統合は、取得側が
    # 同一application_idを付与した場合、またはcanonical URLが一致する場合だけ行う。
    return "|".join((str(row.get("tcg_key") or "other"), product, chain, branch, end, url))
