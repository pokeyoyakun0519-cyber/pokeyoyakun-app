from __future__ import annotations

from collections import Counter, defaultdict
import re
from typing import Any

from core.application_status import evaluate_application_period
from core.tcg_categories import normalize_key


TCGS = (
    "pokemon", "onepiece", "dragon_ball_fusion_world", "yugioh",
    "gundam", "union_arena", "duelmasters", "weiss",
)


def _tcg(item: dict[str, Any]) -> str:
    record = item.get("record", {})
    hit = item.get("hit", {})
    return normalize_key(
        record.get("tcg_key", hit.get("tcg_key")),
        record.get("tcg", hit.get("tcg")),
    )[0]


def _is_current(hit: dict[str, Any], now=None) -> bool:
    raw_end = str(hit.get("application_end_at") or hit.get("application_end") or "").strip()
    if not re.search(r"(?:20\d{2}[-/.年])?\d{1,2}[-/.月]\d{1,2}", raw_end):
        return False
    period = evaluate_application_period(hit, now=now)
    return not bool(period.get("period_ended")) and str(period.get("period_status")) not in {
        "受付前", "締切日時不明",
    }


def _identity(item: dict[str, Any]) -> tuple[str, ...]:
    record, hit = item.get("record", {}), item.get("hit", {})
    return (
        _tcg(item), str(record.get("product_code") or record.get("product_name", "")).casefold(),
        str(hit.get("site_key", "")), str(hit.get("branch", hit.get("store_branch", ""))),
        str(hit.get("application_url", hit.get("url", ""))),
        str(hit.get("application_end_at", hit.get("application_end", ""))),
    )


