"""Read-only Test5 audit of saved application deadline fields."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from core.application_period import ApplicationPeriodParser  # noqa: E402
from core.application_status import evaluate_application_period  # noqa: E402


JST = timezone(timedelta(hours=9))
DATE_ONLY = re.compile(r"^\s*(?:20\d{2}[-/年])?\d{1,2}(?:[-/月])\d{1,2}日?\s*$")
YEARLESS = re.compile(r"^\s*\d{1,2}(?:[-/月])\d{1,2}日?")
HAS_TIME = re.compile(r"\d{1,2}(?::|時)\d{2}")


def _old_period_ended(site: dict, now: datetime) -> bool:
    if str(site.get("status") or "").strip() in {
        "受付終了", "抽選受付終了", "応募終了", "予約受付終了", "販売終了",
    }:
        return True
    value = str(site.get("application_end_at") or "").strip()
    if not value:
        return False
    try:
        end = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    if end.tzinfo is None:
        end = end.replace(tzinfo=JST)
    return now.astimezone(JST) > end.astimezone(JST)


def audit(path: Path, *, now: datetime) -> dict[str, int | str]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    products = raw if isinstance(raw, list) else []
    metrics: dict[str, int | str] = {
        "path": str(path), "products": len(products), "application_records": 0,
        "application_end": 0, "application_end_at": 0,
        "date_parse_success": 0, "date_parse_failure": 0,
        "past_date_active_before": 0, "past_date_active_after": 0,
        "over_14_days_visible_before": 0, "over_14_days_visible_after": 0,
        "date_only": 0, "yearless": 0, "time_missing": 0, "invalid_date": 0,
    }
    parser = ApplicationPeriodParser()
    for product in products:
        if not isinstance(product, dict):
            continue
        for raw_site in product.get("sites", []):
            if not isinstance(raw_site, dict):
                continue
            site = dict(raw_site)
            raw_end = str(site.get("application_end") or "").strip()
            raw_end_at = str(site.get("application_end_at") or "").strip()
            if not raw_end and not raw_end_at:
                continue
            metrics["application_records"] += 1
            metrics["application_end"] += bool(raw_end)
            metrics["application_end_at"] += bool(raw_end_at)
            source_value = raw_end or raw_end_at
            metrics["date_only"] += bool(DATE_ONLY.fullmatch(source_value))
            metrics["yearless"] += bool(YEARLESS.match(source_value))
            metrics["time_missing"] += not bool(HAS_TIME.search(source_value))
            evidence_text = "\n".join(
                str(site.get(key) or "")
                for key in ("period_evidence", "application_period", "order_period")
            )
            enriched = parser.enrich_site(site, evidence_text, now=now)
            parsed_value = str(enriched.get("application_end_at") or "").strip()
            try:
                parsed_end = datetime.fromisoformat(parsed_value.replace("Z", "+00:00"))
                if parsed_end.tzinfo is None:
                    parsed_end = parsed_end.replace(tzinfo=JST)
            except ValueError:
                parsed_end = None
            if parsed_end is None:
                metrics["date_parse_failure"] += 1
                metrics["invalid_date"] += 1
                continue
            metrics["date_parse_success"] += 1
            old_ended = _old_period_ended(site, now)
            new_ended = bool(evaluate_application_period(enriched, now=now)["period_ended"])
            if parsed_end < now:
                metrics["past_date_active_before"] += not old_ended
                metrics["past_date_active_after"] += not new_ended
            if parsed_end + timedelta(days=14) < now:
                metrics["over_14_days_visible_before"] += not old_ended
                metrics["over_14_days_visible_after"] += not new_ended
    return metrics


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("products_json", type=Path)
    parser.add_argument("--now", default="")
    args = parser.parse_args()
    now = datetime.fromisoformat(args.now) if args.now else datetime.now(JST)
    if now.tzinfo is None:
        now = now.replace(tzinfo=JST)
    print(json.dumps(audit(args.products_json, now=now), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
