from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "app"))
sys.path.insert(0, str(PROJECT_ROOT))

from core.update_manager_base import BaseUpdateManager
from core.user_update_profile import USER_PROFILE
from tools import apply_update


class StableBridgeUpdaterTest(unittest.TestCase):
    def test_frozen_updater_is_staged_outside_install_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            install_root = root / "install"
            temp_dir = root / "data" / "temp" / "user_updater"
            install_root.mkdir(parents=True)
            temp_dir.mkdir(parents=True)
            updater = install_root / USER_PROFILE.updater_name
            updater.write_bytes(b"valid updater payload")

            manager = BaseUpdateManager.__new__(BaseUpdateManager)
            manager.install_root = install_root
            manager.user_root = root / "data"
            manager.temp_dir = temp_dir
            manager.PROFILE = USER_PROFILE

            with patch.object(manager, "_current_pid", return_value=1234), patch(
                "core.update_manager_base.is_frozen", return_value=True
            ):
                command, _status_file = manager.create_apply_command(
                    temp_dir / "PokeyoyaKun_User_Setup_Ver1.25.0.exe"
                )

            staged = Path(command[0])
            self.assertEqual(temp_dir / "PokeyoyaKunUpdaterV2_1234.exe", staged)
            self.assertEqual(updater.read_bytes(), staged.read_bytes())
            self.assertNotEqual(install_root, staged.parent)

    def test_staged_updater_is_launched_from_staging_directory(self):
        manager = BaseUpdateManager.__new__(BaseUpdateManager)
        manager.temp_dir = Path("staging")
        with patch("core.update_manager_base.subprocess.Popen") as launcher:
            manager.launch_apply_command(["staging/updater.exe"])
        launcher.assert_called_once_with(
            ["staging/updater.exe"], cwd=str(manager.temp_dir), close_fds=True
        )

    def test_stable_installer_does_not_replace_running_legacy_updater(self):
        installer = (
            PROJECT_ROOT / "installer" / "PokeyoyaKun_User_Setup.iss"
        ).read_text(encoding="utf-8")
        file_section = installer.split("[Files]", 1)[1].split("[Icons]", 1)[0]
        self.assertIn("PokeyoyaKunUpdaterV2.exe", file_section)
        self.assertNotIn("PokeyoyaKunUpdater.exe", file_section)
        self.assertIn(
            'Type: files; Name: "{app}\\PokeyoyaKunUpdater.exe"', installer
        )


class SafeLaunchFailureTest(unittest.TestCase):
    def _run_with_mocked_installer(self, installer_result) -> tuple[int, Mock, dict]:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            setup = root / "PokeyoyaKun_User_Setup_Ver1.25.0.exe"
            setup.write_bytes(b"fixture bytes are never executed")
            sha_file = root / "setup.sha256"
            sha_file.write_text(
                hashlib.sha256(setup.read_bytes()).hexdigest(), encoding="ascii"
            )
            status_file = root / "status.json"
            arguments = [
                "updater", "--pid", "0", "--setup", str(setup),
                "--sha-file", str(sha_file), "--target", str(root / "target"),
                "--launch-json", "[]", "--status-file", str(status_file),
            ]
            run_patch = (
                patch("tools.apply_update.subprocess.run", side_effect=installer_result)
                if isinstance(installer_result, BaseException)
                else patch("tools.apply_update.subprocess.run", return_value=installer_result)
            )
            with patch.object(sys, "argv", arguments), run_patch as launcher, patch(
                "tools.apply_update.subprocess.Popen"
            ) as relaunch:
                result = apply_update.run("user")
            relaunch.assert_not_called()
            return result, launcher, json.loads(status_file.read_text(encoding="utf-8"))

    def test_launch_failure_is_mocked_and_fails_fast_without_windows_dialog(self):
        result, launcher, status = self._run_with_mocked_installer(
            OSError("mocked launch failure")
        )
        self.assertEqual(1, result)
        self.assertEqual(1, launcher.call_count)
        self.assertFalse(status["success"])
        self.assertIn("mocked launch failure", status["message"])

    def test_nonzero_installer_exit_is_mocked_without_retry(self):
        result, launcher, status = self._run_with_mocked_installer(
            Mock(returncode=5)
        )
        self.assertEqual(1, result)
        self.assertEqual(1, launcher.call_count)
        self.assertEqual("インストーラーが失敗しました: 5", status["message"])


if __name__ == "__main__":
    unittest.main()