def build_application_coverage(
    discoveries: list[dict[str, Any]], *, dashboard_rows: list[dict[str, Any]] | None = None,
    source_gaps: list[dict[str, Any]] | None = None,
    known_current: list[dict[str, Any]] | None = None, now=None,
) -> dict[str, Any]:
    dashboard_rows = [dict(row) for row in (dashboard_rows or [])]
    current = [item for item in discoveries if isinstance(item, dict) and _is_current(item.get("hit", {}), now)]
    gaps = list({
        (str(gap.get("source_id", "")), str(gap.get("reason", "UNKNOWN")), tuple(sorted(gap.get("supported_tcg", [])))): gap
        for gap in (source_gaps or [])
    }.values())
    known = [item for item in (known_current or []) if _is_current(item.get("hit", {}), now)]
    by_tcg: dict[str, Any] = {}
    artifact_rows: list[dict[str, Any]] = []
    for tcg in TCGS:
        items = [item for item in current if _tcg(item) == tcg]
        confirmed = [item for item in items if item.get("hit", {}).get("verification_status") == "confirmed"]
        pending = [item for item in items if item not in confirmed]
        chains = Counter(str(item.get("hit", {}).get("site_key") or item.get("record", {}).get("source_id") or "unknown") for item in confirmed)
        branches = {
            (chain, str(item.get("hit", {}).get("branch") or item.get("hit", {}).get("store_branch") or item.get("hit", {}).get("name") or ""))
            for item in confirmed
            for chain in [str(item.get("hit", {}).get("site_key") or item.get("record", {}).get("source_id") or "unknown")]
        }
        total = sum(chains.values())
        dominant = (max(chains.values()) / total) if total else 0.0
        dashboard = [row for row in dashboard_rows if normalize_key(row.get("tcg_key"), row.get("tcg"))[0] == tcg]
        raw_tcg_gaps = [gap for gap in gaps if tcg in gap.get("supported_tcg", [tcg])]
        priority = {"ROBOTS": 5, "APP_REQUIRED": 4, "SNS_ONLY": 3, "PARSER_NEEDED": 2, "UNKNOWN": 1}
        selected_gaps: dict[str, dict[str, Any]] = {}
        for gap in raw_tcg_gaps:
            source_id = str(gap.get("source_id") or "unknown")
            existing = selected_gaps.get(source_id)
            if existing is None or priority.get(str(gap.get("reason")), 0) > priority.get(str(existing.get("reason")), 0):
                selected_gaps[source_id] = gap
        tcg_gaps = list(selected_gaps.values())
        gap_counts = Counter(str(gap.get("reason", "UNKNOWN")) for gap in tcg_gaps)
        articles = {str(item.get("record", {}).get("article_url", "")) for item in items if item.get("record", {}).get("article_url")}
        products: dict[str, dict[str, Any]] = defaultdict(lambda: {"candidate_chains": set(), "candidate_branches": set(), "verified_branches": set(), "dashboard_branches": set()})
        for item in items:
            record, hit = item.get("record", {}), item.get("hit", {})
            product = str(record.get("product_name") or "商品不明")
            chain = str(hit.get("site_key") or record.get("source_id") or "unknown")
            branch = str(hit.get("branch") or hit.get("store_branch") or hit.get("name") or "")
            products[product]["candidate_chains"].add(chain)
            products[product]["candidate_branches"].add((chain, branch))
            if hit.get("verification_status") == "confirmed":
                products[product]["verified_branches"].add((chain, branch))
        for row in dashboard:
            product = str(row.get("product_name") or "商品不明")
            products[product]["dashboard_branches"].add((str(row.get("site_key", "")), str(row.get("branch", row.get("store_name", "")))))
        by_tcg[tcg] = {
            "current_candidate_count": len(items),
            "official_candidate_count": sum(bool(item.get("record", {}).get("application_evidence")) for item in items),
            "verified_official_count": len(confirmed),
            "confirmed_application_count": len(confirmed),
            "dashboard_count": len(dashboard),
            "pending_count": len(pending),
            "unavailable_count": len(tcg_gaps),
            "app_required_count": gap_counts["APP_REQUIRED"],
            "sns_only_count": gap_counts["SNS_ONLY"],
            "robots_blocked_count": gap_counts["ROBOTS"],
            "parser_needed_count": gap_counts["PARSER_NEEDED"],
            "unknown_gap_count": gap_counts["UNKNOWN"],
            "official_article_count": len(articles),
            "application_event_count": len({_identity(item) for item in items}),
            "active_chain_count": len(chains),
            "active_branch_count": len(branches),
            "applications_per_chain": dict(chains),
            "dominant_chain_ratio": round(dominant, 3),
            "chain_diversity_warning": bool(total and dominant >= 0.8),
            "product_coverage": [
                {"product": product, "candidate_chain_count": len(values["candidate_chains"]),
                 "candidate_branch_count": len(values["candidate_branches"]),
                 "official_verified_branch_count": len(values["verified_branches"]),
                 "dashboard_branch_count": len(values["dashboard_branches"]),
                 "pending_count": len(values["candidate_branches"] - values["verified_branches"])}
                for product, values in sorted(products.items())
            ],
        }
        for item in items:
            record, hit = item.get("record", {}), item.get("hit", {})
            artifact_rows.append({
                "tcg": tcg, "product": record.get("product_name", ""),
                "chain": hit.get("site_key", ""), "branch": hit.get("branch") or hit.get("store_branch") or hit.get("name", ""),
                "source": record.get("source_id", ""), "state": hit.get("verification_status", "candidate"),
                "confirmed": hit.get("verification_status") == "confirmed",
                "dashboard_visible": any(str(row.get("application_url", row.get("url", ""))) == str(hit.get("application_url", hit.get("url", ""))) for row in dashboard),
                "failure_reason": "" if hit.get("verification_status") == "confirmed" else "VERIFICATION_FAILED",
                "official_url": record.get("article_url", ""), "application_url": hit.get("application_url", hit.get("url", "")),
                "application_route": _application_route(hit, record),
                "deadline": hit.get("application_end_at", hit.get("application_end", "")),
            })
    known_ids = {_identity(item) for item in known}
    confirmed_ids = {_identity(item) for item in current if item.get("hit", {}).get("verification_status") == "confirmed"}
    false_negative = known_ids - confirmed_ids
    false_positive = confirmed_ids - known_ids if known_ids else set()
    return {
        "by_tcg": by_tcg,
        "totals": {
            "current_candidates": len(current),
            "current_confirmed": len(confirmed_ids),
            "dashboard_rows": len(dashboard_rows),
            "false_negative_count": len(false_negative),
            "false_negative_reasons": {"NOT_DISCOVERED_OR_NOT_CONFIRMED": len(false_negative)},
            "precision_estimate": "not_estimated" if not known_ids else round((len(confirmed_ids & known_ids) / len(confirmed_ids)), 3) if confirmed_ids else 1.0,
            "recall_estimate": "not_estimated" if not known_ids else round(len(confirmed_ids & known_ids) / len(known_ids), 3),
            "estimate_scope": "dedicated_adapter_observed_current_set" if known_ids else "insufficient_ground_truth",
        },
        "rows": artifact_rows,
    }


def _application_route(hit: dict[str, Any], record: dict[str, Any]) -> str:
    application_url = str(hit.get("application_url") or hit.get("url") or "")
    official_url = str(record.get("article_url") or "")
    if "x.com/" in application_url or "twitter.com/" in application_url:
        return "SNS_REQUIRED"
    if not application_url:
        return "STORE_ONLY" if str(hit.get("sales_mode")) == "STORE" else "UNKNOWN"
    if application_url == official_url:
        return "OFFICIAL_DETAIL"
    if any(value in application_url for value in ("forms.gle/", "form.run/", "/apply", "/entry")):
        return "DIRECT_APPLICATION"
    return "OFFICIAL_DETAIL"
