from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from core.runtime_paths import app_root


class ActivityTimeline:
    MAX_ITEMS = 20

    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root is not None else app_root()
        self.path = self.root / "data" / "activity_timeline.json"

    def add(self, event_type: str, title: str, *, product_id: str = "", store_id: str = "", occurred_at: str = "") -> bool:
        return bool(self.add_many([{
            "event_type": event_type, "title": title, "product_id": product_id,
            "store_id": store_id, "occurred_at": occurred_at,
        }]))

    def add_many(self, events: list[dict[str, Any]]) -> int:
        items = self.load()
        existing = {str(item.get("id", "")) for item in items}
        added = 0
        for raw in events:
            occurred = str(raw.get("occurred_at", "")) or datetime.now().isoformat(timespec="seconds")
            event_type = str(raw.get("event_type", ""))
            title = str(raw.get("title", ""))
            product_id = str(raw.get("product_id", ""))
            store_id = str(raw.get("store_id", ""))
            identity = f"{event_type}|{title}|{product_id}|{store_id}|{occurred[:10]}"
            event_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
            if event_id in existing:
                continue
            existing.add(event_id)
            items.insert(0, {
                "id": event_id, "event_type": event_type, "title": title,
                "product_id": product_id, "store_id": store_id, "occurred_at": occurred,
            })
            added += 1
        if added:
            self._save(items[: self.MAX_ITEMS])
        return added

    def load(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        return data[: self.MAX_ITEMS] if isinstance(data, list) else []

    def _save(self, items: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)
