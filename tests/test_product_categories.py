from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "app"))

from core.application_dashboard import ApplicationDashboard
from core.product_categories import (
    CARD,
    COLLAB_LIMITED,
    SUPPLY,
    detect_product_category,
    normalize_product_category,
)
from core.product_store import ProductStore


class ProductCategoryTest(unittest.TestCase):
    def test_explicit_categories(self):
        self.assertEqual(normalize_product_category({"product_category": "CARD"}), CARD)
        self.assertEqual(normalize_product_category({"product_category": "supply"}), SUPPLY)
        self.assertEqual(
            normalize_product_category({"product_category": "COLLAB_LIMITED"}),
            COLLAB_LIMITED,
        )

    def test_legacy_and_unknown_are_safe_card_defaults(self):
        self.assertEqual(normalize_product_category({"name": "旧商品"}), CARD)
        self.assertEqual(normalize_product_category({"product_category": "bad"}), CARD)

    def test_supply_and_collaboration_detection(self):
        self.assertEqual(detect_product_category("ポケカ公式スリーブ予約受付"), SUPPLY)
        self.assertEqual(
            detect_product_category("ONE PIECE 周年記念 特別セット 抽選販売"),
            COLLAB_LIMITED,
        )
        self.assertEqual(detect_product_category("一般イベント限定のお知らせ"), CARD)

    def test_legacy_store_load_does_not_rewrite_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.joinpath("data").mkdir()
            path = root / "data" / "products.json"
            original = [{"id": "legacy-1", "name": "旧カード", "sites": []}]
            path.write_text(json.dumps(original, ensure_ascii=False), encoding="utf-8")
            loaded = ProductStore(root).load_products()
            self.assertEqual(loaded[0]["product_category"], CARD)
            self.assertNotIn("product_category", json.loads(path.read_text(encoding="utf-8"))[0])

    def test_application_category_filter_keeps_application_separate(self):
        rows = [
            {"product_category": CARD, "period_ended": False, "tcg_key": "pokemon",
             "sales_mode": "ONLINE", "prefecture": "東京都", "application_state": "未応募",
             "period_status": "受付中", "dashboard_state": "未応募", "product_name": "カード",
             "site_name": "店", "tcg": "Pokemon", "application_end_at": "", "application_end": ""},
            {"product_category": SUPPLY, "period_ended": False, "tcg_key": "pokemon",
             "sales_mode": "ONLINE", "prefecture": "東京都", "application_state": "未応募",
             "period_status": "受付中", "dashboard_state": "未応募", "product_name": "スリーブ",
             "site_name": "店", "tcg": "Pokemon", "application_end_at": "", "application_end": ""},
        ]
        filtered = ApplicationDashboard.filter_cached(
            rows,
            product_category_filter=SUPPLY,
        )
        self.assertEqual([item["product_name"] for item in filtered], ["スリーブ"])


if __name__ == "__main__":
    unittest.main()
