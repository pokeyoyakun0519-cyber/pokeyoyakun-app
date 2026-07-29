from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
sys.path.insert(0, str(APP_DIR))

from core.bushiroad_store_parser import BushiroadStoreParser
from core.log_manager import LogManager
from core.retail_search_manager import RetailSearchManager


def card(
    *,
    handle: str = "ws-test",
    title: str = "ヴァイスシュヴァルツ ブースターパック TEST【BOX】",
    state: str = "予約受付中",
    available: bool = True,
    price: str = "5,280",
    image: str = "//bushiroad-store.com/cdn/shop/files/test_{width}x.webp",
) -> str:
    return f"""
    <div class="product-item product--items-wishlist"
         data-handle="{handle}" data-title="{title}"
         data-available="{'true' if available else 'false'}">
      <a class="product-item__image-wrapper"
         href="/collections/ws-tcg/products/{handle}">
        <img data-src="{image}" alt="{title}">
      </a>
      <div class="product-item__info">
        <a class="product-item__title"
           href="/collections/ws-tcg/products/{handle}">{title}</a>
        <span class="price">{price}円 <span>(税込)</span></span>
        <p>{state}</p>
      </div>
    </div>
    """


def detail(
    *,
    release_date: str = "2026年10月10日(土)",
    image: str = "https://bushiroad-store.com/cdn/shop/files/detail.jpg",
) -> str:
    return f"""
    <html><head>
      <meta property="og:image:secure_url" content="{image}">
    </head><body>
      <section class="product">
        <p><strong>【発売日】{release_date}</strong></p>
      </section>
    </body></html>
    """


class FakeFetcher:
    def __init__(self, responses: dict[str, tuple[int, str, str] | Exception]):
        self.responses = responses
        self.calls: list[str] = []

    def __call__(self, url: str, timeout: float):
        self.calls.append(url)
        response = self.responses[url]
        if isinstance(response, Exception):
            raise response
        return response


