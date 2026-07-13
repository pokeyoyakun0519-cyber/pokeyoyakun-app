import hashlib
import json
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

from core.runtime_paths import app_root, install_root, is_frozen
from core.version import APP_CHANNEL, APP_VERSION


class UpdateError(Exception):
    pass


class UpdateManager:
    USER_AGENT = "PokeyoyaKun-Updater/0.27"

    def __init__(self):
        self.install_root = install_root()
        self.user_root = app_root()
        self.temp_dir = self.user_root / "temp" / "updater"
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    def check(self, manifest_location: str) -> dict:
        if not manifest_location.strip():
            raise UpdateError(
                "更新マニフェストが設定されていません。"
            )

        manifest = self._load_json(manifest_location.strip())

        required = [
            "version",
            "channel",
            "download_url",
            "notes",
        ]
        missing = [
            key
            for key in required
            if key not in manifest
        ]

        if missing:
            raise UpdateError(
                "必要な項目がありません: "
                + ", ".join(missing)
            )

        channel = str(
            manifest.get("channel", "")
        ).lower()

        if channel != APP_CHANNEL.lower():
            return {
                "available": False,
                "reason": "配信チャンネルが違います。",
                "manifest": manifest,
            }

        available = (
            self._version_tuple(
                str(manifest["version"])
            )
            > self._version_tuple(APP_VERSION)
        )

        minimum_version = str(
            manifest.get(
                "minimum_version",
                "",
            )
        ).strip()
        forced = bool(
            manifest.get(
                "force_update",
                False,
            )
        )
        below_minimum = bool(
            minimum_version
            and self._version_tuple(APP_VERSION)
            < self._version_tuple(minimum_version)
        )

        if below_minimum:
            forced = True

        reason = (
            "必須アップデートがあります。"
            if available and forced
            else (
                "新しいバージョンがあります。"
                if available
                else "現在のバージョンが最新です。"
            )
        )

        return {
            "available": available,
            "forced": forced,
            "below_minimum": below_minimum,
            "reason": reason,
            "manifest": manifest,
        }


    def download_and_prepare(
        self,
        manifest: dict,
    ) -> tuple[Path, Path]:
        zip_path = self.download(manifest)
        source = self.prepare_update(zip_path)
        return zip_path, source

    def build_apply_command_from_manifest(
        self,
        manifest: dict,
    ) -> tuple[list[str], Path, Path]:
        zip_path, source = self.download_and_prepare(
            manifest
        )
        command, status_file = (
            self.create_apply_command(source)
        )
        return command, status_file, zip_path

    def download(self, manifest: dict) -> Path:
        url = str(
            manifest.get("download_url", "")
        ).strip()

        if not url:
            raise UpdateError(
                "ダウンロードURLがありません。"
            )

        version = str(
            manifest.get("version", "unknown")
        )
        destination = (
            self.temp_dir
            / f"PokeyoyaKun_{version}.zip"
        )

        self._download_file(url, destination)

        expected = str(
            manifest.get("sha256", "")
        ).strip().lower()

        if expected:
            actual = self._sha256(destination)
            if actual != expected:
                destination.unlink(missing_ok=True)
                raise UpdateError(
                    "SHA-256が一致しません。"
                )

        if not zipfile.is_zipfile(destination):
            destination.unlink(missing_ok=True)
            raise UpdateError(
                "更新ファイルが正しいZIPではありません。"
            )

        return destination

    def prepare_update(self, zip_path: Path) -> Path:
        extract_dir = self.temp_dir / "extracted"

        if extract_dir.exists():
            shutil.rmtree(extract_dir)

        extract_dir.mkdir(parents=True)

        with zipfile.ZipFile(zip_path, "r") as archive:
            archive.extractall(extract_dir)

        roots = [
            item
            for item in extract_dir.iterdir()
            if item.is_dir()
        ]

        if len(roots) != 1:
            raise UpdateError(
                "更新ZIPの最上位フォルダーは1つにしてください。"
            )

        source = roots[0]

        if is_frozen():
            required = [
                source / "ポケヨヤ君.exe",
                source / "ポケヨヤ君_設定.exe",
            ]
        else:
            required = [
                source / "app",
                source / "tools",
            ]

        missing = [
            path.name
            for path in required
            if not path.exists()
        ]

        if missing:
            raise UpdateError(
                "更新ZIPに必要なファイルがありません: "
                + ", ".join(missing)
            )

        return source

    def create_apply_command(
        self,
        update_source: Path,
    ) -> tuple[list[str], Path]:
        status_file = self.temp_dir / "update_result.json"
        status_file.unlink(missing_ok=True)

        if is_frozen():
            updater_exe = (
                self.install_root
                / "ポケヨヤ君_Updater.exe"
            )

            if not updater_exe.exists():
                raise UpdateError(
                    "ポケヨヤ君_Updater.exeが"
                    "アプリ本体と同じフォルダーにありません。"
                )

            launch_command = [
                str(
                    self.install_root
                    / "ポケヨヤ君.exe"
                )
            ]
            command = [
                str(updater_exe),
                "--pid",
                str(self._current_pid()),
            ]
        else:
            updater_script = (
                self.install_root
                / "tools"
                / "apply_update.py"
            )

            if not updater_script.exists():
                raise UpdateError(
                    "tools/apply_update.pyが見つかりません。"
                )

            launch_command = [
                sys.executable,
                str(
                    self.install_root
                    / "app"
                    / "monitor_main.py"
                ),
            ]
            command = [
                sys.executable,
                str(updater_script),
                "--pid",
                str(self._current_pid()),
            ]

        command.extend(
            [
                "--source",
                str(update_source),
                "--target",
                str(self.install_root),
                "--launch-json",
                json.dumps(launch_command, ensure_ascii=False),
                "--status-file",
                str(status_file),
            ]
        )

        return command, status_file

    def launch_apply_command(
        self,
        command: list[str],
    ) -> None:
        subprocess.Popen(
            command,
            cwd=str(self.install_root),
            close_fds=True,
        )

    def create_test_manifest(self) -> Path:
        path = self.temp_dir / "test_manifest.json"
        path.write_text(
            json.dumps(
                {
                    "version": "9.9.9",
                    "channel": APP_CHANNEL,
                    "download_url": "",
                    "sha256": "",
                    "notes": (
                        "これは更新画面の動作確認用です。\n"
                        "実際の更新ファイルは取得しません。"
                    ),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return path

    def read_last_result(self) -> dict | None:
        path = self.temp_dir / "update_result.json"

        if not path.exists():
            return None

        try:
            return json.loads(
                path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError):
            return None

    def _load_json(self, location: str) -> dict:
        parsed = urllib.parse.urlparse(location)

        if parsed.scheme in (
            "http",
            "https",
            "file",
        ):
            request = urllib.request.Request(
                location,
                headers={
                    "User-Agent": self.USER_AGENT
                },
            )

            try:
                with urllib.request.urlopen(
                    request,
                    timeout=15,
                ) as response:
                    raw = response.read()
            except urllib.error.URLError as error:
                raise UpdateError(
                    "更新情報へ接続できません。"
                ) from error

            try:
                return json.loads(
                    raw.decode("utf-8-sig")
                )
            except (
                UnicodeDecodeError,
                json.JSONDecodeError,
            ) as error:
                raise UpdateError(
                    "更新情報を読み込めません。"
                ) from error

        path = Path(location)

        if not path.exists():
            raise UpdateError(
                "更新情報ファイルが見つかりません。"
            )

        try:
            return json.loads(
                path.read_text(
                    encoding="utf-8-sig"
                )
            )
        except (
            OSError,
            json.JSONDecodeError,
        ) as error:
            raise UpdateError(
                "更新情報を読み込めません。"
            ) from error

    def _download_file(
        self,
        url: str,
        destination: Path,
    ) -> None:
        parsed = urllib.parse.urlparse(url)

        if parsed.scheme in (
            "http",
            "https",
            "file",
        ):
            request = urllib.request.Request(
                url,
                headers={
                    "User-Agent": self.USER_AGENT
                },
            )

            try:
                with urllib.request.urlopen(
                    request,
                    timeout=60,
                ) as response:
                    with destination.open("wb") as output:
                        shutil.copyfileobj(
                            response,
                            output,
                        )
            except urllib.error.URLError as error:
                raise UpdateError(
                    "更新ZIPを取得できません。"
                ) from error

            return

        source = Path(url)

        if not source.exists():
            raise UpdateError(
                "更新ZIPが見つかりません。"
            )

        shutil.copy2(source, destination)

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()

        with path.open("rb") as file:
            for chunk in iter(
                lambda: file.read(1024 * 1024),
                b"",
            ):
                digest.update(chunk)

        return digest.hexdigest()

    @staticmethod
    def _version_tuple(version: str) -> tuple[int, ...]:
        result = []

        for part in (
            version.strip()
            .lstrip("vV")
            .split(".")
        ):
            digits = "".join(
                character
                for character in part
                if character.isdigit()
            )
            result.append(int(digits or 0))

        return tuple(result)

    @staticmethod
    def _current_pid() -> int:
        import os
        return os.getpid()
