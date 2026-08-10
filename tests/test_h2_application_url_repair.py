import json
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
sys.path.insert(0, str(APP_DIR))

from core.application_dashboard import ApplicationDashboard
from core.application_site import has_application_evidence, normalize_application_site
from core.config_manager import ConfigManager
from core.product_store import ProductStore


PRODUCT_URL = "https://example.jp/products/123"


class H2ApplicationUrlRepairTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    @staticmethod
    def _site(**updates):
        site = {
            "name": "通常店舗",
            "site_key": "shop",
            "url": PRODUCT_URL,
            "application_url": PRODUCT_URL,
            "status": "販売中",
        }
        site.update(updates)
        return site

    def _write_products(self, site):
        path = self.root / "data" / "products.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps([{
            "id": "legacy-product",
            "name": "旧データ商品",
            "tcg_key": "pokemon",
            "sites": [site],
        }], ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def _dashboard_rows(self, site):
        self._write_products(site)
        store = ProductStore(self.root)
        dashboard = ApplicationDashboard(
            store=store,
            config_manager=ConfigManager(self.root),
        )
        dashboard.change_tracker.root = self.root
        return dashboard.build(show_ended=True)["rows"]

    def test_same_application_and_product_page_is_not_evidence(self):
        normalized = normalize_application_site(self._site())
        self.assertNotIn("application_url", normalized)
        self.assertFalse(has_application_evidence(normalized))

    def test_trailing_slash_difference_is_same_url(self):
        normalized = normalize_application_site(
            self._site(application_url=PRODUCT_URL + "/")
        )
        self.assertNotIn("application_url", normalized)

    def test_utm_difference_is_same_url(self):
        variants = (
            PRODUCT_URL + "?utm_source=x&utm_medium=social",
            PRODUCT_URL + "?fbclid=abc&gclid=def&twclid=ghi",
            "HTTPS://EXAMPLE.JP/products/123?ref_src=twsrc%5Etfw",
        )
        for application_url in variants:
            with self.subTest(application_url=application_url):
                normalized = normalize_application_site(self._site(
                    application_url=application_url,
                ))
                self.assertNotIn("application_url", normalized)

        distinct = normalize_application_site(self._site(
            url=PRODUCT_URL + "?product_id=123",
            application_url=PRODUCT_URL + "?product_id=456",
        ))
        self.assertIn("application_url", distinct)

    def test_fragment_difference_is_same_url(self):
        normalized = normalize_application_site(
            self._site(application_url=PRODUCT_URL + "#entry")
        )
        self.assertNotIn("application_url", normalized)

    def test_application_url_matching_product_url_is_removed(self):
        normalized = normalize_application_site(self._site(
            url="https://example.jp/news/1",
            product_url=PRODUCT_URL,
        ))
        self.assertNotIn("application_url", normalized)

    def test_application_url_matching_source_url_is_removed(self):
        normalized = normalize_application_site(self._site(
            url="https://example.jp/news/1",
            source_url=PRODUCT_URL,
        ))
        self.assertNotIn("application_url", normalized)

    def test_external_livepocket_url_is_preserved(self):
        url = "https://t.livepocket.jp/e/lottery-123"
        normalized = normalize_application_site(self._site(application_url=url))
        self.assertEqual(url, normalized["application_url"])
        self.assertTrue(has_application_evidence(normalized))

    def test_external_x_application_link_is_preserved(self):
        url = "https://x.com/example/status/12345"
        normalized = normalize_application_site(self._site(application_url=url))
        self.assertEqual(url, normalized["application_url"])

    def test_same_url_with_application_period_is_preserved(self):
        normalized = normalize_application_site(self._site(
            application_period="2099/08/01～2099/08/10",
        ))
        self.assertEqual(PRODUCT_URL, normalized["application_url"])

    def test_same_url_with_lottery_status_is_preserved(self):
        normalized = normalize_application_site(self._site(status="抽選受付中"))
        self.assertEqual(PRODUCT_URL, normalized["application_url"])
        legacy = normalize_application_site(self._site(
            status="",
            application_status="予約受付中",
        ))
        self.assertEqual(PRODUCT_URL, legacy["application_url"])
        article = normalize_application_site(self._site(
            status="",
            article_type="reservation",
        ))
        self.assertEqual(PRODUCT_URL, article["application_url"])

    def test_same_url_with_ordinary_sale_status_is_not_evidence(self):
        for status in ("通常販売", "商品紹介", "販売中", "在庫あり"):
            with self.subTest(status=status):
                normalized = normalize_application_site(self._site(status=status))
                self.assertNotIn("application_url", normalized)
                self.assertFalse(has_application_evidence(normalized))

    def test_product_page_only_is_hidden_from_dashboard(self):
        self.assertEqual([], self._dashboard_rows(self._site()))

    def test_reading_legacy_data_does_not_rewrite_json(self):
        path = self._write_products(self._site())
        before = path.read_bytes()
        products = ProductStore(self.root).load_products()
        self.assertNotIn("application_url", products[0]["sites"][0])
        self.assertEqual(before, path.read_bytes())

    def test_existing_save_path_can_persist_repaired_value(self):
        path = self._write_products(self._site())
        store = ProductStore(self.root)
        products = store.load_products()
        store._save_product_file(products)
        saved = json.loads(path.read_text(encoding="utf-8"))
        self.assertNotIn("application_url", saved[0]["sites"][0])

    def test_application_history_is_preserved(self):
        history = [{"status": "応募済み", "at": "2026-01-01"}]
        normalized = normalize_application_site(self._site(application_history=history))
        self.assertEqual(history, normalized["application_history"])
        self.assertNotIn("application_url", normalized)
        user_state = normalize_application_site(self._site(application_state="応募済み"))
        self.assertEqual("応募済み", user_state["application_state"])

    def test_result_status_is_preserved(self):
        normalized = normalize_application_site(self._site(result_status="当選"))
        self.assertEqual("当選", normalized["result_status"])

    def test_target_stores_are_preserved(self):
        stores = ["秋葉原店", "大阪店"]
        normalized = normalize_application_site(self._site(target_stores=stores))
        self.assertEqual(stores, normalized["target_stores"])

    def test_null_empty_and_invalid_urls_do_not_raise(self):
        for value in (None, "", "not a url"):
            with self.subTest(value=value):
                normalized = normalize_application_site(self._site(
                    application_url=value,
                ))
                self.assertIsInstance(has_application_evidence(normalized), bool)


if __name__ == "__main__":
    unittest.main()
