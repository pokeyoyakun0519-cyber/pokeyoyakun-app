import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from core.source_inventory_view import (
    STATUS_LABELS,
    build_source_inventory_view,
    filter_source_inventory,
    load_saved_coverage,
)
from ui.application_dashboard_page import SourceInventorySection


def _report():
    states = [
        ("card_labo", "カードラボ", "CURRENT_APPLICATION"),
        ("joshin", "Joshin", "ROBOTS_BLOCKED"),
        ("bookoff", "BOOKOFF", "NO_CURRENT_APPLICATION"),
        ("tsutaya", "TSUTAYA", "APP_REQUIRED"),
        ("batoroco", "バトロコ", "SNS_ONLY"),
        ("new_shop", "新規店", "DISCOVERED_CANDIDATE"),
        ("parser_shop", "解析店", "PARSER_NEEDED"),
        ("unsupported", "未対応店", "UNSUPPORTED"),
    ]
    inventory = []
    for index, (chain, name, state) in enumerate(states):
        inventory.append({
            "tcg": "pokemon", "chain": chain, "display_name": name,
            "official_url": (
                "https://joshinweb.jp/toy/48712.html?SRT=10"
                if chain == "joshin" else "https://www.bookoff.co.jp/event/"
            ),
            "state": state, "prefectures": ["東京都"] if index == 0 else [],
            "last_check": "2026-08-23T12:00:00+09:00",
            "monitoring_type": "WEB_DIRECT", "discovered_from": "RETAILER",
            "secret": "must-not-be-rendered",
        })
    return {
        "generated_at": "2026-08-23T12:00:00+09:00",
        "inventory": inventory,
        "applications": [{
            "tcg": "pokemon", "chain": "card_labo", "branch": "秋葉原店",
            "prefecture": "東京都", "state": "CURRENT_APPLICATION",
            "official_url": "https://www.c-labo.jp/blog/1/",
        }],
    }


class SourceInventoryModelTest(unittest.TestCase):
    def test_summary_counts_unique_store_and_states(self):
        view = build_source_inventory_view(_report())
        summary = view["summary"]
        self.assertEqual(8, summary["chain_count"])
        self.assertEqual(8, summary["branch_store_count"])
        self.assertEqual(1, summary["current"])
        self.assertEqual(1, summary["no_current"])
        self.assertEqual(1, summary["verifying"])
        self.assertEqual(1, summary["app_required"])
        self.assertEqual(1, summary["sns_only"])
        self.assertEqual(1, summary["restricted"])
        self.assertEqual(1, summary["parser_needed"])
        self.assertEqual(1, summary["unsupported"])

    def test_filters_and_store_search(self):
        rows = build_source_inventory_view(_report())["rows"]
        self.assertEqual(["joshin"], [row["chain"] for row in filter_source_inventory(
            rows, state_filter="restricted", keyword="Joshin"
        )])
        self.assertEqual(["card_labo"], [row["chain"] for row in filter_source_inventory(
            rows, state_filter="current", tcg="pokemon", region="関東",
            prefecture="東京都", chain="card_labo", keyword="秋葉原",
        )])

    def test_status_reason_safe_url_and_candidate_not_application(self):
        rows = build_source_inventory_view(_report())["rows"]
        joshin = next(row for row in rows if row["chain"] == "joshin")
        candidate = next(row for row in rows if row["chain"] == "new_shop")
        self.assertEqual("自動確認に制限あり", STATUS_LABELS["ROBOTS_BLOCKED"])
        self.assertIn("別の公式情報源", joshin["reason"])
        self.assertTrue(joshin["official_url_safe"])
        self.assertFalse(candidate["dashboard_listed"])
        self.assertEqual(0, candidate["current_application_count"])

    def test_saved_loader_has_no_network_dependency(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "coverage.json"
            path.write_text('{"inventory": [], "applications": []}', encoding="utf-8")
            with patch("urllib.request.urlopen", side_effect=AssertionError("network called")):
                self.assertEqual([], load_saved_coverage(path)["inventory"])


class SourceInventoryWidgetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_widget_uses_saved_snapshot_and_hides_private_values(self):
        with patch(
            "ui.application_dashboard_page.load_saved_coverage", return_value=_report()
        ), patch("urllib.request.urlopen", side_effect=AssertionError("network called")):
            section = SourceInventorySection()
        self.assertEqual(8, section.table.rowCount())
        self.assertIn("監視候補店舗 8", section.summary.text())
        section.search.setText("Joshin")
        self.assertEqual(1, section.table.rowCount())
        section.table.selectRow(0)
        self.assertIn("自動確認に制限あり", section.detail.text())
        self.assertIn("別の公式情報源を探索中", section.detail.text())
        self.assertNotIn("ROBOTS", section.detail.text())
        self.assertNotIn("must-not-be-rendered", section.detail.text())
        section.deleteLater()


if __name__ == "__main__":
    unittest.main()
