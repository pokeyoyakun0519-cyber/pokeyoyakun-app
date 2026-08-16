from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from functools import lru_cache
from typing import Any, Callable

from core.application_period import ApplicationPeriodParser, JST
from core.application_status import evaluate_application_period
from core.builtin_store_catalog import (
    load_builtin_store_catalog,
    match_builtin_store,
    normalize_store_name,
)
from core.tcg_categories import normalize_key


ACTIVE = "ACTIVE"
UPCOMING = "UPCOMING"
EXPIRED = "EXPIRED"
CANDIDATE = "candidate"
CONFIRMED = "confirmed"
REJECTED = "rejected"

OFFICIAL_SOURCE_TYPES = {
    "OFFICIAL_MANUFACTURER", "OFFICIAL_STORE", "OFFICIAL_SHOP_BRANCH",
}
_NEGATIVE = re.compile(
    r"買取|デッキレシピ|カードリスト|大会(?:結果|情報)?|イベント|"
    r"プレゼント企画|個人売買|相場|交換希望|譲ります|サプライ|"
    r"スリーブ|プレイマット|フィギュア|グッズ"
)
_TYPE_PATTERNS = (
    ("LOTTERY", re.compile(r"抽選販売|WEB抽選|店頭抽選|抽選受付|応募受付|購入権|当選")),
    ("RESERVATION", re.compile(r"予約受付|予約開始|予約中|受注|店頭受付")),
    ("RESTOCK", re.compile(r"再販|再入荷|入荷しました|入荷情報")),
    ("SALE", re.compile(r"販売開始|発売開始|販売中|在庫あり")),
)
_TCG_TEXT = (
    ("pokemon", re.compile(r"ポケモンカード|ポケカ", re.I)),
    ("onepiece", re.compile(r"ONE\s*PIECEカード|ワンピ(?:ース)?(?:カード)?", re.I)),
    ("union_arena", re.compile(r"UNION\s*ARENA|ユニオンアリーナ|ユニアリ", re.I)),
    (
        "dragon_ball_fusion_world",
        re.compile(
            r"ドラゴンボール(?:スーパー)?カードゲーム\s*(?:フュージョンワールド|FW)|"
            r"DBSCG\s*(?:FUSION\s*WORLD|FW)|DBFW",
            re.I,
        ),
    ),
)
_PRODUCT_CODE = re.compile(
    r"\b(?:(?:SV|M|SM|S|XY|BW)?\d{1,3}[A-Z]?|(?:OP|EB|ST|PRB)-?\d{2,3}|"
    r"(?:UA|EX)\d{2}(?:BT|ST|DC)|(?:FB|FS|SB|ST)\d{2})\b",
    re.I,
)
_URL = re.compile(r"https://[^\s<>\]\[()]+", re.I)
_STORE_IN_TEXT = re.compile(
    r"(カードラボ[^\s　、。]{0,24}?店|ホビーステーション[^\s　、。]{0,24}?店|"
    r"ヨドバシ(?:カメラ)?(?:マルチメディア)?[^\s　、。]{0,24}?店|"
    r"ビックカメラ[^\s　、。]{0,24}?店)"
)
_PURCHASE_PERIOD = re.compile(
    r"(?:購入|受取|引取)(?:可能)?期間?\s*[:：]?\s*"
    r"(?P<value>[^\n。]{3,80})"
)


@lru_cache(maxsize=1)
def _catalog_stores() -> tuple[dict[str, Any], ...]:
    """投稿ごとのカタログ再読込を避ける読み取り専用キャッシュ。"""
    try:
        return tuple(load_builtin_store_catalog()["stores"])
    except (OSError, ValueError, KeyError, TypeError):
        return ()


def normalize_store_reference(name: Any, url: Any = "") -> dict[str, Any]:
    """店舗チェーンと支店を分離する。曖昧な名称は推測確定しない。"""
    text = unicodedata.normalize("NFKC", str(name or "")).strip()
    compact = normalize_store_name(text)
    branch = ""
    if re.search(r"ヨドバシ(?:カメラ)?(?:マルチメディア)?(?:akiba|秋葉原)", compact, re.I):
        text, branch = "ヨドバシカメラ", "マルチメディアAkiba"
    else:
        branch_match = re.search(
            r"(?P<chain>カードラボ|ホビーステーション|ビックカメラ|ヨドバシカメラ)"
            r"\s*(?P<branch>[^\s　]{1,30}?)(?:店|店舗)?$",
            text,
        )
        if branch_match and branch_match.group("branch"):
            text = branch_match.group("chain")
            branch = branch_match.group("branch")
    stores = _catalog_stores()
    matched = match_builtin_store(stores, name=text, url=url) if stores else None
    return {
        "store_id": str(matched.get("store_group_id", "")) if matched else "",
        "canonical_store_id": str(matched.get("canonical_store_id", "")) if matched else "",
        "store_name": str(matched.get("display_name", text)) if matched else text,
        "branch": branch,
        "store_match_confidence": 1.0 if matched and not branch else (0.95 if matched else 0.0),
        "store_ambiguous": not bool(matched),
    }


