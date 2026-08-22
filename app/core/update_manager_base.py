from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from threading import Event

from core.release_update import ReleaseUpdateClient, UpdateError
from core.runtime_paths import app_root, install_root, is_frozen
from core.version import APP_RELEASE_CHANNEL, APP_VERSION


def current_tag() -> str:
    channel = APP_RELEASE_CHANNEL.strip().lower()
    return f"v{APP_VERSION}" if channel in {"stable", "release"} else f"v{APP_VERSION}-{channel}"


class BaseUpdateManager:
    PROFILE = None
    TOKEN_PROVIDER = None

    def __init__(self):
        if self.PROFILE is None:
            raise RuntimeError("更新プロファイルがありません。")
        self.install_root = install_root()
        self.user_root = app_root()
        self.temp_dir = self.user_root / "temp" / f"{self.PROFILE.edition_id}_updater"
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.client = ReleaseUpdateClient(
            self.PROFILE, current_tag(), owner_token_provider=self.TOKEN_PROVIDER
        )

    @property
    def edition_id(self) -> str:
        return self.PROFILE.edition_id

    @property
    def updates_enabled(self) -> bool:
        return self.PROFILE.enabled

    @property
    def disabled_reason(self) -> str:
        return self.PROFILE.disabled_reason

    def check(self, *, allow_prerelease: bool = False) -> dict:
        return self.client.check(allow_prerelease=allow_prerelease)

    def download(self, release: dict, *, progress=None, cancel: Event | None = None) -> Path:
        destination = self.temp_dir / release["setup_name"]
        return self.client.download(release, destination, progress=progress, cancel=cancel, retries=2)

    def create_apply_command(self, setup_path: Path) -> tuple[list[str], Path]:
        status_file = self.temp_dir / "update_result.json"
        status_file.unlink(missing_ok=True)
        if is_frozen():
            updater = self.install_root / self.PROFILE.updater_name
            if not updater.is_file():
                raise UpdateError("更新プログラムが見つかりません。アプリを再インストールしてください。")
            staged_updater = self.temp_dir / (
                f"{updater.stem}_{self._current_pid()}{updater.suffix}"
            )
            try:
                shutil.copy2(updater, staged_updater)
            except OSError as error:
                raise UpdateError("更新プログラムを準備できませんでした。") from error
            command = [str(staged_updater)]
            launch = [str(self.install_root / self.PROFILE.application_name)]
        else:
            wrapper = "owner_updater_main.py" if self.edition_id == "owner" else "user_updater_main.py"
            command = [sys.executable, str(self.install_root / "tools" / wrapper)]
            launch_script = "owner_main.py" if self.edition_id == "owner" else "monitor_main.py"
            launch = [sys.executable, str(self.install_root / "app" / launch_script)]
        command.extend([
            "--pid", str(self._current_pid()), "--setup", str(setup_path),
            "--sha-file", str(setup_path.with_suffix(setup_path.suffix + ".sha256")),
            "--target", str(self.install_root),
            "--launch-json", json.dumps(launch, ensure_ascii=False),
            "--status-file", str(status_file),
        ])
        return command, status_file

    def launch_apply_command(self, command: list[str]) -> None:
        subprocess.Popen(command, cwd=str(self.temp_dir), close_fds=True)

    def read_last_result(self) -> dict | None:
        path = self.temp_dir / "update_result.json"
        try:
            return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
        except (OSError, json.JSONDecodeError):
            return None

    @staticmethod
    def _current_pid() -> int:
        import os
        return os.getpid()
