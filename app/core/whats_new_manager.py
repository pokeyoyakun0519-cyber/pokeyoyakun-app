import json

from core.runtime_paths import app_root
from core.version import APP_CHANNEL, APP_VERSION


CURRENT_RELEASE = f"{APP_VERSION}-{APP_CHANNEL.lower()}"


class WhatsNewManager:
    def __init__(self):
        self.path = app_root() / "config" / "whats_new_state.json"

    def should_show(self) -> bool:
        if not self.path.exists():
            return True

        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return True

        return str(data.get("last_seen_version", "")) != CURRENT_RELEASE

    def mark_seen(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(
                {"last_seen_version": CURRENT_RELEASE},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
