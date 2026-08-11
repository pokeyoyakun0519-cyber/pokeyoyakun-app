from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from core.source_manager import SourceManager  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Low-frequency read-only audit of the two priority official sites."
    )
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    if not args.live:
        raise SystemExit("実通信する場合だけ --live を指定してください。")

    manager = SourceManager()
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
    print(json.dumps({
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "http_requests": request_count,
        "pokemon": {
            "count": len(pokemon), "detail_requests": pokemon_details,
            "products": [{key: item.get(key) for key in ("name", "release_date", "official_product_id", "product_code", "image_url", "official_url")} for item in pokemon],
        },
        "onepiece": {
            "count": len(onepiece), "detail_requests": onepiece_details,
            "duplicates": duplicates,
            "products": [{key: item.get(key) for key in ("name", "release_date", "product_code", "image_url", "official_url")} for item in onepiece],
        },
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
