import json
from pathlib import Path
from typing import Any


DEFAULT_CONFIG = {
    "general": {
        "auto_input_enabled": False,
        "new_product_auto_fetch": True,
        "play_notification_sound": True,
        "show_popup": True,
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
        "other": True,
    },
    "sites": {
        "pokemon_center": True,
        "amazon": True,
        "rakuten": True,
        "yodobashi": True,
        "biccamera": True,
        "amiami": False,
    },
}


class ConfigManager:
    """ポケヨヤ君の設定をJSONファイルへ保存・読込する。"""

    def __init__(self):
        project_root = Path(__file__).resolve().parents[2]
        self.config_path = project_root / "config" / "settings.json"

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
        with self.config_path.open("w", encoding="utf-8") as file:
            json.dump(config, file, ensure_ascii=False, indent=2)

    def _merge_defaults(self, defaults: dict, loaded: dict) -> dict:
        result = json.loads(json.dumps(defaults))

        for key, value in loaded.items():
            if isinstance(value, dict) and isinstance(result.get(key), dict):
                result[key].update(value)
            else:
                result[key] = value

        return result
