import json
import platform
import sys
from datetime import datetime
from pathlib import Path

from core.runtime_paths import app_root, install_root
from core.version import APP_CHANNEL, APP_VERSION


class SelfTestManager:
    def __init__(self):
        self.install_root = install_root()
        self.user_root = app_root()

    def run_all(self) -> list[dict]:
        checks = [
            self._check_python_version,
            self._check_required_files,
            self._check_required_folders,
            self._check_json_files,
            self._check_log_writable,
            self._check_version_info,
        ]

        results = []

        for check in checks:
            try:
                result = check()
            except Exception as error:
                result = {
                    "name": check.__name__,
                    "success": False,
                    "message": str(error),
                }

            results.append(result)

        return results

    def export_report(
        self,
        destination: Path,
        results: list[dict],
    ) -> Path:
        destination.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        report = {
            "created_at": datetime.now().isoformat(
                timespec="seconds"
            ),
            "app_version": APP_VERSION,
            "channel": APP_CHANNEL,
            "python": sys.version,
            "platform": platform.platform(),
            "install_root": str(self.install_root),
            "user_root": str(self.user_root),
            "results": results,
        }

        destination.write_text(
            json.dumps(
                report,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return destination

    def _check_python_version(self):
        supported = sys.version_info >= (3, 11)

        return {
            "name": "Pythonバージョン",
            "success": supported,
            "message": (
                f"{platform.python_version()} "
                + ("対応範囲です。" if supported else "3.11以上が必要です。")
            ),
        }

    def _check_required_files(self):
        required = [
            self.install_root / "app" / "monitor_main.py",
            self.install_root / "app" / "settings_main.py",
            self.install_root / "app" / "ui" / "main_window.py",
        ]

        missing = [
            str(path.relative_to(self.install_root))
            for path in required
            if not path.exists()
        ]

        return {
            "name": "必須ファイル",
            "success": not missing,
            "message": (
                "すべて存在します。"
                if not missing
                else "不足: " + ", ".join(missing)
            ),
        }

    def _check_required_folders(self):
        required = [
            self.user_root / "config",
            self.user_root / "data",
            self.user_root / "logs",
            self.user_root / "backup",
            self.user_root / "temp",
        ]

        missing = [
            path.name
            for path in required
            if not path.exists()
        ]

        return {
            "name": "ユーザーデータフォルダー",
            "success": not missing,
            "message": (
                "すべて存在します。"
                if not missing
                else "不足: " + ", ".join(missing)
            ),
        }

    def _check_json_files(self):
        targets = [
            self.user_root / "config" / "sources.json",
            self.user_root / "config" / "lotteries.json",
            self.user_root / "config" / "scheduler_settings.json",
            self.user_root / "config" / "external_notification_settings.json",
        ]

        broken = []

        for path in targets:
            if not path.exists():
                continue

            try:
                json.loads(
                    path.read_text(encoding="utf-8")
                )
            except (
                OSError,
                json.JSONDecodeError,
            ):
                broken.append(path.name)

        return {
            "name": "JSON設定ファイル",
            "success": not broken,
            "message": (
                "読み込み可能です。"
                if not broken
                else "破損: " + ", ".join(broken)
            ),
        }

    def _check_log_writable(self):
        logs_dir = self.user_root / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        test_path = logs_dir / ".write_test"
        test_path.write_text(
            "ok",
            encoding="utf-8",
        )
        test_path.unlink(missing_ok=True)

        return {
            "name": "ログ書き込み権限",
            "success": True,
            "message": "書き込み可能です。",
        }

    def _check_version_info(self):
        version_file = (
            self.install_root
            / "app"
            / "core"
            / "version.py"
        )

        return {
            "name": "バージョン情報",
            "success": version_file.exists(),
            "message": (
                f"Ver.{APP_VERSION} / {APP_CHANNEL}"
            ),
        }