class BushiroadStoreParserTest(unittest.TestCase):
    def make_parser(self, fetcher: FakeFetcher, directory: str, **kwargs):
        return BushiroadStoreParser(
            fetcher=fetcher,
            log_manager=LogManager(Path(directory)),
            request_interval_seconds=0,
            **kwargs,
        )

    def test_normal_html_extracts_all_supported_fields(self):
        products, next_url = BushiroadStoreParser.parse_collection_html(
            card(state="販売中")
        )
        self.assertEqual(next_url, "")
        self.assertEqual(len(products), 1)
        product = products[0]
        self.assertEqual(product["title"], "ヴァイスシュヴァルツ ブースターパック TEST【BOX】")
        self.assertEqual(product["url"], "https://bushiroad-store.com/collections/ws-tcg/products/ws-test")
        self.assertEqual(product["status"], "販売中")
        self.assertEqual(product["price"], 5280)
        self.assertIn("600x.webp", product["image_url"])

    def test_zero_products_are_returned_without_fabrication(self):
        with tempfile.TemporaryDirectory() as directory:
            fetcher = FakeFetcher({
                BushiroadStoreParser.COLLECTION_URL: (
                    200,
                    '<html><body><div class="product-list"></div></body></html>',
                    BushiroadStoreParser.COLLECTION_URL,
                ),
            })
            parser = self.make_parser(fetcher, directory)
            hits, _ = parser.search_candidate({"name": "TEST", "tcg_key": "weiss"})
            self.assertEqual(hits, [])
            self.assertEqual(parser.last_diagnostics["detected_count"], 0)
            self.assertEqual(
                parser.last_diagnostics["excluded_reasons"][
                    "商品カード構造を検出できない"
                ],
                1,
            )

    def test_missing_product_card_structure_is_rejected(self):
        malformed = """
        <div class="product-item" data-title="名前だけの商品">
          <a href="/products/missing-handle">商品URL</a>
        </div>
        """
        products, _ = BushiroadStoreParser.parse_collection_html(malformed)
        self.assertEqual(products, [])

    def test_timeout_retries_once_and_reports_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            class TimeoutFetcher:
                def __init__(self):
                    self.calls = 0

                def __call__(self, url, timeout):
                    self.calls += 1
                    raise TimeoutError("test timeout")

            fetcher = TimeoutFetcher()
            parser = BushiroadStoreParser(
                fetcher=fetcher,
                log_manager=LogManager(Path(directory)),
                request_interval_seconds=0,
                max_retries=1,
            )
            hits, _ = parser.search_candidate({"name": "TEST", "tcg_key": "weiss"})
            self.assertEqual(hits, [])
            self.assertEqual(fetcher.calls, 2)
            self.assertEqual(
                parser.last_diagnostics["excluded_reasons"]["一覧取得失敗"],
                1,
            )

    def test_duplicate_products_are_saved_once(self):
        html = card() + card()
        with tempfile.TemporaryDirectory() as directory:
            fetcher = FakeFetcher({
                BushiroadStoreParser.COLLECTION_URL: (
                    200, html, BushiroadStoreParser.COLLECTION_URL
                ),
                "https://bushiroad-store.com/collections/ws-tcg/products/ws-test": (
                    200,
                    detail(release_date=""),
                    "https://bushiroad-store.com/collections/ws-tcg/products/ws-test",
                ),
            })
            parser = self.make_parser(fetcher, directory)
            hits, _ = parser.search_candidate({
                "name": "ヴァイスシュヴァルツ ブースターパック TEST",
                "tcg_key": "weiss",
            })
            self.assertEqual(len(hits), 1)
            self.assertEqual(
                parser.last_diagnostics["excluded_reasons"]["商品URL重複"],
                1,
            )

    def test_reservation_is_application_evidence(self):
        product = BushiroadStoreParser.parse_collection_html(
            card(state="予約受付中")
        )[0][0]
        hit = BushiroadStoreParser._build_hit(product)
        self.assertTrue(hit["reservation_open"])
        self.assertEqual(hit["status"], "予約受付中")
        self.assertEqual(hit["application_url"], hit["product_url"])

    def test_sold_out_is_preserved_without_fabricated_application_url(self):
        product = BushiroadStoreParser.parse_collection_html(
            card(state="売切", available=False)
        )[0][0]
        hit = BushiroadStoreParser._build_hit(product)
        self.assertTrue(hit["sold_out"])
        self.assertEqual(hit["status"], "売り切れ")
        self.assertNotIn("application_url", hit)

    def test_unknown_release_date_remains_empty(self):
        parsed = BushiroadStoreParser.parse_detail_html(
            detail(release_date="")
        )
        self.assertEqual(parsed["release_date"], "")
        self.assertTrue(parsed["image_url"].endswith("detail.jpg"))

    def test_paging_and_detail_are_limited_and_deduplicated(self):
        page_two = "https://bushiroad-store.com/collections/ws-tcg?page=2"
        first = card(handle="first", title="ヴァイスシュヴァルツ TEST") + (
            f'<link rel="next" href="{page_two}">'
        )
        second = card(handle="second", title="ヴァイスシュヴァルツ OTHER")
        first_detail = "https://bushiroad-store.com/collections/ws-tcg/products/first"
        with tempfile.TemporaryDirectory() as directory:
            fetcher = FakeFetcher({
                BushiroadStoreParser.COLLECTION_URL: (
                    200, first, BushiroadStoreParser.COLLECTION_URL
                ),
                page_two: (200, second, page_two),
                first_detail: (
                    200,
                    detail(release_date="2026年10月10日"),
                    first_detail,
                ),
            })
            parser = self.make_parser(fetcher, directory)
            hits, _ = parser.search_candidate({
                "name": "ヴァイスシュヴァルツ TEST",
                "tcg_key": "weiss",
            })
            self.assertEqual(len(hits), 1)
            self.assertEqual(hits[0]["release_date"], "2026-10-10")
            self.assertEqual(parser.last_diagnostics["collection_page_count"], 2)
            self.assertEqual(parser.last_diagnostics["detail_checked_count"], 1)
            self.assertEqual(len(fetcher.calls), len(set(fetcher.calls)))

    def test_retail_manager_routes_only_bushiroad_to_dedicated_parser(self):
        manager = RetailSearchManager()
        dedicated_hit = BushiroadStoreParser._build_hit(
            BushiroadStoreParser.parse_collection_html(card(state="販売中"))[0][0]
        )
        with patch.object(
            manager,
            "_search_yodobashi",
            return_value=([], "ヨドバシ: 0件"),
        ), patch(
            "core.retail_search_manager.enabled_plugins_for_tcg",
            return_value=[{
                "id": "bushiroad_store",
                "name": "ブシロード オンラインストア",
                "mode": "public_html",
                "source": "builtin",
            }],
        ), patch.object(
            manager.bushiroad_store,
            "search_candidate",
            return_value=([dedicated_hit], "専用: 1件"),
        ), patch.object(manager, "_search_generic_plugin") as generic:
            hits, _ = manager.search_candidate({
                "name": "ヴァイスシュヴァルツ ブースターパック TEST",
                "tcg_key": "weiss",
            })
        self.assertEqual(len(hits), 1)
        generic.assert_not_called()


if __name__ == "__main__":
    unittest.main()
