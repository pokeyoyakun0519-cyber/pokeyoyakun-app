from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "app"))
sys.path.insert(0, str(PROJECT_ROOT))

from core.json_file_state import CORRUPT, VALID, CorruptJsonError
from core.p2_startup import P2StartupCoordinator, should_show_user_state_warning
from core.product_store import ProductStore
from core.update_manager_base import current_tag
from tools.apply_update import EDITION_RULES


class FrozenUpdaterFilenameTest(unittest.TestCase):
    def test_user_updater_accepts_rc51(self):
        self.assertIsNotNone(EDITION_RULES["user"].fullmatch(
            "PokeyoyaKun_User_Setup_Ver1.25.0_RC5.1.exe"
        ))

    def test_user_updater_rejects_other_editions_and_test_builds(self):
        for name in (
            "PokeyoyaKun_Owner_Setup_Ver1.25.0_RC5.1.exe",
            "PokeyoyaKun_Admin_Setup_Ver1.25.0_RC5.1.exe",
            "PokeyoyaKun_User_Setup_Ver1.25.0_RC5.1_Test.exe",
            "PokeyoyaKun_User_Setup_Ver1.25.0_RC5.1_FinalTest.exe",
        ):
            with self.subTest(name=name):
                self.assertIsNone(EDITION_RULES["user"].fullmatch(name))

    def test_current_application_tag_is_rc51(self):
        self.assertEqual("v1.25.0-rc5.1", current_tag())


class StartupCorruptUserStateTest(unittest.TestCase):
    def test_corrupt_user_state_stops_startup_sync_without_raising(self):
        with (
            patch("core.p2_startup.SiteMonitorSync.sync", return_value={}),
            patch("core.p2_startup.CandidateManager.load_candidates", return_value=[]),
            patch(
                "core.p2_startup.AutoMonitorManager.add_due_candidates",
                side_effect=CorruptJsonError("user_state.json corrupt"),
            ),
        ):
            result = P2StartupCoordinator().run()
        self.assertTrue(result["auto_monitor"]["state_updates_disabled"])
        self.assertIn("user_state.json", result["auto_monitor"]["error"])

    def test_valid_startup_sync_is_unchanged(self):
        expected = {"added": 0, "products": []}
        with (
            patch("core.p2_startup.SiteMonitorSync.sync", return_value={}),
            patch("core.p2_startup.CandidateManager.load_candidates", return_value=[]),
            patch(
                "core.p2_startup.AutoMonitorManager.add_due_candidates",
                return_value=expected,
            ),
        ):
            result = P2StartupCoordinator().run()
        self.assertEqual(expected, result["auto_monitor"])

    def test_warning_is_shown_for_normal_start_but_not_smoke_test(self):
        result = {"auto_monitor": {"state_updates_disabled": True}}
        self.assertTrue(should_show_user_state_warning(result, ["app.exe"]))
        self.assertFalse(should_show_user_state_warning(
            result, ["app.exe", "--smoke-test"]
        ))

    def test_utf8_bom_user_state_is_accepted_without_rewrite(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ProductStore(Path(directory))
            store.user_state_path.parent.mkdir(parents=True)
            original = (
                b"\xef\xbb\xbf"
                b'{"reserved_product_ids":["kept"],'
                b'"site_applications":{},"auto_monitor_excluded_keys":[]}'
            )
            store.user_state_path.write_bytes(original)
            result = store.inspect_user_state_file()
            self.assertEqual(VALID, result.state)
            self.assertEqual(["kept"], store._load_user_state()["reserved_product_ids"])
            self.assertEqual(original, store.user_state_path.read_bytes())

    def test_invalid_json_and_field_type_remain_corrupt(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ProductStore(Path(directory))
            store.user_state_path.parent.mkdir(parents=True)
            for value in (
                b"\xef\xbb\xbf{broken",
                b'{"reserved_product_ids":"not-a-list"}',
            ):
                with self.subTest(value=value):
                    store.user_state_path.write_bytes(value)
                    self.assertEqual(CORRUPT, store.inspect_user_state_file().state)


if __name__ == "__main__":
    unittest.main()
