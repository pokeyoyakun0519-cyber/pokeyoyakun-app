from __future__ import annotations

import json
import os
import re
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from core.application_status import JST, evaluate_application_period, parse_jst_datetime
from core.autonomous_source_registry import OfficialSourceCandidateStore
from core.runtime_paths import app_root
from core.tcg_categories import normalize_key
from core.web_application_sources import (
    PRIORITY_TCG,
    WebApplicationSourceRegistry,
)
from core.restricted_application import UNVERIFIED_RESTRICTED, verification_bucket


COVERAGE_STATES = {
    "DISCOVERED", "OFFICIAL_VERIFIED", "MONITORABLE", "CURRENT_APPLICATION",
    "RECENTLY_ENDED", "NO_CURRENT_APPLICATION", "APP_REQUIRED", "SNS_ONLY",
    "ROBOTS_BLOCKED", "PARSER_NEEDED", "HTTP_ERROR", "UNSUPPORTED",
    "VERIFYING", "DISCOVERED_CANDIDATE", "TEMPORARILY_FAILED",
    "UNVERIFIED_RESTRICTED", "TERMS_RESTRICTED",
}
PREFECTURES = (
    "北海道", "青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県",
    "茨城県", "栃木県", "群馬県", "埼玉県", "千葉県", "東京都", "神奈川県",
    "新潟県", "富山県", "石川県", "福井県", "山梨県", "長野県", "岐阜県",
    "静岡県", "愛知県", "三重県", "滋賀県", "京都府", "大阪府", "兵庫県",
    "奈良県", "和歌山県", "鳥取県", "島根県", "岡山県", "広島県", "山口県",
    "徳島県", "香川県", "愛媛県", "高知県", "福岡県", "佐賀県", "長崎県",
    "熊本県", "大分県", "宮崎県", "鹿児島県", "沖縄県",
)
GAP_CHECKS = (
    "index_checked", "latest_news_checked", "product_keyword_checked",
    "tcg_keyword_checked", "application_keyword_checked",
)


def _source_url(record: dict[str, Any]) -> str:
    for key in (
        "lottery_url", "reservation_url", "index_url", "search_url",
        "official_url", "evidence_url", "url",
    ):
        value = str(record.get(key) or "").strip()
        if value:
            return value
    return ""


def _tcg(item: dict[str, Any]) -> str:
    record, hit = item.get("record", {}), item.get("hit", {})
    return normalize_key(
        record.get("tcg_key", hit.get("tcg_key")),
        record.get("tcg", hit.get("tcg")),
    )[0]


def _chain(item: dict[str, Any]) -> str:
    record, hit = item.get("record", {}), item.get("hit", {})
    value = str(hit.get("site_key") or record.get("source_id") or "unknown")
    # Some branch adapters keep branch uniqueness in site_key.  Coverage must
    # count the parent chain separately from its branch count.
    if re.fullmatch(r"bandai_official_shop_[0-9a-f]{12}", value):
        return "bandai_official_shop"
    return value


def _prefecture(item: dict[str, Any]) -> str:
    record, hit = item.get("record", {}), item.get("hit", {})
    value = str(hit.get("prefecture") or record.get("prefecture") or "")
    return value if value in PREFECTURES else ""


def _period_state(item: dict[str, Any], now: datetime) -> str:
    hit = item.get("hit", {})
    preserved = str(hit.get("_coverage_state") or "")
    if preserved in {"CURRENT_APPLICATION", "RECENTLY_ENDED"}:
        return preserved
    period = evaluate_application_period(hit, now=now)
    if not period.get("period_ended"):
        return "CURRENT_APPLICATION"
    end_at = parse_jst_datetime(
        hit.get("application_end_at") or hit.get("application_end")
    )
    if isinstance(end_at, datetime) and now - end_at.astimezone(JST) <= timedelta(days=14):
        return "RECENTLY_ENDED"
    return "NO_CURRENT_APPLICATION"


def _source_state(row: dict[str, Any]) -> str:
    status = str(row.get("status") or "")
    source_class = str(row.get("monitor_type") or row.get("source_class") or "")
    if status in {"ACCESS_RESTRICTED", "BLOCKED_ROBOTS"} or row.get("error_code") in {
        "ROBOTS_DISALLOWED", "ROBOTS_BLOCKED",
    }:
        return "ROBOTS_BLOCKED"
    if status in {"PARSER_OUTDATED", "PARSE_EMPTY", "VERIFICATION_FAILED"}:
        return "PARSER_NEEDED"
    if status in {"HTTP_ERROR", "TEMPORARILY_FAILED"}:
        return status
    if source_class in {"APP_REQUIRED", "SNS_ONLY", "UNSUPPORTED"}:
        return source_class
    if status == "NO_CURRENT_APPLICATION":
        return "NO_CURRENT_APPLICATION"
    if source_class in {"WEB_DIRECT", "WEB_FORM", "WEB_TO_STORE", "STORE_DIRECT"}:
        return "MONITORABLE"
    return "DISCOVERED"


