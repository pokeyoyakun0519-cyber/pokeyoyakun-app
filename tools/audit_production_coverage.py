from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from core.autonomous_source_registry import OfficialSourceCandidateStore
from core.production_coverage import build_production_coverage, save_production_coverage


def _discoveries_from_rows(rows: list[dict]) -> list[dict]:
    output = []
    for row in rows:
        if not row.get("confirmed"):
            continue
        output.append({
            "record": {
                "tcg_key": row.get("tcg"), "source_id": row.get("source"),
                "product_name": row.get("product"), "article_url": row.get("official_url"),
            },
            "hit": {
                "tcg_key": row.get("tcg"), "site_key": row.get("chain"),
                "branch": row.get("branch"), "prefecture": row.get("prefecture", ""),
                "application_url": row.get("application_url"),
                "application_end_at": row.get("deadline"),
                "verification_status": "confirmed",
            },
        })
    return output


def _discoveries_from_applications(rows: list[dict]) -> list[dict]:
    output = []
    for row in rows:
        output.append({
            "record": {
                "tcg_key": row.get("tcg"), "source_id": row.get("chain"),
                "product_name": row.get("product"), "article_url": row.get("official_url"),
            },
            "hit": {
                "tcg_key": row.get("tcg"), "site_key": row.get("chain"),
                "branch": row.get("branch"), "prefecture": row.get("prefecture", ""),
                "application_url": row.get("application_url"),
                "verification_status": "confirmed",
                "_coverage_state": row.get("state"),
            },
        })
    return output


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create production coverage metrics from a real-Web audit artifact."
    )
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--registry-root", type=Path, default=ROOT)
    args = parser.parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    nationwide = payload.get("dedicated_diagnostics", {}).get(
        "nationwide_web_monitor", {}
    )
    previous = payload.get("production_coverage", {})
    discoveries = (
        _discoveries_from_applications(previous.get("applications", []))
        if previous.get("applications") else _discoveries_from_rows(payload.get("rows", []))
    )
    report = build_production_coverage(
        discoveries,
        autonomous_registry=OfficialSourceCandidateStore(args.registry_root),
        nationwide_diagnostics=nationwide,
    )
    save_production_coverage(report, args.output)
    print(json.dumps(report["totals"], ensure_ascii=False, indent=2))
    for tcg, values in report["by_tcg"].items():
        print(tcg, json.dumps(values, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
