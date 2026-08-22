"""Test5 read-only live audit using only public official Web pages."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import argparse
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from core.application_dashboard import ApplicationDashboard  # noqa: E402
from core.candidate_manager import CandidateManager  # noqa: E402
from core.card_labo_parser import CardLaboParser  # noqa: E402
from core.config_manager import ConfigManager  # noqa: E402
from core.product_store import ProductStore  # noqa: E402
from core.retail_search_manager import RetailSearchManager  # noqa: E402


TCGS = {"pokemon", "onepiece", "dragon_ball_fusion_world"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="pokeyoya-test5-web-audit-") as directory:
        root = Path(directory)
        previous = os.environ.get("POKEYOYA_DATA_ROOT")
        os.environ["POKEYOYA_DATA_ROOT"] = str(root)
        try:
            searcher = RetailSearchManager()
            discoveries = searcher.discover_priority_applications(TCGS)
            candidates = CandidateManager(root)
            merged = candidates.merge_application_discoveries(
                discoveries, matcher=CardLaboParser._matches_candidate
            )
            dashboard = ApplicationDashboard(ProductStore(root), ConfigManager(root))
            snapshot = dashboard.build(show_ended=True, period_filter="all")
            diagnostics = dict(searcher.last_diagnostics.get("nationwide_web_monitor") or {})
            rows_by_tcg = {
                tcg: [row for row in snapshot.get("rows", []) if row.get("tcg_key") == tcg]
                for tcg in sorted(TCGS)
            }
            for tcg, rows in rows_by_tcg.items():
                if tcg in diagnostics.get("by_tcg", {}):
                    diagnostics["by_tcg"][tcg]["dashboard_rows"] = len(rows)
            traces = {}
            for tcg in sorted(TCGS):
                tcg_summary = diagnostics.get("by_tcg", {}).get(tcg, {})
                sources = [
                    item for item in diagnostics.get("sources", [])
                    if tcg in item.get("tcg", [])
                ]
                traces[tcg] = {
                    "source_checked": sum(bool(item.get("parent_urls_checked")) for item in sources),
                    "parser_success": sum(item.get("parser_result") == "success" for item in sources),
                    "candidate": int(tcg_summary.get("candidate_count", 0)),
                    "official_verified": int(tcg_summary.get("confirmed_count", 0)),
                    "confirmed": int(tcg_summary.get("confirmed_count", 0)),
                    "explicit_rejection_or_no_current": sum(
                        item.get("status") in {
                            "NO_CURRENT_APPLICATION", "HTTP_ERROR", "ACCESS_RESTRICTED",
                            "APP_REQUIRED", "SNS_ONLY", "UNSUPPORTED", "PARSER_OUTDATED",
                        }
                        for item in sources
                    ),
                    "dashboard_rows": len(rows_by_tcg[tcg]),
                    "statuses": {
                        status: sum(item.get("status") == status for item in sources)
                        for status in sorted({str(item.get("status")) for item in sources})
                    },
                }
            output = {
                "audited_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "storage_root": "temporary",
                "user_product_store_modified": False,
                "merge": merged,
                "diagnostics": diagnostics,
                "e2e_by_tcg": traces,
            }
            rendered = json.dumps(output, ensure_ascii=False, indent=2)
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(rendered, encoding="utf-8")
                print(json.dumps({
                    "output": str(args.output),
                    "summary": {key: value for key, value in diagnostics.items() if key != "sources"},
                    "e2e_by_tcg": traces,
                }, ensure_ascii=False, indent=2))
            else:
                print(rendered)
        finally:
            if previous is None:
                os.environ.pop("POKEYOYA_DATA_ROOT", None)
            else:
                os.environ["POKEYOYA_DATA_ROOT"] = previous
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
