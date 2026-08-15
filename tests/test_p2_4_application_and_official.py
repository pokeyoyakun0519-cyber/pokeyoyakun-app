from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QTabBar


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
sys.path.insert(0, str(APP_DIR))

from core.application_dashboard import ApplicationDashboard
from core.gmail_result_service import GmailResultService
from core.gundam_official_extractor import GundamOfficialExtractor
from core.lottery_manager import LotteryManager
from core.onepiece_official_extractor import OnePieceOfficialExtractor
from core.product_store import ProductStore
from core.source_manager import SourceManager
from core.tcg_categories import normalize_key
from ui.application_dashboard_page import ApplicationDashboardPage


ONEPIECE_HTML = """
<html lang="ja"><body>
<li class="linkListColBox" data-cat="boosters">
 <a href="/products/op17.html" class="linkListColItem">
  <h4 class="linkListColTitle">ブースターパック 海賊島【OP-17】</h4>
  <time class="newsDate" datetime="2026-08-01"></time>
  <img src="../images/op17.png">
 </a>
</li>
<li class="linkListColBox" data-cat="decks">
 <a href="/products/st36.html" class="linkListColItem">
  <h4 class="linkListColTitle">スタートデッキ 海軍【ST-36】</h4>
 </a>
</li>
<a href="?view=normal&amp;page=2">2</a>
<a href="/cardlist/">カードリスト</a>
</body></html>
"""

GUNDAM_HTML = """
<html lang="ja"><body class="lang-ja">
<div class="productsDetail" data-tags="BOOSTERPACK">
 <a href="/jp/products/gd06.html" class="card productsDetailInner">
  <div class="cardTit">Stardust Trails [GD06]</div>
  <dl><dt>発売日</dt><dd>2026.10.31</dd></dl>
 </a>
</div>
<div class="productsDetail" data-tags="ACCESSORIES">
 <a href="accessory01.html" class="card productsDetailInner">
  <div class="cardTit">オフィシャルカードスリーブ</div>
 </a>
</div>
<a href="?page=2">2</a>
<a href="/jp/rules/">ルール</a>
</body></html>
"""


def _products() -> list[dict]:
    return [
        {
            "id": "op",
            "name": "ワンピース商品",
            "tcg_key": "onepiece",
            "tcg": "ワンピースカード",
            "release_date": "2026-08-01",
            "sites": [{
                "site_key": "shop", "name": "店舗A", "url": "https://shop.example/op",
                "application_state": "抽選受付完了", "result_status": "未確認",
                "applied_at": "2026-07-17T10:00:00", "receipt_number": "AB12345678",
            }],
        },
        {
            "id": "gd",
            "name": "ガンダム商品",
            "tcg_key": "gundam",
            "tcg": "ガンダムカード",
            "release_date": "2026-09-01",
            "sites": [{
                "site_key": "shop", "name": "店舗B", "url": "https://shop.example/gd",
                "application_state": "当選", "result_status": "当選",
                "result_checked_at": "2026-07-18T11:00:00",
            }],
        },
    ]


