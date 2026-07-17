import json
from core.runtime_paths import app_root


DEFAULT_UPDATE_CONFIG = {
    "check_on_startup": True,
    "allow_prerelease": False,
}


class UpdateConfig:
    def __init__(self, edition_id: str = "user"):
        filename = "owner_update_settings.json" if edition_id == "owner" else "update_settings.json"
        self.path = app_root() / "config" / filename

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
