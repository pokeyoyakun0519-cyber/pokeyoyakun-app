from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
sys.path.insert(0, str(APP_DIR))

from core.konami_style_parser import KonamiStyleParser
from core.log_manager import LogManager
from core.retail_search_manager import RetailSearchManager


def list_card(
    *,
    product_id: str = "123",
    title: str = "遊戯王OCG TEST PACK",
    price: str = "5,500",
    status: str = "予約受付中",
) -> str:
    return f"""
    <li class="grid-col5">
      <a href="/products/detail.php?product_id={product_id}">
        <img class="picture" src="/upload/{product_id}.jpg" alt="{title}">
      </a>
      <p class="item-name return-words">{title}</p>
      <p class="item-price">{price} 円（税込）</p>
      <p class="item-tag">{status}</p>
    </li>
    """


def list_page(cards: str = "", total: int = 1) -> str:
    return f"""
    <p class="item-count"><span class="num">{total}</span>件</p>
    <ul class="main-item-list grid-content">{cards}</ul>
    """


def detail_page(
    *,
    title: str = "遊戯王OCG TEST PACK",
    code: str = "CG-TEST",
    release: str = "2026年10月10日",
    status: str = "予約注文する",
) -> str:
    return f"""
    <html><head>
      <meta property="og:image"
            content="https://eccdn-endpoint01.azureedge.net/test.jpg">
    </head><body>
      <h2 class="hdg-text return-words">{title}</h2>
      <dl>
        <dt>商品番号</dt><dd>{code}</dd>
        <dt>発売日</dt><dd>{release}</dd>
        <dt>希望小売価格</dt><dd>5,500円（税込）</dd>
      </dl>
      <button>{status}</button>
    </body></html>
    """


class FakeFetcher:
    def __init__(self, handler):
        self.handler = handler
        self.calls: list[str] = []

    def __call__(self, url: str, timeout: float):
        self.calls.append(url)
        result = self.handler(url)
        if isinstance(result, Exception):
            raise result
        return result


