import json
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
sys.path.insert(0, str(APP_DIR))

from core.product_master import ProductMasterManager
from core.product_store import ProductStore


def product(name="同一商品", **updates):
    value = {
        "id": updates.pop("id", name),
        "name": name,
        "tcg_key": updates.pop("tcg_key", "pokemon"),
        "product_kind": updates.pop("product_kind", "BOX"),
        "brand": updates.pop("brand", "ブランドA"),
        "sites": [],
    }
    value.update(updates)
    return value


class B3IdentifierConflictTest(unittest.TestCase):
    def test_same_jan_is_merged(self):
        index, reason = ProductMasterManager.find_match(
            [product(jan="4901234567890")],
            product(name="商品名の微差", jan="4901234567890"),
        )
        self.assertEqual((0, "identifier"), (index, reason))

    def test_jan_conflict_is_not_merged(self):
        result = ProductMasterManager.find_match(
            [product(jan="4901234567890")],
            product(jan="4901234567891"),
        )
        self.assertEqual((None, "identifier_conflict"), result)

    def test_product_code_conflict_is_not_merged(self):
        result = ProductMasterManager.find_match(
            [product(product_code="ABC-001")],
            product(product_code="ABC-002"),
        )
        self.assertEqual((None, "identifier_conflict"), result)

    def test_one_conflict_overrides_a_different_matching_identifier(self):
        result = ProductMasterManager.find_match(
            [product(jan="4901234567890", product_code="ABC-001")],
            product(jan="4901234567890", product_code="ABC-002"),
        )
        self.assertEqual((None, "identifier_conflict"), result)

    def test_official_product_id_conflict_is_not_merged(self):
        result = ProductMasterManager.find_match(
            [product(official_product_id="official-1")],
            product(official_product_id="official-2"),
        )
        self.assertEqual((None, "identifier_conflict"), result)

    def test_jan_and_jan_code_are_same_identifier_type(self):
        result = ProductMasterManager.find_match(
            [product(jan="490-1234-567890")],
            product(name="別表記", jan_code="4901234567890"),
        )
        self.assertEqual((0, "identifier"), result)

    def test_official_id_alias_matches_official_product_id(self):
        result = ProductMasterManager.find_match(
            [product(official_id="OP-001")],
            product(name="別表記", official_product_id="op001"),
        )
        self.assertEqual((0, "identifier"), result)

    def test_name_match_without_identifiers_uses_existing_fallback(self):
        result = ProductMasterManager.find_match(
            [product(name="商品名")],
            product(name="商品名"),
        )
        self.assertEqual((0, "normalized_name"), result)

    def test_different_name_without_identifiers_is_new_product(self):
        result = ProductMasterManager.find_match(
            [product(name="商品A")],
            product(name="商品B"),
        )
        self.assertEqual((None, "no_match"), result)

    def test_identifier_match_overrides_minor_name_difference(self):
        result = ProductMasterManager.find_match(
            [product(name="商品 BOX", product_code="ABC-001")],
            product(name="商品 限定BOX", product_code="abc001"),
        )
        self.assertEqual((0, "identifier"), result)

    def test_exact_name_with_different_jan_stays_as_two_products(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ProductStore(Path(directory))
            store.merge_discovered_products([
                product(id="first", jan="4901234567890")
            ])
            store.merge_discovered_products([
                product(id="second", jan="4901234567891")
            ])
            saved = json.loads(store.products_path.read_text(encoding="utf-8"))
        self.assertEqual(2, len(saved))

    def test_internal_product_id_does_not_override_identifier_conflict(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ProductStore(Path(directory))
            store.merge_discovered_products([
                product(id="same-internal-id", jan="4901234567890")
            ])
            store.merge_discovered_products([
                product(id="same-internal-id", jan="4901234567891")
            ])
            saved = json.loads(store.products_path.read_text(encoding="utf-8"))
        self.assertEqual(2, len(saved))

    def test_box_pack_and_brand_conflicts_remain_separate(self):
        cases = (
            (product(product_kind="BOX"), product(product_kind="パック")),
            (product(brand="ブランドA"), product(brand="ブランドB")),
        )
        for existing, incoming in cases:
            with self.subTest(existing=existing, incoming=incoming):
                self.assertEqual(
                    (None, "no_match"),
                    ProductMasterManager.find_match([existing], incoming),
                )

    def test_different_tcg_remains_separate(self):
        result = ProductMasterManager.find_match(
            [product(jan="4901234567890", tcg_key="pokemon")],
            product(jan="4901234567890", tcg_key="onepiece"),
        )
        self.assertEqual((None, "no_match"), result)

    def test_multiple_identifier_matches_remain_ambiguous(self):
        existing = [
            product(name="商品A", jan="4901234567890"),
            product(name="商品B", jan_code="4901234567890"),
        ]
        result = ProductMasterManager.find_match(
            existing,
            product(name="商品C", jan="4901234567890"),
        )
        self.assertEqual((None, "ambiguous_identifier"), result)

    def test_one_sided_identifier_does_not_fallback_to_name(self):
        cases = (
            ([product(jan="4901234567890")], product()),
            ([product()], product(jan="4901234567890")),
        )
        for existing, incoming in cases:
            with self.subTest(existing=existing, incoming=incoming):
                self.assertEqual(
                    (None, "no_match"),
                    ProductMasterManager.find_match(existing, incoming),
                )


if __name__ == "__main__":
    unittest.main()
