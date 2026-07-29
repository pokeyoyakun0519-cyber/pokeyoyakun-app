import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
sys.path.insert(0, str(APP_DIR))

from core.application_dashboard import ApplicationDashboard
from core.application_site import has_application_evidence
from core.candidate_manager import CandidateManager
from core.hobby_station_parser import HobbyStationParser
from core.log_manager import LogManager
from core.product_store import ProductStore
from core.retail_search_manager import RetailSearchManager


def rss(*entries):
    rows = "".join(
        f"<url><loc>{url}</loc><lastmod>{modified}</lastmod></url>"
        for url, modified in entries
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"{rows}</urlset>"
    )


def article(
    *,
    title="遊戯王OCG TEST PACK 2026年8月8日(土)発売",
    body="1パック5枚入り：180円 1ボックス30パック入り：5,400円",
    links="",
    image="https://www.hbst.net/wordpress/wp-content/uploads/test.jpg",
):
    return f"""
    <html>
      <head>
        <meta property="og:title" content="{title}">
        <meta property="og:image" content="{image}">
      </head>
      <body>
        <section id="article" class="section article text-left">
          <div class="col-md-9 col-xs-12 text-left">
            <h2>{title}</h2>
            <div class="row content">
              <p>{body}</p>
              {links}
            </div>
          </div>
          <div class="col-md-3 col-xs-12">
            <p>ポケモンカードゲーム 抽選販売 応募期間</p>
          </div>
        </section>
        <section id="related-post">
          <p>ポケモンカードゲーム 抽選販売 応募期間</p>
        </section>
      </body>
    </html>
    """


def lottery_article(*, ended=False, application_url=True):
    title_prefix = "※応募は終了しました" if ended else ""
    link = (
        '<a href="https://livepocket.jp/e/test_01">抽選受付ページ</a>'
        if application_url else ""
    )
    return article(
        title=(
            f"〖2026.07.28〗{title_prefix}"
            "抽選販売「ポケモンカードゲームMEGA 拡張パック TEST」"
        ),
        body="""
        ポケモンカードゲームMEGA 拡張パック TEST
        ・発売予定日：2026年8月8日(土)
        ・販売価格：1BOX6,000円（税込）
        ■応募方法：LivePocketを使用したWEB抽選を行います。
        ■応募期間：2026年7月28日(火)12:00～8月5日(水)23:59まで
        ■当選発表：2026年8月7日(金)予定
        ■当選者購入期間：2026年8月8日(土)～8月14日(金)
        ■商品お受け取り期間：2026年8月8日(土)～8月21日(金)
        新潟店・福岡天神店限定です。
        お申し込みにはLivePocketの会員登録が必要です。
        公的な本人確認書類をお持ちください。
        ご購入は応募店舗の店頭のみです。
        """,
        links=link,
    )


class FakeFetcher:
    def __init__(self, mapping):
        self.mapping = mapping
        self.calls = []

    def __call__(self, url, _timeout):
        self.calls.append(url)
        value = self.mapping[url]
        if isinstance(value, BaseException):
            raise value
        return value


class HobbyStationParserTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.now = datetime(2026, 7, 30, 0, 0, tzinfo=timezone.utc)

    def tearDown(self):
        self.temporary.cleanup()

    def make_parser(self, fetcher=None, **kwargs):
        return HobbyStationParser(
            fetcher=fetcher,
            state_path=self.root / "config" / "hobby_station_state.json",
            log_manager=LogManager(self.root),
            request_interval_seconds=0,
            now_provider=lambda: self.now,
            **kwargs,
        )

    def test_rss_normal_and_duplicate_urls(self):
        xml = rss(
            ("https://www.hbst.net/?p=100", "2026-07-30T01:00:00+00:00"),
            ("https://www.hbst.net/?p=100", "2026-07-30T01:00:00+00:00"),
            ("https://www.hbst.net/?p=101", "2026-07-30T02:00:00+00:00"),
        )
        entries = HobbyStationParser.parse_rss(xml)
        self.assertEqual(2, len(entries))
        self.assertEqual("https://www.hbst.net/?p=100", entries[0]["url"])

    def test_rss_zero_and_broken_xml(self):
        self.assertEqual([], HobbyStationParser.parse_rss(""))
        self.assertEqual([], HobbyStationParser.parse_rss("<broken>"))

    def test_product_article(self):
        record = HobbyStationParser.parse_article_html(
            article(),
            "https://www.hbst.net/?p=100",
            now=self.now,
        )
        self.assertEqual("product_schedule", record["article_type"])
        self.assertEqual("yugioh", record["tcg_key"])
        self.assertEqual("2026-08-08", record["release_date"])
        self.assertEqual(5400, record["price"])
        self.assertTrue(record["image_url"].startswith("https://www.hbst.net/"))
        hit = HobbyStationParser._build_hit(record)
        self.assertFalse(has_application_evidence(hit))
        self.assertNotIn("application_url", hit)

    def test_open_lottery_article(self):
        record = HobbyStationParser.parse_article_html(
            lottery_article(),
            "https://www.hbst.net/?p=200",
            now=self.now,
        )
        self.assertEqual("application", record["article_type"])
        self.assertEqual("pokemon", record["tcg_key"])
        self.assertEqual("抽選受付中", record["status"])
        self.assertEqual(
            "https://livepocket.jp/e/test_01",
            record["application_url"],
        )
        self.assertTrue(record["application_start_at"])
        self.assertTrue(record["application_end_at"])
        self.assertTrue(record["result_announcement_at"])
        self.assertTrue(record["purchase_period"])
        self.assertTrue(record["receipt_period"])
        self.assertTrue(record["target_stores"])
        self.assertTrue(record["conditions"])
        self.assertTrue(has_application_evidence(
            HobbyStationParser._build_hit(record)
        ))

    def test_ended_lottery(self):
        record = HobbyStationParser.parse_article_html(
            lottery_article(ended=True),
            "https://www.hbst.net/?p=201",
            now=self.now,
        )
        self.assertEqual("終了済み", record["status"])

    def test_application_without_url_keeps_period_evidence(self):
        record = HobbyStationParser.parse_article_html(
            lottery_article(application_url=False),
            "https://www.hbst.net/?p=202",
            now=self.now,
        )
        self.assertEqual("", record["application_url"])
        hit = HobbyStationParser._build_hit(record)
        self.assertTrue(has_application_evidence(hit))
        self.assertEqual(
            "https://www.hbst.net/?p=202",
            hit["application_url"],
        )

    def test_multiple_supported_tcgs(self):
        cases = {
            "ポケモンカードゲーム": "pokemon",
            "ワンピースカードゲーム": "onepiece",
            "ガンダムカードゲーム": "gundam",
            "遊戯王OCG": "yugioh",
            "遊戯王ラッシュデュエル": "yugioh",
            "デュエル・マスターズ": "duelmasters",
            "ヴァイスシュヴァルツ": "weiss",
            "Magic: The Gathering": "mtg",
        }
        for label, expected in cases.items():
            with self.subTest(label=label):
                self.assertEqual(
                    expected,
                    HobbyStationParser.detect_tcg(f"{label} TEST"),
                )

    def test_unknown_tcg_and_missing_html_are_excluded(self):
        unknown = HobbyStationParser.parse_article_html(
            article(
                title="店舗営業時間のお知らせ",
                body="営業時間を変更します。",
            ),
            "https://www.hbst.net/?p=300",
            now=self.now,
        )
        self.assertEqual("general_news", unknown["article_type"])
        missing = HobbyStationParser.parse_article_html(
            "<html><body></body></html>",
            "https://www.hbst.net/?p=301",
            now=self.now,
        )
        self.assertEqual("excluded", missing["article_type"])

    def test_old_checked_article_is_not_fetched(self):
        state_path = self.root / "config" / "hobby_station_state.json"
        state_path.parent.mkdir(parents=True)
        state_path.write_text(json.dumps({
            "last_checked_at": "2026-07-30T03:00:00+00:00",
            "checked_urls": {
                "https://www.hbst.net/?p=400": "2026-07-29T01:00:00+00:00",
            },
        }), encoding="utf-8")
        fetcher = FakeFetcher({
            HobbyStationParser.RSS_URL: (
                200,
                rss((
                    "https://www.hbst.net/?p=400",
                    "2026-07-29T01:00:00+00:00",
                )),
                HobbyStationParser.RSS_URL,
            ),
        })
        parser = self.make_parser(fetcher)
        self.assertEqual([], parser.scan())
        self.assertEqual([HobbyStationParser.RSS_URL], fetcher.calls)
        self.assertEqual(0, parser.last_diagnostics["new_url_count"])

    def test_timeout_retries_once(self):
        fetcher = FakeFetcher({
            HobbyStationParser.RSS_URL: TimeoutError("timeout"),
        })
        parser = self.make_parser(fetcher, max_retries=1)
        self.assertEqual([], parser.scan())
        self.assertEqual(2, len(fetcher.calls))
        self.assertEqual(1, parser.last_diagnostics["http_failure_count"])

    def test_livepocket_is_never_fetched(self):
        article_url = "https://www.hbst.net/?p=500"
        fetcher = FakeFetcher({
            HobbyStationParser.RSS_URL: (
                200,
                rss((article_url, "2026-07-30T01:00:00+00:00")),
                HobbyStationParser.RSS_URL,
            ),
            article_url: (200, lottery_article(), article_url),
        })
        parser = self.make_parser(fetcher)
        records = parser.scan()
        self.assertEqual(1, len(records))
        self.assertEqual(
            [HobbyStationParser.RSS_URL, article_url],
            fetcher.calls,
        )
        self.assertFalse(any(
            "livepocket.jp" in url for url in fetcher.calls
        ))
        self.assertEqual(
            0,
            parser.last_diagnostics["livepocket_request_count"],
        )

    def test_scan_deduplicates_in_memory_and_classifies(self):
        product_url = "https://www.hbst.net/?p=600"
        lottery_url = "https://www.hbst.net/?p=601"
        fetcher = FakeFetcher({
            HobbyStationParser.RSS_URL: (
                200,
                rss(
                    (product_url, "2026-07-30T01:00:00+00:00"),
                    (lottery_url, "2026-07-30T02:00:00+00:00"),
                ),
                HobbyStationParser.RSS_URL,
            ),
            product_url: (200, article(), product_url),
            lottery_url: (200, lottery_article(), lottery_url),
        })
        parser = self.make_parser(fetcher)
        self.assertEqual(2, len(parser.scan()))
        self.assertEqual(2, len(parser.scan()))
        self.assertEqual(3, len(fetcher.calls))
        self.assertEqual(
            {"application": 1, "product_schedule": 1},
            parser.last_diagnostics["article_type_counts"],
        )

    def test_retail_manager_routes_to_dedicated_parser(self):
        manager = RetailSearchManager()
        manager._search_yodobashi = lambda _candidate: ([], "なし")
        manager.store_candidates.save_candidates = lambda: None
        hit = HobbyStationParser._build_hit(
            HobbyStationParser.parse_article_html(
                article(),
                "https://www.hbst.net/?p=700",
                now=self.now,
            )
        )
        plugin = {
            "id": "hobby_station",
            "name": "ホビーステーション",
            "mode": "dedicated",
            "source": "builtin",
            "tcg": ["yugioh"],
        }
        with patch(
            "core.retail_search_manager.enabled_plugins_for_tcg",
            return_value=[plugin],
        ), patch.object(
            manager.hobby_station,
            "search_candidate",
            return_value=([hit], "専用1件"),
        ) as dedicated, patch.object(
            manager,
            "_search_generic_plugin",
        ) as generic:
            hits, _ = manager.search_candidate({
                "name": "遊戯王OCG TEST PACK",
                "tcg_key": "yugioh",
            })
        self.assertEqual(1, len(hits))
        dedicated.assert_called_once()
        generic.assert_not_called()

    def test_product_store_and_dashboard_separate_product_and_application(self):
        manager = CandidateManager(self.root)
        manager.add_manual_candidate(
            "ポケモンカードゲームMEGA 拡張パック TEST",
            tcg_key="pokemon",
        )
        candidate = manager.load_candidates()[0]
        application = HobbyStationParser._build_hit(
            HobbyStationParser.parse_article_html(
                lottery_article(),
                "https://www.hbst.net/?p=800",
                now=self.now,
            )
        )
        manager.update_search_result(
            candidate["id"],
            hits=[application],
            messages=["ホビーステーション1件"],
        )
        products = ProductStore(self.root).load_products()
        self.assertEqual(1, len(products))
        dashboard = ApplicationDashboard(
            store=ProductStore(self.root)
        )
        dashboard.change_tracker.root = self.root
        self.assertEqual(
            1,
            len(dashboard.build(show_ended=True)["rows"]),
        )

        product_only = HobbyStationParser._build_hit(
            HobbyStationParser.parse_article_html(
                article(
                    title=(
                        "ガンダムカードゲーム TEST PACK "
                        "2026年8月8日(土)発売"
                    )
                ),
                "https://www.hbst.net/?p=801",
                now=self.now,
            )
        )
        self.assertFalse(has_application_evidence(product_only))


if __name__ == "__main__":
    unittest.main()
