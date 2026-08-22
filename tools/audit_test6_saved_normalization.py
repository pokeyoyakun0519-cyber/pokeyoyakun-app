"""Audit legacy saved application periods in a disposable ProductStore copy."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from core.application_dashboard import ApplicationDashboard  # noqa: E402
from core.application_period import JST, normalize_saved_application_period  # noqa: E402
from core.config_manager import ConfigManager  # noqa: E402
from core.product_store import ProductStore  # noqa: E402


def _site_key(product: dict, site: dict) -> tuple[str, str, str]:
    return (
        str(product.get("name") or "").strip().rstrip("」").strip(),
        str(site.get("name") or site.get("site_key") or "").strip(),
        str(site.get("url") or site.get("application_url") or ""),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--now", default="")
    args = parser.parse_args()
    now = datetime.fromisoformat(args.now) if args.now else datetime.now(JST)
    if now.tzinfo is None:
        now = now.replace(tzinfo=JST)

    products_path = args.root / "data" / "products.json"
    raw_products = json.loads(products_path.read_text(encoding="utf-8"))
    legacy: list[dict] = []
    for product in raw_products if isinstance(raw_products, list) else []:
        if not isinstance(product, dict):
            continue
        for site in product.get("sites", []):
            if not isinstance(site, dict) or str(site.get("application_end_at") or "").strip():
                continue
            if not any(str(site.get(key) or "").strip() for key in (
                "application_end", "application_period", "order_period",
            )):
                continue
            normalized = normalize_saved_application_period(site, product=product, now=now)
            legacy.append({
                "key": _site_key(product, site),
                "product": str(product.get("name") or ""),
                "site": str(site.get("name") or ""),
                "normalized": normalized,
            })

    store = ProductStore(args.root)
    loaded = store.load_products()
    loaded_sites = {}
    for product in loaded:
        for site in product.get("sites", []):
            key = _site_key(product, site)
            loaded_sites[key] = dict(site)
    failed = [
        item for item in legacy
        if not str(item["normalized"].get("application_end_at") or "")
    ]
    dashboard = ApplicationDashboard(store, ConfigManager(args.root)).build(
        show_ended=True, now=now
    )
    storm = []
    for source in legacy:
        key = source["key"]
        if "ストームエメラルダ" not in source["product"]:
            continue
        site = source["normalized"]
        storm.append({
            "site": source["site"],
            "application_end_at": str(site.get("application_end_at") or ""),
            "time_confirmed": bool(site.get("application_end_time_confirmed")),
            "retained_after_product_filters": key in loaded_sites,
            "visible": any(
                str(row.get("store_name") or "") == key[1]
                and str(row.get("site_url") or "") == key[2]
                for row in dashboard.get("rows", [])
            ),
        })
    by_tcg = Counter(str(row.get("tcg_key") or "unknown") for row in dashboard.get("rows", []))
    print(json.dumps({
        "storage": "disposable_copy",
        "raw_products": len(raw_products),
        "legacy_deadline_sites": len(legacy),
        "normalized_by_same_load_normalizer": len(legacy) - len(failed),
        "normalization_failed": len(failed),
        "product_store_diagnostic_count": int(
            store.last_load_diagnostics.get("normalized_application_deadlines", 0)
        ),
        "dashboard_rows": len(dashboard.get("rows", [])),
        "dashboard_rows_by_tcg": dict(by_tcg),
        "storm_emerald_legacy_sites": storm,
    }, ensure_ascii=False, indent=2))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
