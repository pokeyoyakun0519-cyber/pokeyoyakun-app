from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from core.source_manager import SourceManager  # noqa: E402


def evaluate_catalog(products: list[dict], baseline: dict) -> dict:
    urls = {str(item.get("official_url", "")) for item in products}
    critical = [str(value) for value in baseline.get("critical_urls", [])]
    missing = [url for url in critical if url not in urls]
    minimum = int(baseline.get("minimum_catalog_count", 0) or 0)
    return {
        "catalog_count": len(products),
        "minimum_catalog_count": minimum,
        "critical_url_count": len(critical),
        "critical_recall": (
            round((len(critical) - len(missing)) / len(critical), 4)
            if critical else 1.0
        ),
        "missing_critical_urls": missing,
        "structure_drop_detected": len(products) < minimum or bool(missing),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Low-frequency read-only audit of the two priority official sites."
    )
    parser.add_argument("--live", action="store_true")
    parser.add_argument(
        "--summary", action="store_true",
        help="商品明細を省略し、継続監査の件数・critical URL結果だけを表示します。",
    )
    args = parser.parse_args()
    if not args.live:
        raise SystemExit("実通信する場合だけ --live を指定してください。")

    manager = SourceManager()
    baseline = json.loads(
        (ROOT / "app" / "resources" / "priority_source_audit_baseline.json")
        .read_text(encoding="utf-8")
    )
    request_count = 0
    original = manager._fetch_page

    def counted(url: str):
        nonlocal request_count
        result = original(url)
        request_count += int(not result.get("cache_hit", False))
        return result

    manager._fetch_page = counted
    started = time.perf_counter()
    pokemon_top = counted("https://www.pokemon-card.com/")
    pokemon, pokemon_details = manager._extract_pokemon_official_products(
        pokemon_top["html"], pokemon_top.get("url", "https://www.pokemon-card.com/"),
        "ポケモンカード公式",
    )
    onepiece_top = counted("https://www.onepiece-cardgame.com/products/?view=normal")
    onepiece, onepiece_details, duplicates = manager._extract_onepiece_official_products(
        onepiece_top["html"], onepiece_top.get("url", "https://www.onepiece-cardgame.com/products/?view=normal"),
        "ONE PIECEカードゲーム公式",
    )
    result = {
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "http_requests": request_count,
        "pokemon": {
            "count": len(pokemon), "detail_requests": pokemon_details,
            "audit": evaluate_catalog(pokemon, baseline["pokemon"]),
            "products": [{key: item.get(key) for key in ("name", "release_date", "official_product_id", "product_code", "image_url", "official_url")} for item in pokemon],
        },
        "onepiece": {
            "count": len(onepiece), "detail_requests": onepiece_details,
            "duplicates": duplicates,
            "audit": evaluate_catalog(onepiece, baseline["onepiece"]),
            "products": [{key: item.get(key) for key in ("name", "release_date", "product_code", "image_url", "official_url")} for item in onepiece],
        },
    }
    if args.summary:
        result["pokemon"].pop("products", None)
        result["onepiece"].pop("products", None)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if any(
        result[key]["audit"]["structure_drop_detected"]
        for key in ("pokemon", "onepiece")
    ):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
