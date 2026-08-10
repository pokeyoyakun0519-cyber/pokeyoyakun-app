from __future__ import annotations

import json
import tempfile
import unittest
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from core.application_site import has_application_evidence
from core.card_labo_parser import CardLaboParser
from core.retail_search_manager import RetailSearchManager


NOW = datetime(2026, 7, 30, 3, 0, tzinfo=timezone.utc)


def rss(*ids: int) -> str:
    items = "".join(
        (
            "<item>"
            f"<title>記事{article_id}</title>"
            f"<link>https://www.c-labo.jp/blog/{article_id}/</link>"
            "<pubDate>Thu, 30 Jul 2026 01:00:00 +0000</pubDate>"
            "</item>"
        )
        for article_id in ids
    )
    return f"<rss><channel>{items}</channel></rss>"


def listing(*ids: int) -> str:
    return "<html><body>" + "".join(
        (
            f'<a href="https://www.c-labo.jp/blog/{article_id}/">'
            f"記事{article_id}</a>"
        )
        for article_id in ids
    ) + "</body></html>"


def article(
    *,
    title: str = (
        "〖8月7日発売〗『ポケモンカードゲーム MEGA 拡張パック "
        "テストパック』抽選販売のお知らせ"
    ),
    heading: str = "なんば店の 店舗ブログ",
    body: str | None = None,
    external_url: str = "",
    image_only: bool = False,
) -> str:
    if body is None:
        body = """
        〈開催店舗〉
        ・カードラボ なんば店
        〈販売方法・対象商品〉
        人気商品のため抽選販売とします。
        発売日：2026年8月7日(金)
        商品名：ポケモンカードゲーム MEGA 拡張パック テストパック
        販売価格：6,000円（税込）
        応募期間：2026年7月30日 12:00～8月2日 23:59
        当選発表：2026年8月3日
        当選者購入期間：2026年8月7日～8月9日
        店頭でのお受取が可能な方。身分証明書が必要です。
        """
    image = '<img src="/reservation.png" alt="">' if image_only else ""
    link = f'<a href="{external_url}">応募はこちら</a>' if external_url else ""
    return f"""
    <html>
      <head>
        <title>{title} - カードラボ</title>
        <meta property="og:title" content="{title}">
      </head>
      <body>
        <h2>{heading}</h2>
        <h1>{title}</h1>
        <article>{body}{image}{link}</article>
      </body>
    </html>
    """


def calendar_html() -> str:
    return """
    <html><head><title>2026年 TCG発売日カレンダー</title></head>
    <body>
      <h3>7月31日(金)発売</h3>
      <table>
        <tr><th>カテゴリ</th><th>商品名</th><th>価格(税込)</th></tr>
        <tr><td>ポケモン</td><td>ストームエメラルダ</td><td>200円</td></tr>
        <tr><td>遊戯王RD</td><td>ユニオン・ベース</td><td>264円</td></tr>
      </table>
      <h3>8月7日(金)発売</h3>
      <table>
        <tr><td>MTG</td><td>ホビット プレリリースパック</td><td>4,400円</td></tr>
      </table>
    </body></html>
    """


class Fetcher:
    def __init__(self, responses):
        self.responses = dict(responses)
        self.calls: list[str] = []

    def __call__(self, url: str, timeout: float):
        self.calls.append(url)
        value = self.responses.get(url)
        if isinstance(value, BaseException):
            raise value
        if value is None:
            raise urllib.error.URLError("missing fixture")
        if isinstance(value, tuple):
            return value
        return 200, value, url


class CardLaboParserTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def parser(self, fetcher=None, **kwargs):
        return CardLaboParser(
            fetcher=fetcher,
            state_path=self.root / "config" / "card_labo_state.json",
            request_interval_seconds=0,
            now_provider=lambda: NOW,
            **kwargs,
        )

    def test_rss_normal_deduplicates_and_limits_to_ten(self):
        entries = CardLaboParser.parse_rss(rss(*range(1, 13), 1))
        self.assertEqual(10, len(entries))
        self.assertEqual("1", CardLaboParser._article_id(entries[0]["url"]))

    def test_rss_zero_and_broken_xml(self):
        self.assertEqual([], CardLaboParser.parse_rss("<rss><channel/></rss>"))
        self.assertEqual([], CardLaboParser.parse_rss("<broken"))

    def test_blog_listing_supplements_rss_miss(self):
        fetcher = Fetcher({
            CardLaboParser.RSS_URL: rss(1),
            CardLaboParser.BLOG_URL: listing(1, 2),
            CardLaboParser.CALENDAR_URL: calendar_html(),
            "https://www.c-labo.jp/blog/1/": article(),
            "https://www.c-labo.jp/blog/2/": article(
                title="〖通常販売〗ポケモンカードゲーム テスト商品",
                body=(
                    "カードラボ なんば店にて新品販売。"
                    "商品名：ポケモンカードゲーム テスト商品\n"
                    "発売日：2026年8月7日\n価格：500円（税込）"
                ),
            ),
        })
        parser = self.parser(fetcher)
        parser.scan()
        self.assertEqual(1, parser.last_diagnostics["blog_supplement_count"])
        self.assertEqual(2, parser.last_diagnostics["parsed_url_count"])

    def test_second_page_only_when_known_id_not_reached(self):
        state_path = self.root / "config" / "card_labo_state.json"
        state_path.parent.mkdir(parents=True)
        state_path.write_text(json.dumps({
            "checked_article_ids": ["99"],
            "calendar_checked_date": "2026-07-30",
            "calendar_records": [],
        }), encoding="utf-8")
        fetcher = Fetcher({
            CardLaboParser.RSS_URL: rss(3),
            CardLaboParser.BLOG_URL: listing(3),
            CardLaboParser.BLOG_PAGE_2_URL: listing(99),
            "https://www.c-labo.jp/blog/3/": article(),
        })
        self.parser(fetcher).scan()
        self.assertIn(CardLaboParser.BLOG_PAGE_2_URL, fetcher.calls)

        state_path.write_text(json.dumps({
            "checked_article_ids": ["2"],
            "calendar_checked_date": "2026-07-30",
            "calendar_records": [],
        }), encoding="utf-8")
        fetcher2 = Fetcher({
            CardLaboParser.RSS_URL: rss(3),
            CardLaboParser.BLOG_URL: listing(3, 2),
            "https://www.c-labo.jp/blog/3/": article(),
        })
        self.parser(fetcher2).scan()
        self.assertNotIn(CardLaboParser.BLOG_PAGE_2_URL, fetcher2.calls)

    def test_lottery_article_extracts_supported_fields(self):
        record = CardLaboParser.parse_article_html(
            article(),
            "https://www.c-labo.jp/shop/namba/blog/10/",
            published_at="Thu, 30 Jul 2026 01:00:00 +0000",
            now=NOW,
        )
        self.assertEqual("lottery", record["article_type"])
        self.assertEqual("pokemon", record["tcg_key"])
        self.assertEqual("なんば店", record["store_name"])
        self.assertEqual(6000, record["price"])
        self.assertEqual("2026-08-07", record["release_date"])
        self.assertEqual("受付中", record["status"])
        self.assertTrue(record["application_evidence"])
        self.assertIn("本人確認", record["conditions"])

    def test_store_reservation_article(self):
        record = CardLaboParser.parse_article_html(
            article(
                title="〖予約受付〗遊戯王OCG テストBOX",
                body=(
                    "開催店舗：カードラボ なんば店\n"
                    "商品名：遊戯王OCG テストBOX\n"
                    "新品商品の店頭予約受付です。\n"
                    "予約受付期間：2026年7月30日～8月1日\n"
                    "発売日：2026年8月8日\n価格：3,000円（税込）"
                ),
            ),
            "https://www.c-labo.jp/shop/namba/blog/11/",
            now=NOW,
        )
        self.assertEqual("reservation", record["article_type"])
        self.assertEqual("受付中", record["status"])

    def test_resale_article_is_distinct(self):
        record = CardLaboParser.parse_article_html(
            article(
                title="『ONE PIECEカードゲーム 再販BOX』再販売抽選",
                body=(
                    "開催店舗：カードラボ なんば店\n"
                    "対象商品：ONE PIECEカードゲーム 再販BOX\n"
                    "再販売分を抽選販売します。\n"
                    "応募期間：2026年7月30日～8月1日\n"
                    "当選発表：2026年8月2日\n発売日：2026年8月5日"
                ),
            ),
            "https://www.c-labo.jp/shop/namba/blog/12/",
            now=NOW,
        )
        self.assertEqual("resale", record["article_type"])

    def test_regular_sale_is_not_application(self):
        record = CardLaboParser.parse_article_html(
            article(
                title="ガンダムカードゲーム 新品通常販売のお知らせ",
                body=(
                    "開催店舗：カードラボ なんば店\n"
                    "商品名：ガンダムカードゲーム テスト商品\n"
                    "新品通常販売です。発売日：2026年8月7日\n"
                    "価格：1,000円（税込）"
                ),
            ),
            "https://www.c-labo.jp/shop/namba/blog/13/",
            now=NOW,
        )
        self.assertEqual("regular_sale", record["article_type"])
        self.assertFalse(record["application_evidence"])
        self.assertFalse(has_application_evidence(
            CardLaboParser._build_hit(record)
        ))

    def test_ended_lottery(self):
        record = CardLaboParser.parse_article_html(
            article(body=(
                "開催店舗：カードラボ なんば店\n"
                "対象商品：ポケモンカードゲーム 終了商品\n"
                "抽選販売。応募期間：2026年7月20日～7月29日\n"
                "当選発表：2026年7月30日"
            )),
            "https://www.c-labo.jp/shop/namba/blog/14/",
            now=NOW,
        )
        self.assertEqual("終了済み", record["status"])

    def test_no_external_url_uses_official_article_as_application_url(self):
        url = "https://www.c-labo.jp/shop/namba/blog/15/"
        record = CardLaboParser.parse_article_html(
            article(),
            url,
            now=NOW,
        )
        self.assertEqual(url, record["application_url"])

    def test_social_share_button_is_not_application_url(self):
        url = "https://www.c-labo.jp/blog/150/"
        html = article().replace(
            "</article>",
            '<a href="https://twitter.com/share">ツイート</a></article>',
        )
        record = CardLaboParser.parse_article_html(html, url, now=NOW)
        self.assertEqual(url, record["application_url"])

    def test_footer_keywords_do_not_exclude_article_body(self):
        html = article() + (
            "<footer><a>買取情報</a><a>デッキレシピ</a>"
            "<a>対戦結果</a></footer>"
        )
        record = CardLaboParser.parse_article_html(
            html,
            "https://www.c-labo.jp/blog/151/",
            now=NOW,
        )
        self.assertEqual("lottery", record["article_type"])

    def test_x_link_is_saved_without_tracking(self):
        record = CardLaboParser.parse_article_html(
            article(external_url="https://x.com/c_labo/status/123?utm_source=test"),
            "https://www.c-labo.jp/shop/namba/blog/16/",
            now=NOW,
        )
        self.assertEqual(
            "https://x.com/c_labo/status/123",
            record["application_url"],
        )

    def test_livepocket_link_is_saved(self):
        record = CardLaboParser.parse_article_html(
            article(external_url="https://t.livepocket.jp/e/test"),
            "https://www.c-labo.jp/shop/namba/blog/17/",
            now=NOW,
        )
        self.assertEqual(
            "https://t.livepocket.jp/e/test",
            record["application_url"],
        )

    def test_external_hosts_are_never_fetched(self):
        fetcher = Fetcher({
            CardLaboParser.RSS_URL: rss(18),
            CardLaboParser.BLOG_URL: listing(18),
            CardLaboParser.CALENDAR_URL: calendar_html(),
            "https://www.c-labo.jp/blog/18/": article(
                external_url="https://t.livepocket.jp/e/test"
            ),
        })
        parser = self.parser(fetcher)
        parser.scan()
        self.assertTrue(all(
            "www.c-labo.jp" in url for url in fetcher.calls
        ))
        self.assertEqual(
            0,
            parser.last_diagnostics["external_host_request_count"],
        )

    def test_store_slug_and_headings_agree(self):
        record = CardLaboParser.parse_article_html(
            article(),
            "https://www.c-labo.jp/shop/namba/blog/19/",
            now=NOW,
        )
        self.assertEqual("なんば店", record["store_name"])
        self.assertEqual("namba", record["store_slug"])

    def test_store_mismatch_is_needs_review(self):
        record = CardLaboParser.parse_article_html(
            article(heading="池袋店の 店舗ブログ"),
            "https://www.c-labo.jp/shop/namba/blog/20/",
            now=NOW,
        )
        self.assertEqual("needs_review", record["article_type"])
        self.assertEqual("店舗表記不一致", record["needs_review_reason"])

    def test_all_supported_tcgs(self):
        cases = {
            "ポケモンカードゲーム": ("pokemon", ""),
            "ONE PIECEカードゲーム": ("onepiece", ""),
            "ガンダムカードゲーム": ("gundam", ""),
            "遊戯王OCG": ("yugioh", "ocg"),
            "遊戯王ラッシュデュエル": ("yugioh", "rush"),
            "デュエル・マスターズ": ("duelmasters", ""),
            "ヴァイスシュヴァルツ": ("weiss", ""),
            "Magic: The Gathering": ("mtg", ""),
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(expected, CardLaboParser.detect_tcg(text))

    def test_yugioh_ocg_and_rush_are_distinct(self):
        ocg = CardLaboParser.parse_calendar_html(
            calendar_html()
        )
        rush = next(item for item in ocg if item["tcg_key"] == "yugioh")
        self.assertEqual("rush", rush["tcg_variant"])
        self.assertEqual("遊戯王ラッシュデュエル", rush["tcg"])

    def test_image_only_information_is_needs_review(self):
        record = CardLaboParser.parse_article_html(
            article(
                title="〖予約情報〗カードラボなんば店予約受付中商品",
                body=(
                    "開催店舗：カードラボ なんば店\n"
                    "新品予約情報です。店頭予約受付中です。"
                ),
                image_only=True,
            ),
            "https://www.c-labo.jp/shop/namba/blog/21/",
            now=NOW,
        )
        self.assertEqual("needs_review", record["article_type"])
        self.assertTrue(record["image_only"])

    def test_purchase_and_deck_articles_are_excluded(self):
        for title in (
            "ポケモンカードゲーム 高価買取表",
            "遊戯王OCG 優勝デッキレシピ",
            "ヴァイスシュヴァルツ デッキ販売情報",
        ):
            with self.subTest(title=title):
                self.assertEqual(
                    "excluded",
                    CardLaboParser.classify_article(
                        title,
                        "買取価格や対戦結果のお知らせ",
                        "pokemon",
                    ),
                )

    def test_duplicate_article_is_fetched_once(self):
        fetcher = Fetcher({
            CardLaboParser.RSS_URL: rss(22, 22),
            CardLaboParser.BLOG_URL: listing(22, 22),
            CardLaboParser.CALENDAR_URL: calendar_html(),
            "https://www.c-labo.jp/blog/22/": article(),
        })
        parser = self.parser(fetcher)
        parser.scan()
        self.assertEqual(
            1,
            fetcher.calls.count("https://www.c-labo.jp/blog/22/"),
        )

    def test_timeout_retries_once(self):
        class TimeoutFetcher:
            def __init__(self):
                self.calls = 0

            def __call__(self, url, timeout):
                self.calls += 1
                raise TimeoutError("timeout")

        fetcher = TimeoutFetcher()
        parser = self.parser(fetcher, max_retries=1)
        self.assertEqual([], parser.scan())
        self.assertEqual(6, fetcher.calls)
        self.assertGreaterEqual(
            parser.last_diagnostics["http_failure_count"],
            2,
        )

    def test_missing_html_is_excluded(self):
        record = CardLaboParser.parse_article_html(
            "<html><body></body></html>",
            "https://www.c-labo.jp/blog/23/",
            now=NOW,
        )
        self.assertEqual("excluded", record["article_type"])

    def test_release_calendar_products(self):
        records = CardLaboParser.parse_calendar_html(calendar_html())
        self.assertEqual(3, len(records))
        pokemon = records[0]
        self.assertEqual("product_info", pokemon["article_type"])
        self.assertEqual("2026-07-31", pokemon["release_date"])
        self.assertEqual(200, pokemon["price"])
        self.assertFalse(pokemon["application_evidence"])

    def test_release_calendar_deduplicates_category_and_date_views(self):
        html = calendar_html().replace(
            "</body>",
            """
            <h3>9月26日(土)発売</h3>
            <table>
              <tr><th>発売日</th><th>商品名</th><th>価格(税抜)</th></tr>
              <tr><td>7月31日(金)</td><td>ストームエメラルダ</td><td>200円</td></tr>
            </table>
            </body>
            """,
        )
        records = CardLaboParser.parse_calendar_html(html)
        pokemon = [
            item for item in records
            if item["product_name"] == "ストームエメラルダ"
        ]
        self.assertEqual(1, len(pokemon))
        self.assertEqual("2026-07-31", pokemon[0]["release_date"])

    def test_product_article_is_not_application(self):
        record = CardLaboParser.parse_article_html(
            article(
                title="ポケモンカードゲーム 新商品情報",
                body=(
                    "開催店舗：カードラボ なんば店\n"
                    "商品名：ポケモンカードゲーム 新商品\n"
                    "発売日：2026年8月7日\n価格：200円（税込）"
                ),
            ),
            "https://www.c-labo.jp/shop/namba/blog/24/",
            now=NOW,
        )
        self.assertEqual("product_info", record["article_type"])
        self.assertFalse(record["application_evidence"])
        self.assertFalse(has_application_evidence(
            CardLaboParser._build_hit(record)
        ))

    def test_retail_manager_routes_card_labo_to_dedicated_parser(self):
        manager = RetailSearchManager()
        plugin = {
            "id": "card_labo",
            "name": "カードラボ",
            "mode": "dedicated",
            "source": "builtin",
            "tcg": ["pokemon"],
        }
        hit = CardLaboParser._build_hit(
            CardLaboParser.parse_article_html(
                article(),
                "https://www.c-labo.jp/shop/namba/blog/25/",
                now=NOW,
            )
        )
        with patch(
            "core.retail_search_manager.enabled_plugins_for_tcg",
            return_value=[plugin],
        ), patch.object(
            manager.card_labo,
            "search_candidate",
            return_value=([hit], "カードラボ1件"),
        ) as dedicated, patch.object(
            manager,
            "_search_generic_plugin",
        ) as generic, patch.object(
            manager,
            "_search_pokemon_center",
            return_value=([], "skip"),
        ), patch.object(
            manager,
            "_search_yodobashi",
            return_value=([], "skip"),
        ):
            hits, _ = manager.search_candidate({
                "name": "テストパック",
                "tcg_key": "pokemon",
            })
        self.assertEqual(1, len(hits))
        dedicated.assert_called_once()
        generic.assert_not_called()


if __name__ == "__main__":
    unittest.main()
