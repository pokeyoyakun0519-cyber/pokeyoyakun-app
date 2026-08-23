from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

from core.application_status import JST, parse_jst_datetime


REVERIFY_AFTER = timedelta(days=7)
STALE_AFTER = timedelta(days=14)
_OPEN = re.compile(r"(?:応募|予約|抽選)?受付中|応募中|予約受付中|抽選受付中")


def assess_unknown_deadline(
    site: dict[str, Any],
    *,
    product: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Classify unknown deadlines in memory; never mutates persisted data."""
    if str(site.get("application_end_at") or site.get("application_end") or "").strip():
        return _result("KNOWN_DEADLINE")
    if (
        bool(site.get("applied"))
        or str(site.get("application_state") or "").strip() not in {"", "未応募"}
        or str(site.get("result_status") or "").strip() not in {"", "未確認"}
    ):
        # User-tracked history remains visible; stale cleanup only applies to
        # unresolved offers that would otherwise look permanently open.
        return _result("USER_TRACKED")
    current = now or datetime.now(JST)
    current = current.replace(tzinfo=JST) if current.tzinfo is None else current.astimezone(JST)
    if _has_explicit_open_evidence(site, current):
        return _result("EXPLICIT_OPEN", explicit_open=True)

    product = product or {}
    timestamps = []
    # A product may be re-imported while an individual application source is
    # old.  Prefer site verification history and only fall back to product
    # timestamps when the site has no usable timestamp at all.
    for source in (site, product):
        source_timestamps = []
        for key in ("last_verified_at", "application_added_at", "created_at", "detected_at"):
            parsed = parse_jst_datetime(source.get(key))
            if parsed:
                source_timestamps.append((parsed, key))
        if source_timestamps:
            timestamps = source_timestamps
            break
    if timestamps:
        reference, field = max(timestamps, key=lambda item: item[0])
        age = current - reference
        if age > STALE_AFTER:
            return _result(
                "STALE_UNKNOWN", reference=reference, reason=f"{field}から14日超更新なし"
            )
        if age >= REVERIFY_AFTER:
            return _result(
                "REVERIFY_UNKNOWN", reference=reference, reason=f"{field}から7日以上更新なし"
            )
        return _result("CURRENT_UNKNOWN", reference=reference)

    release = parse_jst_datetime(product.get("release_date") or site.get("release_date"))
    if release and current > release + STALE_AFTER:
        return _result(
            "STALE_UNKNOWN",
            reference=release,
            reason="発売日から14日超・締切不明・明示受付中Evidenceなし",
        )
    return _result("UNKNOWN_FRESHNESS")


def _has_explicit_open_evidence(site: dict[str, Any], current: datetime) -> bool:
    status_open = False
    for key in ("status", "application_status", "reception_status", "source_status"):
        value = site.get(key)
        values = value if isinstance(value, (list, tuple)) else [value]
        if any(_OPEN.search(str(item or "")) for item in values):
            status_open = True
    verified_times = [
        parse_jst_datetime(site.get(key))
        for key in ("last_verified_at", "detected_at", "application_added_at", "created_at")
    ]
    if status_open and any(
        value is not None and current - value <= STALE_AFTER for value in verified_times
    ):
        return True
    evidence = site.get("evidence") or site.get("source_evidence") or []
    for item in evidence if isinstance(evidence, list) else [evidence]:
        if not isinstance(item, dict):
            continue
        extracted = item.get("extracted_fields")
        texts = [item.get("status"), item.get("explicit_open_evidence")]
        if isinstance(extracted, dict):
            texts.extend(extracted.get(key) for key in ("status", "application_status"))
        observed = parse_jst_datetime(
            item.get("last_verified_at") or item.get("observed_at") or item.get("detected_at")
        )
        if (
            observed is not None
            and current - observed <= STALE_AFTER
            and any(_OPEN.search(str(text or "")) for text in texts)
        ):
            return True
    return False


def _result(
    state: str,
    *,
    explicit_open: bool = False,
    reference: datetime | None = None,
    reason: str = "",
) -> dict[str, Any]:
    return {
        "freshness_status": state,
        "stale_unknown": state == "STALE_UNKNOWN",
        "reverify_unknown": state == "REVERIFY_UNKNOWN",
        "explicit_open_evidence": explicit_open,
        "freshness_reference_at": reference.isoformat() if reference else "",
        "freshness_reason": reason,
    }
