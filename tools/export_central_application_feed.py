from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from core.central_application_feed import build_central_feed


def main() -> int:
    parser = argparse.ArgumentParser(description="Export an isolated Central Application Feed")
    parser.add_argument("--coverage", type=Path, required=True)
    parser.add_argument("--restricted", type=Path, default=APP / "resources" / "pokemon_restricted_campaigns.json")
    parser.add_argument("--official", type=Path, default=APP / "resources" / "official_central_campaigns.json")
    parser.add_argument("--discovery-sources", type=Path, default=APP / "resources" / "phase10_discovery_sources.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--now", help="ISO-8601 timestamp used for reproducible audits")
    args = parser.parse_args()
    coverage = json.loads(args.coverage.read_text(encoding="utf-8"))
    restricted = json.loads(args.restricted.read_text(encoding="utf-8"))
    official = json.loads(args.official.read_text(encoding="utf-8"))
    discovery = json.loads(args.discovery_sources.read_text(encoding="utf-8"))
    now = datetime.fromisoformat(args.now) if args.now else None
    feed = build_central_feed(coverage, restricted, official, discovery, now=now)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(json.dumps(feed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(args.output)
    print(json.dumps(feed["metrics"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