def build_production_coverage(
    discoveries: list[dict[str, Any]], *,
    dashboard_rows: list[dict[str, Any]] | None = None,
    registry: WebApplicationSourceRegistry | None = None,
    autonomous_registry: OfficialSourceCandidateStore | None = None,
    nationwide_diagnostics: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build a saved-data-only national coverage inventory.

    It never fetches Web pages and never upgrades a candidate to confirmed.
    """
    now = (now or datetime.now(JST)).astimezone(JST)
    registry = registry or WebApplicationSourceRegistry()
    nationwide = nationwide_diagnostics or {}
    observed_rows = {
        (str(row.get("chain")), str(row.get("source"))): row
        for row in nationwide.get("sources", []) if isinstance(row, dict)
    }
    inventory: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for tcg in PRIORITY_TCG:
        for source in registry.sources(tcg):
            chain = str(source.get("chain") or "unknown")
            url = _source_url(source)
            key = (tcg, chain, url)
            if key in seen:
                continue
            seen.add(key)
            observed = observed_rows.get((chain, url), {})
            merged = dict(source)
            merged.update(observed)
            state = _source_state(merged)
            checked = bool(observed.get("last_check"))
            inventory.append({
                "tcg": tcg, "chain": chain,
                "display_name": source.get("display_name") or chain,
                "official_url": url, "state": state,
                "declared_branches": int(source.get("branch_count") or 0),
                "prefectures": sorted({
                    str(location.get("prefecture"))
                    for location in source.get("confirmed_locations", [])
                    if isinstance(location, dict)
                    and str(location.get("prefecture")) in PREFECTURES
                }),
                "official_alternative_paths": list(source.get("official_alternative_paths") or []),
                "last_check": str(observed.get("last_check") or ""),
                "last_success": str(observed.get("last_success") or ""),
                "failure_reason": str(observed.get("error_code") or ""),
                "monitoring_type": str(source.get("source_class") or ""),
                "discovered_from": "bundled_registry",
                "gap_checks": {name: checked for name in GAP_CHECKS},
            })
    if autonomous_registry is not None:
        for source in autonomous_registry.sources():
            for tcg in source.get("supported_tcg", []):
                if tcg not in PRIORITY_TCG:
                    continue
                chain, url = str(source.get("id") or "unknown"), str(source.get("base_url") or "")
                key = (tcg, chain, url)
                if key in seen:
                    continue
                seen.add(key)
                raw_state = str(source.get("source_state") or "DISCOVERED_CANDIDATE")
                state = {
                    "VERIFIED_OFFICIAL": "OFFICIAL_VERIFIED", "KNOWN_ACTIVE": "MONITORABLE",
                    "MONITORABLE": "MONITORABLE", "BLOCKED_ROBOTS": "ROBOTS_BLOCKED",
                }.get(raw_state, raw_state if raw_state in COVERAGE_STATES else "UNSUPPORTED")
                inventory.append({
                    "tcg": tcg, "chain": chain, "display_name": source.get("name") or chain,
                    "official_url": url, "state": state, "declared_branches": 0,
                    "prefectures": [],
                    "official_alternative_paths": [],
                    "last_check": str(source.get("last_checked") or ""),
                    "last_success": str(source.get("last_success") or ""),
                    "failure_reason": str(source.get("health") or ""),
                    "monitoring_type": str(source.get("seed_type") or ""),
                    "discovered_from": str(source.get("seed_type") or ""),
                    "gap_checks": {
                        name: bool(source.get("last_checked")) for name in GAP_CHECKS
                    },
                })

    displayable = [
        item for item in discoveries
        if isinstance(item, dict)
        and verification_bucket(item.get("hit", {}).get("verification_status"))
        in {"confirmed", UNVERIFIED_RESTRICTED}
    ]
    applications = []
    for item in displayable:
        state = _period_state(item, now)
        if state not in {"CURRENT_APPLICATION", "RECENTLY_ENDED"}:
            continue
        applications.append({
            "tcg": _tcg(item), "chain": _chain(item), "prefecture": _prefecture(item),
            "state": state,
            "branch": str(item.get("hit", {}).get("branch") or item.get("hit", {}).get("store_branch") or item.get("hit", {}).get("name") or ""),
            "product": str(item.get("record", {}).get("product_name") or ""),
            "official_url": str(item.get("record", {}).get("article_url") or ""),
            "application_url": str(item.get("hit", {}).get("application_url") or item.get("hit", {}).get("url") or ""),
            "verification_status": verification_bucket(
                item.get("hit", {}).get("verification_status")
            ),
        })

    by_tcg: dict[str, Any] = {}
    for tcg in PRIORITY_TCG:
        sources = [row for row in inventory if row["tcg"] == tcg]
        apps = [row for row in applications if row["tcg"] == tcg]
        by_tcg[tcg] = {
            "known_chain_count": len({row["chain"] for row in sources}),
            "discovered_chain_count": len({row["chain"] for row in sources if row["state"] != "UNSUPPORTED"}),
            "verified_chain_count": len({row["chain"] for row in sources if row["state"] in {"OFFICIAL_VERIFIED", "MONITORABLE", "NO_CURRENT_APPLICATION"}}),
            "monitorable_chain_count": len({row["chain"] for row in sources if row["state"] in {"MONITORABLE", "NO_CURRENT_APPLICATION"}}),
            "active_chain_count": len({row["chain"] for row in apps if row["state"] == "CURRENT_APPLICATION"}),
            "recently_ended_chain_count": len({row["chain"] for row in apps if row["state"] == "RECENTLY_ENDED"}),
            "active_branch_count": len({(row["chain"], row["branch"]) for row in apps if row["state"] == "CURRENT_APPLICATION"}),
            "recently_ended_branch_count": len({(row["chain"], row["branch"]) for row in apps if row["state"] == "RECENTLY_ENDED"}),
            "confirmed_application_count": sum(
                row["verification_status"] == "confirmed" for row in apps
            ),
            "restricted_application_count": sum(
                row["verification_status"] == UNVERIFIED_RESTRICTED for row in apps
            ),
        }
    prefectures = {}
    for prefecture in PREFECTURES:
        apps = [row for row in applications if row["prefecture"] == prefecture]
        candidate_sources = [row for row in inventory if prefecture in row.get("prefectures", [])]
        prefectures[prefecture] = {
            "candidate": sum(int(row.get("declared_branches") or 0) for row in candidate_sources),
            "monitored": sum(row["state"] in {"MONITORABLE", "NO_CURRENT_APPLICATION"} for row in candidate_sources),
            "active": len({(row["chain"], row["branch"]) for row in apps if row["state"] == "CURRENT_APPLICATION"}),
            "recently_ended": len({(row["chain"], row["branch"]) for row in apps if row["state"] == "RECENTLY_ENDED"}),
        }
    active = [row for row in applications if row["state"] == "CURRENT_APPLICATION"]
    recent = [row for row in applications if row["state"] == "RECENTLY_ENDED"]
    branch_keys = {(row["chain"], row["branch"]) for row in active + recent}
    chain_counts = Counter(chain for chain, _branch in branch_keys)
    branch_count = len(branch_keys)
    return {
        "schema_version": 1, "generated_at": now.isoformat(timespec="seconds"),
        "target_branch_count": 100,
        "totals": {
            "inventory_source_count": len(inventory),
            "active_branch_count": len({(row["chain"], row["branch"]) for row in active}),
            "recently_ended_branch_count": len({(row["chain"], row["branch"]) for row in recent}),
            "active_plus_recently_ended_branch_count": branch_count,
            "target_gap": max(0, 100 - branch_count),
            "unique_chain_count": len(chain_counts),
            "unique_prefecture_count": len({row["prefecture"] for row in active + recent if row["prefecture"]}),
            "unique_product_count": len({row["product"] for row in active + recent if row["product"]}),
            "dominant_chain_ratio": round(max(chain_counts.values()) / sum(chain_counts.values()), 3) if chain_counts else 0.0,
            "confirmed_application_count": sum(
                row["verification_status"] == "confirmed" for row in applications
            ),
            "restricted_application_count": sum(
                row["verification_status"] == UNVERIFIED_RESTRICTED
                for row in applications
            ),
            "dashboard_application_count": len(applications),
        },
        "by_tcg": by_tcg, "by_prefecture": prefectures,
        "inventory": inventory, "applications": applications,
        "unresolved": [row for row in inventory if row["state"] in {"APP_REQUIRED", "SNS_ONLY", "ROBOTS_BLOCKED", "TERMS_RESTRICTED", "PARSER_NEEDED", "UNSUPPORTED"}],
    }


def save_production_coverage(report: dict[str, Any], path: Path | None = None) -> Path:
    destination = path or app_root() / "data" / "production_coverage.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(
        prefix="production_coverage_", suffix=".tmp", dir=destination.parent
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        Path(temporary_name).replace(destination)
    finally:
        Path(temporary_name).unlink(missing_ok=True)
    return destination
