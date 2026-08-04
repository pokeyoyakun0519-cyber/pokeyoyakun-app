import json
from pathlib import Path

from core.runtime_paths import app_root
from core.user_data_migration import UserDataMigration
from core.json_file_state import (
    CORRUPT,
    CANDIDATE_LIST_FIELDS,
    MISSING,
    PRODUCT_LIST_FIELDS,
    SOURCE_LIST_FIELDS,
    JsonFileResult,
    inspect_json_file,
)


class StartupCheck:
    """必要フォルダーと最低限のJSONファイルを確認・補修する。"""

    REQUIRED_FOLDERS = [
        "config",
        "data",
        "logs",
        "temp",
        "backup",
    ]

    JSON_DEFAULTS = {
        "config/update_settings.json": {
            "check_on_startup": True,
            "allow_prerelease": False,
        },
        "config/user_state.json": {
            "reserved_product_ids": [],
        },
        "config/sources.json": [],
        "config/lotteries.json": [],
        "data/products.json": [],
        "data/candidates.json": [],
        "config/notifications.json": [],
        "config/whats_new_state.json": {
            "last_seen_version": "",
        },
        "config/regression_checklist.json": {
            "updated_at": "",
            "items": [],
        },
        "config/external_notification_settings.json": {
            "discord_enabled": False,
            "discord_webhook_url": "",
            "email_enabled": False,
            "smtp_host": "",
            "smtp_port": 587,
            "smtp_use_tls": True,
            "smtp_username": "",
            "smtp_password": "",
            "email_from": "",
            "email_to": "",
            "notify_source_changes": True,
            "notify_lottery_wins": True,
            "notify_errors": True,
        },
        "config/behavior_settings.json": {
            "start_minimized": False,
            "minimize_to_tray": True,
            "close_to_tray": True,
            "show_tray_notifications": True,
        },
        "config/scheduler_settings.json": {
            "enabled": False,
            "interval_minutes": 30,
            "check_sources": True,
            "check_lotteries": True,
            "last_run": "",
        },
    }

    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root is not None else app_root()
        self.json_issues: list[JsonFileResult] = []

    def run(self) -> list[str]:
        messages = []
        self.json_issues = []
        messages.extend(UserDataMigration().run())

        for folder_name in self.REQUIRED_FOLDERS:
            folder = self.root / folder_name
            if not folder.exists():
                folder.mkdir(parents=True, exist_ok=True)
                messages.append(f"{folder_name}フォルダーを作成")

        for relative_path, default_value in self.JSON_DEFAULTS.items():
            path = self.root / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)

            if relative_path == "data/products.json":
                nullable_fields = PRODUCT_LIST_FIELDS
            elif relative_path == "data/candidates.json":
                nullable_fields = CANDIDATE_LIST_FIELDS
            elif relative_path == "config/sources.json":
                nullable_fields = SOURCE_LIST_FIELDS
            else:
                nullable_fields = ()
            result = inspect_json_file(
                path,
                type(default_value),
                nullable_list_fields=nullable_fields,
            )
            if result.state == MISSING:
                self._write_json(path, default_value)
                messages.append(f"{relative_path}を作成")
                continue
            if result.state == CORRUPT:
                self.json_issues.append(result)
                recovery = "（バックアップから復元可能）" if result.recoverable else ""
                messages.append(f"{relative_path}が破損{recovery}")

        master_path = self.root / "data" / "product_master.json"
        master_result = inspect_json_file(
            master_path,
            list,
            nullable_list_fields=PRODUCT_LIST_FIELDS,
        )
        if master_result.state == CORRUPT:
            self.json_issues.append(master_result)
            recovery = "（バックアップから復元可能）" if master_result.recoverable else ""
            messages.append(f"data/product_master.jsonが破損{recovery}")

        return messages

    @staticmethod
    def _write_json(path: Path, value) -> None:
        path.write_text(
            json.dumps(value, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
