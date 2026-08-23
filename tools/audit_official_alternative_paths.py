from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from core.retail_search_manager import RetailSearchManager
from core.web_application_sources import OFFICIAL_ALTERNATIVE_PATHS


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit public official alternatives without bypassing robots policy."
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    manager = RetailSearchManager()
    rows = []
    for chain, paths in OFFICIAL_ALTERNATIVE_PATHS.items():
        for path in paths:
            allowed = manager._robots_allowed(path["url"])
            result = manager._fetch(path["url"]) if allowed else {
                "ok": False, "status": "ROBOTS_BLOCKED", "url": path["url"],
            }
            rows.append({
                "chain": chain, "url": path["url"], "kind": path["kind"],
                "declared_status": path["status"], "ok": bool(result.get("ok")),
                "status": str(result.get("status") or ""),
                "final_url": str(result.get("url") or path["url"]),
                "bytes": len(str(result.get("html") or "").encode("utf-8")),
            })
    payload = {
        "schema_version": 1, "policy": "production_monitor_user_agent",
        "rows": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
