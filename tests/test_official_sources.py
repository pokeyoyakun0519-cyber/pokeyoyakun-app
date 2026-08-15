from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PySide6.QtWidgets import QApplication, QLabel, QPushButton


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
sys.path.insert(0, str(APP_DIR))

from core.source_manager import SourceManager
from ui.sources_page import SourceCard, SourcesPage


def _product(name: str = "公式商品") -> dict:
    return {
        "name": name,
        "release_date": "2026-09-01",
        "sites": [{"url": "https://example.com/product"}],
    }


class OfficialSourceManagerTest(unittest.TestCase):
    def _manager(self, directory: str) -> SourceManager:
        with patch("core.source_manager.app_root", return_value=Path(directory)):
            return SourceManager()

    def test_fresh_install_seeds_all_supported_official_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = self._manager(directory)
            sources = manager.load_sources()
            self.assertEqual(len(sources), 8)
            self.assertEqual(
                [item["url"] for item in sources],
                [item["url"] for item in SourceManager.DEFAULT_SOURCES],
            )
            self.assertEqual(
                {item["tcg_key"] for item in sources},
                {
                    "pokemon", "onepiece", "yugioh", "gundam",
                    "union_arena", "duelmasters", "weiss", "mtg",
                },
            )
            self.assertTrue(all(item["check_state"] == "unchecked" for item in sources))
            self.assertTrue(manager.sources_path.is_file())

    def test_update_preserves_existing_data_and_adds_only_missing_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = self._manager(directory)
            manager.sources_path.parent.mkdir(parents=True)
            existing = [
                {
                    "id": "custom",
                    "name": "既存カスタムソース",
                    "url": "https://cards.example/custom",
                    "last_status": "既存状態",
                    "enabled": False,
                    "tcg_key": "other",
                },
                {
                    "id": "pokemon-existing",
                    "name": "登録済みポケモン公式",
                    "url": "https://www.pokemon-card.com/",
                    "last_status": "確認成功・既存",
                    "enabled": True,
                    "tcg_key": "pokemon",
                },
            ]
            manager.sources_path.write_text(
                json.dumps(existing, ensure_ascii=False), encoding="utf-8"
            )
            sources = manager.load_sources()
            self.assertEqual(len(sources), 9)
            custom = next(item for item in sources if item["id"] == "custom")
            pokemon = next(item for item in sources if item["id"] == "pokemon-existing")
            self.assertFalse(custom["enabled"])
            self.assertEqual(custom["last_status"], "既存状態")
            self.assertEqual(pokemon["last_status"], "確認成功・既存")
            self.assertEqual(
                sum(item["url"] == "https://www.pokemon-card.com/" for item in sources),
                1,
            )

    def test_corrupt_existing_file_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = self._manager(directory)
            manager.sources_path.parent.mkdir(parents=True)
            manager.sources_path.write_text("{broken", encoding="utf-8")
            self.assertEqual(manager.load_sources(), [])
            self.assertEqual(manager.sources_path.read_text(encoding="utf-8"), "{broken")

    def test_individual_check_succeeds_for_all_supported_tcg_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = self._manager(directory)
            sources = manager.load_sources()
            ok = {"ok": True, "title": "公式商品", "html": "<html></html>", "status": "確認成功"}
            with (
                patch.object(manager, "_fetch_page", return_value=ok),
                patch.object(
                    manager,
                    "_extract_pokemon_official_products",
                    return_value=([_product("ポケモン商品")], 1),
                ),
                patch.object(
                    manager,
                    "_extract_yugioh_official_products",
                    return_value=([_product("遊戯王商品")], 1),
                ),
                patch.object(
                    manager,
                    "_extract_onepiece_official_products",
                    return_value=([_product("ワンピース商品")], 1, 0),
                ),
                patch.object(
                    manager,
                    "_extract_gundam_official_products",
                    return_value=([_product("ガンダム商品")], 1, 0),
                ),
                patch.object(
                    manager,
                    "_extract_union_arena_official_products",
                    return_value=([_product("UNION ARENA商品")], 1, 0),
                ),
                patch.object(
                    manager,
                    "_extract_catalog_official_products",
                    return_value=([_product("追加公式商品")], 1, 0),
                ),
                patch.object(
                    manager,
                    "_extract_mtg_official_products",
                    return_value=([_product("MTG商品")], 1, 0),
                ),
                patch.object(
                    manager.extractor,
                    "extract",
                    side_effect=lambda _html, _url, name: [_product(name)],
                ),
                patch.object(manager.diff_tracker, "compare_and_update", return_value=[]),
                patch.object(
                    manager.candidate_manager,
                    "merge_official_candidates",
                    return_value=([], 0),
                ),
            ):
                for source in sources:
                    with self.subTest(tcg_key=source["tcg_key"]):
                        checked, _changed = manager.check_source(source["id"])
                        self.assertIsNotNone(checked)
                        self.assertEqual(checked["check_state"], "checked")
                        self.assertTrue(checked["last_checked"])
                        self.assertTrue(checked["last_status"].startswith("確認成功"))
                        self.assertEqual(checked["last_detected_count"], 1)

    def test_check_all_continues_after_one_source_parser_error(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = self._manager(directory)
            manager.load_sources()
            ok = {"ok": True, "title": "公式商品", "html": "<html></html>", "status": "確認成功"}

            def generic_extract(_html, _url, source_name):
                if "ワンピース" in source_name:
                    raise ValueError("解析エラー")
                return [_product(source_name)]

            with (
                patch.object(manager, "_fetch_page", return_value=ok),
                patch.object(
                    manager,
                    "_extract_pokemon_official_products",
                    return_value=([_product("ポケモン商品")], 1),
                ),
                patch.object(
                    manager,
                    "_extract_yugioh_official_products",
                    return_value=([_product("遊戯王商品")], 1),
                ),
                patch.object(
                    manager,
                    "_extract_onepiece_official_products",
                    side_effect=ValueError("解析エラー"),
                ),
                patch.object(
                    manager,
                    "_extract_gundam_official_products",
                    return_value=([_product("ガンダム商品")], 1, 0),
                ),
                patch.object(
                    manager,
                    "_extract_union_arena_official_products",
                    return_value=([_product("UNION ARENA商品")], 1, 0),
                ),
                patch.object(
                    manager,
                    "_extract_catalog_official_products",
                    return_value=([_product("追加公式商品")], 1, 0),
                ),
                patch.object(
                    manager,
                    "_extract_mtg_official_products",
                    return_value=([_product("MTG商品")], 1, 0),
                ),
                patch.object(manager.extractor, "extract", side_effect=generic_extract),
                patch.object(manager.diff_tracker, "compare_and_update", return_value=[]),
                patch.object(
                    manager.candidate_manager,
                    "merge_official_candidates",
                    return_value=([], 0),
                ),
            ):
                checked, _changed = manager.check_all()
            states = {item["tcg_key"]: item["check_state"] for item in checked}
            self.assertEqual(states["pokemon"], "checked")
            self.assertEqual(states["onepiece"], "error")
            self.assertEqual(states["yugioh"], "checked")
            self.assertEqual(states["gundam"], "checked")
            self.assertTrue(all(item["last_checked"] for item in checked))

    def test_mark_checking_is_persisted(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = self._manager(directory)
            source = manager.load_sources()[0]
            self.assertTrue(manager.mark_checking(source["id"]))
            saved = next(item for item in manager.load_sources() if item["id"] == source["id"])
            self.assertEqual(saved["check_state"], "checking")
            self.assertEqual(saved["last_status"], "確認中")


class OfficialSourceUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_card_has_individual_check_button_and_clear_status(self):
        called = []
        source = {
            "id": "source-1",
            "name": "公式",
            "url": "https://example.com",
            "tcg_key": "pokemon",
            "enabled": True,
            "check_state": "checked",
            "last_status": "確認成功・商品1件検出",
            "last_checked": "2026/07/17 12:00:00",
        }
        card = SourceCard(
            source,
            lambda _source: None,
            lambda value: called.append(value["id"]),
            lambda _source: None,
            lambda _source_id: None,
        )
        button = next(
            item for item in card.findChildren(QPushButton) if item.text() == "確認"
        )
        button.click()
        self.assertEqual(called, ["source-1"])
        labels = [item.text() for item in card.findChildren(QLabel)]
        self.assertIn("🟢 確認済み", labels)
        self.assertTrue(any("最終確認：2026/07/17" in text for text in labels))

    def test_all_check_runs_in_registration_order_and_reports_progress(self):
        sources = [
            {
                "id": str(index),
                "name": default["name"],
                "url": default["url"],
                "tcg_key": default["tcg_key"],
                "enabled": True,
                "check_state": "unchecked",
                "last_status": "未確認",
                "last_checked": "",
            }
            for index, default in enumerate(SourceManager.DEFAULT_SOURCES)
        ]
        manager = Mock()
        manager.load_sources.side_effect = lambda: [dict(item) for item in sources]
        manager.mark_checking.side_effect = lambda source_id: True
        checked_order = []

        def check_source(source_id):
            checked_order.append(source_id)
            return {"id": source_id, "check_state": "checked"}, False

        manager.check_source.side_effect = check_source
        with (
            patch("ui.sources_page.SourceManager", return_value=manager),
            patch("ui.sources_page.LogManager"),
            patch("ui.sources_page.NotificationManager"),
        ):
            page = SourcesPage()
        page.check_sources()
        for _ in range(20):
            self.app.processEvents()
            if not page._checking:
                break
        self.assertFalse(page._checking)
        self.assertEqual(
            checked_order,
            [str(index) for index in range(len(SourceManager.DEFAULT_SOURCES))],
        )
        self.assertIn(
            f"{len(SourceManager.DEFAULT_SOURCES)}件の確認が完了",
            page.result_label.text(),
        )
        self.assertTrue(page.check_all_button.isEnabled())


if __name__ == "__main__":
    unittest.main()
