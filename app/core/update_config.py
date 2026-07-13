import json
from pathlib import Path


DEFAULT_UPDATE_CONFIG = {
    "manifest_url": "",
    "channel": "stable",
    "check_on_startup": True,
    "allow_beta": False,
}


class UpdateConfig:
    def __init__(self):
        self.path = (
            Path(__file__).resolve().parents[2]
            / "config"
            / "update_settings.json"
        )

    def load(self):
        if not self.path.exists():
            self.save(DEFAULT_UPDATE_CONFIG)
            return dict(DEFAULT_UPDATE_CONFIG)

        try:
            data = json.loads(
                self.path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError):
            return dict(DEFAULT_UPDATE_CONFIG)

        result = dict(DEFAULT_UPDATE_CONFIG)
        if isinstance(data, dict):
            result.update(data)
        return result

    def save(self, config):
        self.path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        self.path.write_text(
            json.dumps(
                config,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
