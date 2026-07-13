import json
from pathlib import Path

from core.runtime_paths import app_root
from core.user_data_migration import UserDataMigration


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
            "manifest_url": "",
            "channel": "dev",
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

    def __init__(self):
        self.root = app_root()

    def run(self) -> list[str]:
        messages = []
        messages.extend(UserDataMigration().run())

        for folder_name in self.REQUIRED_FOLDERS:
            folder = self.root / folder_name
            if not folder.exists():
                folder.mkdir(parents=True, exist_ok=True)
                messages.append(f"{folder_name}フォルダーを作成")

        for relative_path, default_value in self.JSON_DEFAULTS.items():
            path = self.root / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)

            if not path.exists():
                self._write_json(path, default_value)
                messages.append(f"{relative_path}を作成")
                continue

            try:
                json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                broken_path = path.with_suffix(path.suffix + ".broken")
                try:
                    if broken_path.exists():
                        broken_path.unlink()
                    path.replace(broken_path)
                except OSError:
                    pass

                self._write_json(path, default_value)
                messages.append(f"{relative_path}を破損から復旧")

        return messages

    @staticmethod
    def _write_json(path: Path, value) -> None:
        path.write_text(
            json.dumps(value, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