class ApplicationDashboardP24Test(unittest.TestCase):
    def _dashboard(self) -> ApplicationDashboard:
        dashboard = ApplicationDashboard()
        dashboard.store.load_products = _products
        return dashboard

    def test_tcg_counts_filter_and_state_filter_can_be_combined(self):
        dashboard = self._dashboard()
        data = dashboard.build(tcg_filter="onepiece", state_filter="応募済み")
        self.assertEqual(data["tcg_counts"]["onepiece"], 1)
        self.assertEqual(data["tcg_counts"]["gundam"], 1)
        self.assertEqual([row["product_name"] for row in data["rows"]], ["ワンピース商品"])

    def test_rows_show_tcg_dates_url_and_masked_reference(self):
        row = self._dashboard().build(tcg_filter="onepiece")["rows"][0]
        self.assertEqual(row["tcg_key"], "onepiece")
        self.assertEqual(row["application_datetime"], "2026-07-17T10:00:00")
        self.assertEqual(row["related_url"], "https://shop.example/op")
        self.assertNotIn("123456", row["masked_reference"])

    def test_unknown_tcg_is_normalized_to_other_not_pokemon(self):
        self.assertEqual(normalize_key("unexpected-game")[0], "other")
        products = _products()
        products[0]["tcg_key"] = "unexpected-game"
        products[0]["tcg"] = "未知TCG"
        products[0]["sites"][0]["tcg_key"] = "unexpected-game"
        products[0]["sites"][0]["tcg"] = "未知TCG"
        dashboard = self._dashboard()
        dashboard.store.load_products = lambda: products
        row = next(row for row in dashboard.build()["rows"] if row["product_id"] == "op")
        self.assertEqual(row["tcg_key"], "other")

    def test_gmail_inference_supports_onepiece_and_gundam(self):
        self.assertEqual(GmailResultService._infer_tcg_key("onepiececardgame当選"), "onepiece")
        self.assertEqual(GmailResultService._infer_tcg_key("ガンダムカードゲーム予約完了"), "gundam")
        self.assertEqual(GmailResultService._infer_tcg_key("遊戯王ocg当選"), "yugioh")

    def test_manual_lottery_saves_tcg_and_migrates_unknown_existing_data(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("core.lottery_manager.app_root", return_value=Path(directory)):
                manager = LotteryManager()
            manager.items_path.parent.mkdir(parents=True)
            manager.items_path.write_text(json.dumps([{"id": "old", "tcg_key": "bad"}]), encoding="utf-8")
            self.assertEqual(manager.load_items()[0]["tcg_key"], "other")
            self.assertTrue(manager.add_item("商品", "店舗", "https://example.com", "gundam"))
            self.assertEqual(manager.load_items()[-1]["tcg_key"], "gundam")

    def test_product_application_state_preserves_product_tcg(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("core.product_store.app_root", return_value=Path(directory)):
                store = ProductStore()
            store.products_path.parent.mkdir(parents=True)
            store.products_path.write_text(json.dumps(_products(), ensure_ascii=False), encoding="utf-8")
            store.save_site_application_state("op", "shop", "https://shop.example/op", True, "onepiece")
            site = store.load_products()[0]["sites"][0]
            self.assertEqual(site["tcg_key"], "onepiece")
            self.assertTrue(site["applied_at"])


class OfficialExtractorP24Test(unittest.TestCase):
    def test_onepiece_list_date_kind_relative_url_and_exclusions(self):
        extractor = OnePieceOfficialExtractor()
        products = extractor.extract_list_products(
            ONEPIECE_HTML, "https://www.onepiece-cardgame.com/products/?view=normal", "公式"
        )
        self.assertEqual(len(products), 2)
        self.assertEqual(products[0]["release_date"], "2026-08-01")
        self.assertEqual(products[0]["product_kind"], "ブースターパック")
        self.assertEqual(products[0]["tcg_key"], "onepiece")
        self.assertTrue(products[1]["official_url"].startswith("https://www.onepiece-cardgame.com/products/"))

    def test_onepiece_detail_pagination_duplicate_and_region_rejection(self):
        extractor = OnePieceOfficialExtractor()
        pages = extractor.collect_page_urls(
            ONEPIECE_HTML, "https://www.onepiece-cardgame.com/products/?view=normal"
        )
        self.assertEqual(len(pages), 2)
        detail = extractor.supplement_from_detail(
            '<html lang="ja"><meta property="og:title" content="商品 | ONE PIECE"><p>2026年9月2日発売</p></html>',
            "https://www.onepiece-cardgame.com/products/op17.html",
        )
        self.assertEqual(detail["release_date"], "2026-09-02")
        with self.assertRaises(ValueError):
            extractor.extract_list_products(ONEPIECE_HTML.replace('lang="ja"', 'lang="en"'), "https://www.onepiece-cardgame.com/products/", "公式")

    def test_gundam_list_date_kind_relative_url_and_pagination(self):
        extractor = GundamOfficialExtractor()
        products = extractor.extract_list_products(
            GUNDAM_HTML, "https://www.gundam-gcg.com/jp/products/list.php", "公式"
        )
        self.assertEqual(len(products), 2)
        self.assertEqual(products[0]["release_date"], "2026-10-31")
        self.assertEqual(products[0]["product_kind"], "ブースターパック")
        self.assertEqual(products[0]["tcg_key"], "gundam")
        self.assertEqual(len(extractor.collect_page_urls(GUNDAM_HTML, "https://www.gundam-gcg.com/jp/products/list.php")), 2)

    def test_gundam_detail_and_region_rejection(self):
        extractor = GundamOfficialExtractor()
        detail = extractor.supplement_from_detail(
            '<html><body class="lang-ja"><h2 class="titleColInnerHead">GD06</h2><div class="date"><span>2026.10.31</span></div></body></html>',
            "https://www.gundam-gcg.com/jp/products/gd06.html",
        )
        self.assertEqual(detail["release_date"], "2026-10-31")
        with self.assertRaises(ValueError):
            extractor.extract_list_products(GUNDAM_HTML, "https://www.gundam-gcg.com/en/products/list.php", "公式")

    def test_duplicate_helper_and_zero_products_are_errors(self):
        product = {"name": "同一商品", "release_date": "2026-01-01", "official_url": "https://example.com/a"}
        unique, duplicates = SourceManager._deduplicate_products([product, dict(product)])
        self.assertEqual((len(unique), duplicates), (1, 1))
        with tempfile.TemporaryDirectory() as directory:
            with patch("core.source_manager.app_root", return_value=Path(directory)):
                manager = SourceManager()
            source = next(item for item in manager.load_sources() if item["tcg_key"] == "onepiece")
            response = {"ok": True, "title": "公式", "html": "<html lang=\"ja\"></html>", "status": "確認成功", "url": source["url"]}
            with patch.object(manager, "_fetch_page", return_value=response), patch.object(
                manager, "_extract_onepiece_official_products", return_value=([], 0, 0)
            ):
                checked, _ = manager.check_source(source["id"])
            self.assertEqual(checked["check_state"], "error")
            self.assertIn("商品を解析できませんでした", checked["last_error_reason"])


class ApplicationDashboardP24UiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_dashboard_has_all_tcg_tabs_with_counts(self):
        with patch.object(ApplicationDashboard, "build", return_value={
            "counts": {key: 0 for key in ("未応募", "応募済み", "抽選結果待ち", "当選", "落選", "予約完了", "注文受付", "キャンセル", "その他")},
            "tcg_counts": {
                key: 0
                for key in (
                    "pokemon", "onepiece", "yugioh", "gundam",
                    "union_arena", "dragon_ball_fusion_world",
                    "duelmasters", "weiss", "mtg", "other",
                )
            },
            "rows": [], "total_rows": 0,
        }):
            page = ApplicationDashboardPage()
        tabs = page.findChild(QTabBar)
        self.assertEqual(
            [tabs.tabData(i) for i in range(tabs.count())],
            [
                "all", "pokemon", "onepiece", "yugioh", "gundam",
                "union_arena", "dragon_ball_fusion_world",
                "duelmasters", "weiss", "mtg", "other",
            ],
        )


if __name__ == "__main__":
    unittest.main()
