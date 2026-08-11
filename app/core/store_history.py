from __future__ import annotations

import json
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any

from core.runtime_paths import app_root


class StoreHistoryManager:
    MAX_PER_STORE = 50

    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root is not None else app_root()
        self.path = self.root / "data" / "store_history.json"

    def record(self, store_id: str, action: str, detail: str = "", *, occurred_at: str = "") -> None:
        self.record_many([{
            "store_id": store_id, "action": action, "detail": detail,
            "occurred_at": occurred_at,
        }])

    def record_many(self, entries: list[dict[str, Any]]) -> int:
        data = self.load_all()
        added = 0
        for raw in entries:
            store_id = str(raw.get("store_id", ""))
            history = data.setdefault(store_id, [])
            entry = {
                "action": str(raw.get("action", "")),
                "detail": str(raw.get("detail", "")),
                "occurred_at": str(raw.get("occurred_at", "")) or datetime.now().isoformat(timespec="seconds"),
            }
            identity = f'{store_id}|{entry["action"]}|{entry["detail"]}|{entry["occurred_at"][:10]}'
            entry["id"] = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
            if any(item.get("id") == entry["id"] for item in history):
                continue
            history.insert(0, entry)
            data[store_id] = history[: self.MAX_PER_STORE]
            added += 1
        if added:
            self._save(data)
        return added

    def history(self, store_id: object) -> list[dict[str, Any]]:
        return list(self.load_all().get(str(store_id), []))

    def load_all(self) -> dict[str, list[dict[str, Any]]]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save(self, data: dict[str, list[dict[str, Any]]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)