def normalize_evidence(raw: dict[str, Any]) -> dict[str, Any]:
    source_type = str(raw.get("source_type", "GENERAL_INFORMATION")).strip().upper()
    return {
        "source_type": source_type,
        "source_url": str(raw.get("source_url", "")).strip(),
        "observed_at": str(raw.get("observed_at", "")).strip(),
        "trust": max(0, min(100, int(raw.get("trust", raw.get("manual_trust_score", 30)) or 0))),
        "extracted_fields": dict(raw.get("extracted_fields", {}))
        if isinstance(raw.get("extracted_fields", {}), dict) else {},
        "verification_status": str(raw.get("verification_status", CANDIDATE)),
    }


def temporal_state(item: dict[str, Any], *, now: datetime | None = None) -> str:
    period = evaluate_application_period(item, now=now)
    if period["period_ended"]:
        return EXPIRED
    start = ApplicationPeriodParser._as_jst(now or datetime.now(JST))
    parsed_start = _parse_time(item.get("application_start_at"))
    if parsed_start and start < parsed_start:
        return UPCOMING
    return ACTIVE


def confidence_components(item: dict[str, Any]) -> dict[str, Any]:
    evidence = [normalize_evidence(value) for value in item.get("evidence", []) if isinstance(value, dict)]
    source_trust = max(
        [int(item.get("manual_trust_score", item.get("trust_score", 30)) or 30)]
        + [value["trust"] for value in evidence]
    )
    official = any(value["source_type"] in OFFICIAL_SOURCE_TYPES for value in evidence)
    app_url = bool(str(item.get("application_url", "")).strip())
    start = _parse_time(item.get("application_start_at"))
    end = _parse_time(item.get("application_end_at"))
    date_consistency = not (start and end and end < start)
    product_match = _bounded(item.get("product_match_confidence", 1.0 if item.get("product_id") else 0.5))
    store_match = _bounded(item.get("store_match_confidence", 1.0 if item.get("store_id") else 0.5))
    score = (
        (source_trust / 100) * 0.35
        + min(len(evidence), 3) / 3 * 0.15
        + (0.20 if official else 0)
        + (0.10 if app_url else 0)
        + (0.05 if date_consistency else 0)
        + product_match * 0.075
        + store_match * 0.075
    )
    return {
        "source_trust": source_trust,
        "evidence_count": len(evidence),
        "official_confirmation": official,
        "explicit_application_url": app_url,
        "date_consistency": date_consistency,
        "product_match_confidence": product_match,
        "store_match_confidence": store_match,
        "confidence": round(min(1.0, score), 4),
    }


