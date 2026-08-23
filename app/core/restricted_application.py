from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit


UNVERIFIED_RESTRICTED = "unverified_restricted"
CONFIRMED = "confirmed"
REJECTED = "rejected"

_RESTRICTED_FAILURES = {
    "ROBOTS_BLOCKED", "ROBOTS_DISALLOWED", "ACCESS_RESTRICTED",
    "AUTOMATED_ACCESS_RESTRICTED",
}
_TRUSTED_PROVENANCE = {
    "TIER_B_DISCOVERY", "TIER_A_OFFICIAL", "VERIFIED_OFFICIAL_LINK",
    "KNOWN_STORE_HISTORY", "MULTI_SOURCE_CORROBORATION",
}


def is_restricted(value: Any) -> bool:
    return str(value or "").strip().casefold() == UNVERIFIED_RESTRICTED


def verification_bucket(value: Any) -> str:
    status = str(value or "candidate").strip().casefold()
    if status == CONFIRMED:
        return CONFIRMED
    if status == UNVERIFIED_RESTRICTED:
        return UNVERIFIED_RESTRICTED
    if status in {REJECTED, "invalid"}:
        return REJECTED
    return "candidate"


def restrict_discovery(
    discovery: dict[str, Any], *, official_url: str, reason: str,
) -> dict[str, Any]:
    """Mark a sufficiently sourced application candidate as restricted.

    This never manufactures missing application fields and never promotes a
    source-only record.  Callers must have already parsed an application.
    """
    output = {**discovery, "record": dict(discovery.get("record") or {}),
              "hit": dict(discovery.get("hit") or {})}
    record, hit = output["record"], output["hit"]
    if str(reason or "").strip().upper() not in _RESTRICTED_FAILURES:
        return output
    provenance = str(
        record.get("trust_tier") or record.get("provenance")
        or hit.get("trust_tier") or ""
    ).strip().upper()
    evidence_count = len([item for item in hit.get("evidence", []) if isinstance(item, dict)])
    trusted = provenance in _TRUSTED_PROVENANCE or evidence_count >= 2
    product = str(record.get("product_name") or hit.get("product_name") or "").strip()
    store = str(hit.get("name") or hit.get("chain") or record.get("source_name") or "").strip()
    application = bool(
        hit.get("application_end_at") or hit.get("application_start_at")
        or hit.get("application_period")
        or str(hit.get("application_type") or "").upper() in {
            "LOTTERY", "RESERVATION", "RESTOCK",
        }
    )
    if not (trusted and product and store and application):
        return output

    discovery_url = str(
        record.get("discovery_source_url")
        or record.get("article_url")
        or hit.get("source_url")
        or ""
    ).strip()
    official_url = str(official_url or "").strip()
    hit.update({
        "verification_status": UNVERIFIED_RESTRICTED,
        "confirmed": False,
        "retailer_verified": False,
        "official_store_verified": False,
        "restriction_reason": "AUTOMATED_ACCESS_RESTRICTED",
        "verification_details": (
            "サイト側の自動取得制限により、ポケヨヤ君では公式情報を自動確認できません。"
            "応募前に公式ページで内容をご確認ください。"
        ),
        "official_detail_url": official_url,
        "discovery_source_url": discovery_url,
        "restricted_url_kind": "official" if official_url else "discovery",
        "last_checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })
    if not official_url and discovery_url:
        hit["url"] = discovery_url
    record["verification_status"] = UNVERIFIED_RESTRICTED
    return output


def is_official_candidate_url(url: Any, discovery_url: Any = "") -> bool:
    value = str(url or "").strip()
    if not value or value == str(discovery_url or "").strip():
        return False
    try:
        parsed = urlsplit(value)
        return parsed.scheme.casefold() == "https" and bool(parsed.hostname)
    except ValueError:
        return False
