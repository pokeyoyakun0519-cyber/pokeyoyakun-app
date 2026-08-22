"""Read-only Test4 audit for real Bandai official application pages.

This script never writes to the user's application data.  It fetches two
public official application pages and builds a temporary ProductStore.
"""
from __future__ import annotations

import json
import sys
import tempfile
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from core.application_dashboard import ApplicationDashboard
from core.bandai_official_applications import BandaiOfficialApplicationParser
from core.candidate_manager import CandidateManager
from core.card_labo_parser import CardLaboParser
from core.config_manager import ConfigManager
from core.product_store import ProductStore
from core.secure_https import build_https_opener


LIVE_CASES = {
    "onepiece": {
        "url": (
            "https://parks2.bandainamco-am.co.jp/category/ECCL00000054/"
            "ECCL00000054_20260822_25_004.html"
        ),
        "dashboard_now": "2026-08-22T12:00:00+09:00",
    },
    "dragon_ball_fusion_world": {
        "url": (
            "https://parks2.bandainamco-am.co.jp/category/TITLE/"
            "ECCL00000052_20260808_09_008.html"
        ),
        # The real application ended on Aug 2.  Aug 10 proves the unchanged
        # 14-day history path; at the actual Aug 22 audit it is correctly hidden.
        "dashboard_now": "2026-08-10T12:00:00+09:00",
    },
}


def fetch(url: str) -> str:
    request = urllib.request.Request(
        url, headers={"User-Agent": "PokeyoyaKun/1.25 OfficialWebAudit"}
    )
    with build_https_opener().open(request, timeout=30) as response:
        if int(getattr(response, "status", 200)) != 200:
            raise RuntimeError(f"official page returned HTTP {response.status}")
        return response.read().decode("utf-8", errors="replace")


def main() -> int:
    records = []
    for expected_tcg, case in LIVE_CASES.items():
        record = BandaiOfficialApplicationParser.parse(fetch(case["url"]), case["url"])
        if not record or record.get("tcg_key") != expected_tcg or not record.get("confirmed"):
            raise RuntimeError(f"official verification failed: {expected_tcg}")
        records.append(record)

    with tempfile.TemporaryDirectory(prefix="pokeyoya-test4-audit-") as directory:
        root = Path(directory)
        manager = CandidateManager(root)
        merged = manager.merge_application_discoveries(
            [{"record": record, "hit": record["hit"]} for record in records],
            matcher=CardLaboParser._matches_candidate,
        )
        dashboard = ApplicationDashboard(ProductStore(root), ConfigManager(root))
        output = {"storage_root": "temporary", "merge": merged, "records": []}
        for record in records:
            tcg_key = record["tcg_key"]
            now = datetime.fromisoformat(LIVE_CASES[tcg_key]["dashboard_now"])
            data = dashboard.build(
                tcg_filter=tcg_key, show_ended=True, period_filter="ended", now=now
            )
            if not data["rows"]:
                raise RuntimeError(f"dashboard path failed: {tcg_key}")
            row = data["rows"][0]
            output["records"].append({
                "tcg_key": tcg_key,
                "product_name": record["product_name"],
                "store_name": record["store_name"],
                "application_url": record["application_url"],
                "application_start_at": record["application_start_at"],
                "application_end_at": record["application_end_at"],
                "sales_mode": row["sales_mode"],
                "prefecture": row["prefecture"],
                "region": row["region"],
                "verification_status": row["verification_status"],
                "period_ended": row["period_ended"],
                "dashboard_rows": len(data["rows"]),
                "dashboard_now": now.isoformat(),
            })
        print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