def resolve_candidate(item: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    output = dict(item)
    output["evidence"] = _deduplicate_evidence(output.get("evidence", []))
    components = confidence_components(output)
    output.update(components)
    output["active_state"] = temporal_state(output, now=now)
    contradiction = not components["date_consistency"] or bool(output.get("contradiction"))
    official = components["official_confirmation"]
    explicit_type = str(output.get("application_type", "")) in {
        "LOTTERY", "RESERVATION", "RESTOCK",
    }
    if contradiction:
        status = REJECTED
    elif (
        output["active_state"] != EXPIRED
        and official
        and explicit_type
        and components["confidence"] >= 0.75
    ):
        status = CONFIRMED
    else:
        status = CANDIDATE
    output["verification_status"] = status
    output["confirmed"] = status == CONFIRMED
    return output


def match_product_reference(
    item: dict[str, Any], products: list[dict[str, Any]]
) -> dict[str, Any]:
    """既存の識別子衝突保護を使い、曖昧な商品を推測確定しない。"""
    from core.product_master import ProductMasterManager

    probe = {
        "tcg_key": item.get("tcg_key", ""),
        "name": item.get("product_name", item.get("name", "")),
        "product_kind": item.get("product_kind", ""),
        "official_product_id": item.get("official_product_id", ""),
        "product_code": item.get("product_code", ""),
        "jan": item.get("jan", ""),
        "release_date": item.get("release_date", ""),
    }
    index, method = ProductMasterManager.find_match(products, probe)
    if index is None:
        return {
            **item,
            "product_match_confidence": 0.0,
            "product_match_status": method or "not_found",
        }
    matched = products[index]
    return {
        **item,
        "product_id": str(matched.get("product_id") or matched.get("id") or ""),
        "product_name": str(matched.get("canonical_name") or matched.get("name") or ""),
        "product_match_confidence": 1.0 if method == "identifier" else 0.8,
        "product_match_status": method,
    }


def deduplicate_applications(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for raw in items:
        item = resolve_candidate(raw)
        matched = next((value for value in output if _same_application(value, item)), None)
        if not matched:
            output.append(item)
            continue
        matched["evidence"] = _deduplicate_evidence(
            [*matched.get("evidence", []), *item.get("evidence", [])]
        )
        for key in (
            "application_url", "application_start_at", "application_end_at",
            "result_announcement_at", "purchase_period", "product_id", "store_id", "branch",
        ):
            if not matched.get(key) and item.get(key):
                matched[key] = item[key]
        resolved = resolve_candidate(matched)
        matched.clear()
        matched.update(resolved)
    return output


def parse_discovery_post(
    text: Any,
    *,
    tcg_hint: str = "",
    created_at: str = "",
    ai_parser: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    value = unicodedata.normalize("NFKC", str(text or "")).strip()
    information_type = "IRRELEVANT" if _NEGATIVE.search(value) else "NEWS"
    if information_type != "IRRELEVANT":
        for kind, pattern in _TYPE_PATTERNS:
            if pattern.search(value):
                information_type = kind
                break
    tcg = normalize_key(tcg_hint, "")[0] if tcg_hint else "other"
    for key, pattern in _TCG_TEXT:
        if pattern.search(value):
            tcg = key
            break
    if tcg == "other" and re.search(r"\bFW\b", value, re.I) and re.search(
        r"\b(?:FB|FS|SB)\d{2}\b", value, re.I
    ):
        tcg = "dragon_ball_fusion_world"
    product_code_match = _PRODUCT_CODE.search(value)
    product_code = product_code_match.group(0).upper() if product_code_match else ""
    quoted = re.search(r"[「『](.{2,100}?)[」』]", value)
    parsed = ApplicationPeriodParser.parse(value, release_date="")
    url_match = _URL.search(value)
    store_match = _STORE_IN_TEXT.search(value)
    store = normalize_store_reference(store_match.group(1)) if store_match else {}
    purchase_match = _PURCHASE_PERIOD.search(value)
    output = {
        "tcg_key": tcg,
        "application_type": information_type,
        "product_name": quoted.group(1).strip() if quoted else product_code,
        "product_code": product_code,
        "application_url": url_match.group(0).rstrip("。、") if url_match else "",
        "created_at": created_at,
        **{key: val for key, val in parsed.items() if val not in ("", False)},
        **{key: val for key, val in store.items() if val not in ("", False)},
    }
    if purchase_match:
        output["purchase_period"] = purchase_match.group("value").strip()
    if ai_parser is not None:
        try:
            supplement = ai_parser(value)
            if isinstance(supplement, dict):
                for key in (
                    "product_name", "store_name", "branch", "application_start_at",
                    "application_end_at", "result_announcement_at", "purchase_period",
                ):
                    if not output.get(key) and supplement.get(key):
                        output[key] = supplement[key]
        except Exception:
            output["ai_fallback"] = True
    return output


def _same_application(left: dict[str, Any], right: dict[str, Any]) -> bool:
    if str(left.get("tcg_key", "")) != str(right.get("tcg_key", "")):
        return False
    left_url = _canonical_url(left.get("application_url"))
    right_url = _canonical_url(right.get("application_url"))
    if left_url and left_url == right_url:
        return True
    keys = ("product_id", "store_id", "branch", "application_end_at")
    left_values = tuple(_norm(left.get(key)) for key in keys)
    right_values = tuple(_norm(right.get(key)) for key in keys)
    return bool(all(left_values) and left_values == right_values)


def _deduplicate_evidence(values: Any) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for raw in values if isinstance(values, list) else []:
        if not isinstance(raw, dict):
            continue
        value = normalize_evidence(raw)
        key = (value["source_type"], value["source_url"])
        if key not in seen:
            seen.add(key)
            output.append(value)
    return output


def _parse_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return ApplicationPeriodParser._as_jst(parsed)


def _canonical_url(value: Any) -> str:
    from core.application_site import _url_identity
    return _url_identity(value)


def _norm(value: Any) -> str:
    return re.sub(r"[\s　「」『』・_\-/]", "", str(value or "")).casefold()


def _bounded(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0
