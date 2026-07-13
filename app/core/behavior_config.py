import json
from core.runtime_paths import app_root

DEFAULT_CONFIG = {
    "start_minimized": False,
    "minimize_to_tray": True,
    "close_to_tray": True,
    "show_tray_notifications": True,
}

class BehaviorConfig:
    def __init__(self):
        self.path = app_root() / "config" / "behavior_settings.json"

    def load(self):
        if not self.path.exists():
            self.save(DEFAULT_CONFIG)
            return dict(DEFAULT_CONFIG)
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return dict(DEFAULT_CONFIG)
        result = dict(DEFAULT_CONFIG)
        if isinstance(data, dict):
            result.update(data)
        return result

    def save(self, config):
        result = dict(DEFAULT_CONFIG)
        result.update(config)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