class KonamiStyleParserTest(unittest.TestCase):
    def make_parser(self, fetcher, directory, **kwargs):
        return KonamiStyleParser(
            fetcher=fetcher,
            log_manager=LogManager(Path(directory)),
            request_interval_seconds=0,
            **kwargs,
        )

    def test_normal_html_extracts_supported_fields(self):
        products, total = KonamiStyleParser.parse_list_html(
            list_page(list_card(status="販売中"))
        )
        self.assertEqual(total, 1)
        self.assertEqual(len(products), 1)
        self.assertEqual(products[0]["title"], "遊戯王OCG TEST PACK")
        self.assertEqual(products[0]["price"], 5500)
        self.assertEqual(products[0]["status"], "販売中")
        self.assertTrue(products[0]["url"].startswith("https://"))

    def test_zero_results_do_not_fabricate_products(self):
        products, total = KonamiStyleParser.parse_list_html(
            list_page("", total=0)
        )
        self.assertEqual(products, [])
        self.assertEqual(total, 0)

    def test_multiple_search_terms_have_safe_priority(self):
        terms = KonamiStyleParser.build_search_terms({
            "name": "遊戯王OCG TEST PACK【BOX】",
            "product_code": "CG-TEST",
        })
        self.assertEqual(terms[0], "CG-TEST")
        self.assertIn("遊戯王OCG TEST PACK【BOX】", terms)
        self.assertIn("遊戯王OCG TEST PACK", terms)
        self.assertEqual(terms[-1], "遊戯王OCG")

    def test_paging_finds_a_product_on_second_page(self):
        unrelated = "".join(
            list_card(product_id=str(index), title=f"関連なし {index}")
            for index in range(10)
        )

        def handler(url):
            if "detail.php" in url:
                return 200, detail_page(), url
            if "pageno=2" in url:
                return 200, list_page(list_card(), total=11), url
            return 200, list_page(unrelated, total=11), url

        with tempfile.TemporaryDirectory() as directory:
            fetcher = FakeFetcher(handler)
            parser = self.make_parser(fetcher, directory)
            hits, _ = parser.search_candidate({
                "name": "遊戯王OCG TEST PACK",
                "product_code": "CG-TEST",
                "tcg_key": "yugioh",
            })
        self.assertEqual(len(hits), 1)
        self.assertTrue(any("pageno=2" in url for url in fetcher.calls))

    def test_product_code_match_has_highest_confidence(self):
        score, reason = KonamiStyleParser._match_confidence(
            {"name": "別名", "product_code": "CG-TEST"},
            {"title": "商品", "product_code": "CG-TEST"},
        )
        self.assertEqual(score, 1.0)
        self.assertEqual(reason, "")

    def test_product_name_match_is_accepted(self):
        score, _ = KonamiStyleParser._match_confidence(
            {"name": "遊戯王OCG TEST PACK"},
            {"title": "遊戯王OCG TEST PACK【限定版】"},
        )
        self.assertGreaterEqual(score, KonamiStyleParser.MIN_CONFIDENCE)

    def test_pack_count_and_official_prefix_do_not_require_exact_title(self):
        score, _ = KonamiStyleParser._match_confidence(
            {
                "name": (
                    "遊戯王OCGデュエルモンスターズ "
                    "デッキビルドパック グロリアス・ヴィクターズ"
                )
            },
            {
                "title": (
                    "デッキビルドパック "
                    "－グロリアス・ヴィクターズ－（15Pack）"
                )
            },
        )
        self.assertGreaterEqual(score, KonamiStyleParser.MIN_CONFIDENCE)

    def test_unrelated_product_is_not_matched(self):
        score, _ = KonamiStyleParser._match_confidence(
            {"name": "LIMIT OVER COLLECTION THE HEROES"},
            {"title": "遊戯王ラッシュデュエル 希望のリーチェ"},
        )
        self.assertLess(score, KonamiStyleParser.MIN_CONFIDENCE)

    def test_duplicate_across_search_terms_is_saved_once(self):
        def handler(url):
            if "detail.php" in url:
                return 200, detail_page(), url
            return 200, list_page(list_card()), url

        with tempfile.TemporaryDirectory() as directory:
            fetcher = FakeFetcher(handler)
            parser = self.make_parser(fetcher, directory)
            hits, _ = parser.search_candidate({
                "name": "遊戯王OCG TEST PACK",
                "product_code": "CG-TEST",
                "tcg_key": "yugioh",
            })
        self.assertEqual(len(hits), 1)
        detail_calls = [url for url in fetcher.calls if "detail.php" in url]
        self.assertEqual(len(detail_calls), 1)

    def test_sold_out_is_not_application_evidence(self):
        product = KonamiStyleParser.parse_list_html(
            list_page(list_card(status="売り切れ"))
        )[0][0]
        hit = KonamiStyleParser._build_hit(product, 0.95)
        self.assertTrue(hit["sold_out"])
        self.assertNotIn("application_url", hit)

    def test_on_sale_product_is_not_fabricated_as_application(self):
        product = KonamiStyleParser.parse_list_html(
            list_page(list_card(status="販売中"))
        )[0][0]
        hit = KonamiStyleParser._build_hit(product, 0.95)
        self.assertTrue(hit["on_sale"])
        self.assertNotIn("application_url", hit)

    def test_unknown_release_date_remains_empty(self):
        parsed = KonamiStyleParser.parse_detail_html(
            detail_page(release="")
        )
        self.assertEqual(parsed["release_date"], "")
        self.assertEqual(parsed["release_date_text"], "")

    def test_approximate_release_date_is_kept_without_inventing_a_day(self):
        parsed = KonamiStyleParser.parse_detail_html(
            detail_page(release="2026年12月中旬より順次お届け予定")
        )
        self.assertEqual(parsed["release_date"], "")
        self.assertEqual(
            parsed["release_date_text"],
            "2026年12月中旬より順次お届け予定",
        )

    def test_timeout_retries_only_to_configured_limit(self):
        fetcher = FakeFetcher(lambda url: TimeoutError("test timeout"))
        with tempfile.TemporaryDirectory() as directory:
            parser = self.make_parser(
                fetcher, directory, max_retries=1
            )
            hits, _ = parser.search_candidate({
                "name": "TEST",
                "tcg_key": "yugioh",
            })
        self.assertEqual(hits, [])
        self.assertEqual(len(fetcher.calls), 4)

    def test_detail_release_date_and_reservation_are_preserved(self):
        parsed = KonamiStyleParser.parse_detail_html(
            detail_page()
            + '<h2 class="hdg-text return-words">おすすめ商品</h2>'
        )
        self.assertEqual(parsed["release_date"], "2026-10-10")
        self.assertEqual(parsed["product_code"], "CG-TEST")
        self.assertEqual(parsed["status"], "予約受付中")
        self.assertEqual(parsed["title"], "遊戯王OCG TEST PACK")

    def test_mojibake_candidate_name_is_repaired(self):
        broken = "—V‹Y‰¤OCGƒfƒ…ƒGƒ‹ƒ‚ƒ“ƒXƒ^[ƒY"
        self.assertIn("遊戯王OCG", KonamiStyleParser.repair_mojibake(broken))

    def test_retail_manager_routes_konami_to_dedicated_parser(self):
        manager = RetailSearchManager()
        product = KonamiStyleParser.parse_list_html(
            list_page(list_card(status="販売中"))
        )[0][0]
        hit = KonamiStyleParser._build_hit(product, 0.95)
        with patch.object(
            manager,
            "_search_yodobashi",
            return_value=([], "ヨドバシ: 0件"),
        ), patch(
            "core.retail_search_manager.enabled_plugins_for_tcg",
            return_value=[{
                "id": "konami_style",
                "name": "KONAMI STYLE",
                "mode": "dedicated",
                "source": "builtin",
            }],
        ), patch.object(
            manager.konami_style,
            "search_candidate",
            return_value=([hit], "KONAMI STYLE: 1件"),
        ), patch.object(manager, "_search_generic_plugin") as generic:
            hits, _ = manager.search_candidate({
                "name": "遊戯王OCG TEST PACK",
                "tcg_key": "yugioh",
            })
        self.assertEqual(len(hits), 1)
        generic.assert_not_called()


if __name__ == "__main__":
    unittest.main()
