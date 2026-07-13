import json
from datetime import datetime, timedelta
from core.runtime_paths import app_root

class ErrorThrottle:
    def __init__(self):
        self.path = app_root() / "config" / "error_throttle.json"

    def should_notify(self, error_key: str, cooldown_minutes: int = 10):
        state = self._load()
        now = datetime.now()
        item = state.get(error_key, {})
        count = int(item.get("count", 0)) + 1
        last_text = str(item.get("last_notified", "")).strip()
        last = None
        if last_text:
            try:
                last = datetime.fromisoformat(last_text)
            except ValueError:
                last = None
        notify = last is None or now - last >= timedelta(minutes=max(1, cooldown_minutes))
        state[error_key] = {
            "count": count,
            "last_seen": now.isoformat(timespec="seconds"),
            "last_notified": now.isoformat(timespec="seconds") if notify else last_text,
        }
        self._save(state)
        return notify, count

    def _load(self):
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _save(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
