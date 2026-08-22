from __future__ import annotations

import argparse
import json
import tempfile
from collections import Counter
from pathlib import Path

from core.autonomous_source_registry import OfficialSourceCandidateStore
from core.autonomous_web_discovery import AutonomousApplicationSourceDiscovery
from core.safe_discovery_fetcher import RequestBudget, SafeDiscoveryFetcher
from core.web_application_sources import WebApplicationSourceRegistry


TCGS = (
    "pokemon", "onepiece", "dragon_ball_fusion_world", "yugioh", "gundam",
    "union_arena", "duelmasters", "weiss",
)
AUDIT_SOURCE_IDS = (
    "card_labo", "hobby_station", "batoroco", "plays", "otakarasouko",
    "cardbox", "tsutaya", "furuichi", "bookoff", "premium_bandai",
    "bandai_official_shop", "biccamera", "joshin", "rakuten_books",
    "dragon_star", "seagull", "nyuka_now",
)


def source_inventory(registry: OfficialSourceCandidateStore, results: list[dict]) -> list[dict]:
    web_records = WebApplicationSourceRegistry().sources()
    by_id: dict[str, list[dict]] = {}
    for item in web_records:
        keys = {
            str(item.get("canonical_store_id", "")),
            str(item.get("store_group_id", "")),
        }
        for key in keys - {""}:
            by_id.setdefault(key, []).append(item)
    autonomous = {str(item.get("id")): item for item in registry.records}
    output = []
    for source_id in AUDIT_SOURCE_IDS:
        records = by_id.get(source_id, [])
        seed = autonomous.get(source_id, {})
        observed = [item for item in results if item.get("source_id") == source_id]
        statuses = sorted({str(item.get("status")) for item in observed if item.get("status")})
        classes = sorted({str(item.get("source_class")) for item in records if item.get("source_class")})
        output.append({
            "id": source_id,
            "source_exists": bool(records or seed),
            "trust_tier": seed.get("trust_tier", "TIER_A_OFFICIAL" if records else ""),
            "supported_tcg": sorted(set(seed.get("supported_tcg", [])) | {
                key for record in records for key, value in record.get("tcg_support", {}).items()
                if value in {"supported", "partial"}
            }),
            "parser": sorted({str(item.get("extractor", "none")) for item in records}),
            "scheduler_connected": any(item.get("source_class") in {"WEB_DIRECT", "WEB_FORM", "WEB_TO_STORE", "STORE_DIRECT"} for item in records) or bool(seed.get("enabled")),
            "fetch_status": statuses,
            "robots": "blocked" if "ROBOTS_BLOCKED" in statuses else "allowed_or_not_checked",
            "application_detection": sum(int(item.get("applications", 0)) for item in observed),
            "branch_count": max([int(item.get("branch_count", 0)) for item in records] or [0]),
            "confirmed_promotion": any(int(item.get("applications", 0)) > 0 for item in observed),
            "monitoring": seed.get("source_state") or ",".join(classes) or "UNSUPPORTED",
        })
    return output


def build_report(*, global_max: int = 60, per_domain_max: int = 5) -> dict:
    with tempfile.TemporaryDirectory(prefix="pokeyoya_autonomous_audit_") as folder:
        root = Path(folder)
        registry = OfficialSourceCandidateStore(root)
        fetcher = SafeDiscoveryFetcher(
            root,
            budget=RequestBudget(
                global_max=global_max,
                per_domain_max=per_domain_max,
            ),
            ttl_hours=1,
        )
        engine = AutonomousApplicationSourceDiscovery(
            root,
            registry=registry,
            fetcher=fetcher,
            max_depth=2,
            max_urls_per_source=5,
        )
        result = engine.run(set(TCGS))
        applications = result["discoveries"]
        sources = result["diagnostics"].get("sources", [])
        by_tcg = {}
        for tcg in TCGS:
            configured = [
                item for item in registry.records
                if tcg in item.get("supported_tcg", [])
            ]
            selected = [
                item for item in applications
                if item.get("record", {}).get("tcg_key") == tcg
            ]
            checked_ids = {
                str(item.get("source_id"))
                for item in sources
                if int(item.get("checked_urls", 0)) > 0
            }
            by_tcg[tcg] = {
                "known_candidates": len(configured),
                "official_verified": sum(
                    item.get("trust_tier") == "TIER_A_OFFICIAL"
                    for item in configured
                ),
                "monitorable": sum(
                    item.get("source_state") in {"KNOWN_ACTIVE", "MONITORABLE"}
                    and bool(item.get("enabled"))
                    for item in configured
                ),
                "actually_checked": sum(
                    str(item.get("id")) in checked_ids
                    for item in configured
                ),
                "application_candidates": len(selected),
                "confirmed_applications": sum(
                    item.get("hit", {}).get("verification_status") == "confirmed"
                    for item in selected
                ),
                "sources": [
                    {
                        "id": item.get("id"),
                        "name": item.get("name"),
                        "domain": item.get("official_domains", [""])[0],
                        "state": item.get("source_state"),
                        "trust_tier": item.get("trust_tier"),
                    }
                    for item in configured
                ],
            }
        states = Counter(str(item.get("source_state")) for item in registry.records)
        return {
            "audit_type": "read_only_real_web",
            "temporary_data_root": True,
            "by_tcg": by_tcg,
            "metrics": result["diagnostics"],
            "new_official_candidates": result["source_candidates"],
            "applications": applications,
            "requested_source_inventory": source_inventory(registry, sources),
            "source_gaps": {
                "robots_blocked": states["BLOCKED_ROBOTS"],
                "app_required": states["APP_REQUIRED"],
                "sns_only": states["SNS_ONLY"],
                "unsupported": states["UNSUPPORTED"],
                "temporarily_failed": states["TEMPORARILY_FAILED"],
            },
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--global-max", type=int, default=60)
    parser.add_argument("--per-domain-max", type=int, default=5)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = build_report(
        global_max=max(1, min(100, args.global_max)),
        per_domain_max=max(1, min(10, args.per_domain_max)),
    )
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
