import json
import shutil
from pathlib import Path
from typing import Any

from core.runtime_paths import app_root


DEFAULT_CONFIG = {
    "general": {
        "setup_completed": False,
        "setup_version": 0,
        "ui_mode": "simple",
        "auto_input_enabled": False,
        "new_product_auto_fetch": True,
        "play_notification_sound": True,
        "show_popup": True,
        "auto_monitor_new_releases": True,
        "auto_monitor_days_before": 30,
        "show_ended_applications": False,
        "notify_new_monitoring_sites": True,
        "priority_monitoring_only": False,
        "startup_retail_search": False,
    },
    "profile": {
        "name": "",
        "furigana": "",
        "email": "",
        "phone": "",
        "postal_code": "",
        "address": "",
    },
    "notification": {
        "sound_file": "",
    },
    "games": {
        "pokemon": True,
        "onepiece": True,
        "yugioh": True,
        "gundam": True,
        "union_arena": True,
        "other": True,
    },
    "sites": {
        "pokemon_center_online": True,
        "amazon_jp": True,
        "rakuten_books": True,
        "yodobashi_lottery": True,
        "biccamera": True,
        "amiami": False,
    },
    "site_sync": {
        "known_site_ids": [],
        "new_site_ids": [],
        "last_synced_at": "",
    },
    "application_assistant": {
        "deadline_reminders_enabled": True,
        "reminders": [
            {"minutes": 1440, "enabled": True, "label": "24時間前"},
            {"minutes": 180, "enabled": True, "label": "3時間前"},
            {"minutes": 30, "enabled": True, "label": "30分前"},
        ],
        "group_by_product": True,
        "important_changes_only": True,
    },
}


class ConfigManager:
    """ポケヨヤ君の設定をJSONファイルへ保存・読込する。"""

    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root is not None else app_root()
        self.config_path = self.root / "config" / "settings.json"
        self.backup_path = self.config_path.with_suffix(".json.bak")

    def load(self) -> dict[str, Any]:
        if not self.config_path.exists():
            self.save(DEFAULT_CONFIG)
            return json.loads(json.dumps(DEFAULT_CONFIG))

        try:
            with self.config_path.open("r", encoding="utf-8") as file:
                loaded = json.load(file)
        except (OSError, json.JSONDecodeError):
            return json.loads(json.dumps(DEFAULT_CONFIG))

        return self._merge_defaults(DEFAULT_CONFIG, loaded)

    def save(self, config: dict[str, Any]) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        if self.config_path.exists():
            shutil.copy2(self.config_path, self.backup_path)
        temporary = self.config_path.with_suffix(".json.tmp")
        with temporary.open("w", encoding="utf-8") as file:
            json.dump(config, file, ensure_ascii=False, indent=2)
        temporary.replace(self.config_path)

    def rollback(self) -> bool:
        if not self.backup_path.exists():
            return False
        shutil.copy2(self.backup_path, self.config_path)
        return True

    def _merge_defaults(self, defaults: dict, loaded: dict) -> dict:
        result = json.loads(json.dumps(defaults))

        for key, value in loaded.items():
            if isinstance(value, dict) and isinstance(result.get(key), dict):
                result[key] = self._merge_defaults(result[key], value)
            else:
                result[key] = value

        return result
