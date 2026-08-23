from __future__ import annotations

import argparse
import csv
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path


TCGS = {
    "pokemon", "onepiece", "dragon_ball_fusion_world", "yugioh",
    "gundam", "union_arena", "duelmasters", "weiss",
}


def run(output_json: Path, output_csv: Path) -> dict:
    output_json = output_json.resolve()
    output_csv = output_csv.resolve()
    isolated = tempfile.TemporaryDirectory(prefix="pokeyoya_coverage_")
    os.environ["LOCALAPPDATA"] = isolated.name
    os.environ["POKEYOYA_DATA_ROOT"] = str(Path(isolated.name) / "PokeyoyaKun")
    original_cwd = Path.cwd()
    os.chdir(isolated.name)
    from core.application_coverage_report import build_application_coverage
    from core.application_dashboard import ApplicationDashboard
    from core.autonomous_web_discovery import AutonomousApplicationSourceDiscovery
    from core.candidate_manager import CandidateManager
    from core.product_store import ProductStore
    from core.retail_search_manager import RetailSearchManager

    manager = RetailSearchManager()
    web = manager.discover_web_application_candidates(TCGS)
    dedicated = manager.discover_priority_applications(TCGS)
    discoveries = AutonomousApplicationSourceDiscovery._deduplicate([
        *web.get("verified_discoveries", []), *dedicated,
    ])
    root = Path(isolated.name) / "PokeyoyaKun"
    try:
        production_coverage = json.loads(
            (root / "data" / "production_coverage.json").read_text(encoding="utf-8")
        )
    except (OSError, ValueError, TypeError):
        production_coverage = {}
    candidates = CandidateManager(root)
    merge = candidates.merge_application_discoveries(
        discoveries, matcher=manager.card_labo._matches_candidate,
    )
    store = ProductStore(root)
    dashboard = ApplicationDashboard()
    dashboard.store = store
    dashboard_rows = dashboard.build(show_ended=False)["rows"]
    gaps = []
    registry = manager.autonomous_discovery.registry
    reason_by_state = {
        "APP_REQUIRED": "APP_REQUIRED", "SNS_ONLY": "SNS_ONLY",
        "BLOCKED_ROBOTS": "ROBOTS", "UNSUPPORTED": "UNKNOWN",
    }
    for source in registry.records:
        reason = reason_by_state.get(str(source.get("source_state")))
        if reason:
            gaps.append({"source_id": source.get("id"), "reason": reason,
                         "supported_tcg": source.get("supported_tcg", [])})
    diagnostics = web.get("diagnostics", {}).get("autonomous_discovery", {})
    for source in diagnostics.get("sources", []):
        status = str(source.get("status", ""))
        reason = "ROBOTS" if status == "ROBOTS_BLOCKED" else "PARSER_NEEDED" if status == "PARSER_OUTDATED" else "UNKNOWN" if status in {"HTTP_ERROR", "SECURITY_REJECTED"} else ""
        if reason:
            seed = next((item for item in registry.records if item.get("id") == source.get("source_id")), {})
            gaps.append({"source_id": source.get("source_id"), "reason": reason,
                         "supported_tcg": seed.get("supported_tcg", [])})
    nationwide_sources = manager.last_diagnostics.get("nationwide_web_monitor", {}).get("sources", [])
    nationwide_reasons = {
        "ACCESS_RESTRICTED": "ROBOTS", "APP_REQUIRED": "APP_REQUIRED",
        "SNS_ONLY": "SNS_ONLY", "UNSUPPORTED": "UNKNOWN",
        "PARSER_OUTDATED": "PARSER_NEEDED",
    }
    for source in nationwide_sources:
        reason = nationwide_reasons.get(str(source.get("status", "")))
        if reason:
            gaps.append({"source_id": source.get("chain") or source.get("source"),
                         "reason": reason, "supported_tcg": source.get("tcg", [])})
    report = build_application_coverage(
        discoveries, dashboard_rows=dashboard_rows, source_gaps=gaps,
        known_current=dedicated,
    )
    learned_candidates = {
        str(item.get("id")): item for item in web.get("source_candidates", [])
        if str(item.get("id", "")).startswith("discovered_")
    }
    report.update({
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "audit_type": "read_only_isolated_real_web",
        "isolated_user_data": True,
        "merge_result": merge,
        "autonomous_source_candidates": list(learned_candidates.values()),
        "discovery_diagnostics": diagnostics,
        "dedicated_diagnostics": manager.last_diagnostics,
        "production_coverage": production_coverage,
        "source_gaps": gaps,
    })
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    fields = ["tcg", "product", "chain", "branch", "source", "state", "confirmed",
              "dashboard_visible", "failure_reason", "official_url", "application_url",
              "application_route", "deadline"]
    with output_csv.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows({key: row.get(key, "") for key in fields} for row in report["rows"])
    os.chdir(original_cwd)
    isolated.cleanup()
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", type=Path, default=Path("reports/autonomous_discovery_coverage.json"))
    parser.add_argument("--csv", type=Path, default=Path("reports/autonomous_discovery_coverage.csv"))
    args = parser.parse_args()
    report = run(args.json, args.csv)
    print(json.dumps({"by_tcg": report["by_tcg"], "totals": report["totals"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
