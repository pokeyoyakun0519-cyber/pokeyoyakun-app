from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from core.runtime_paths import app_root


ALLOWED_FIELDS = ("kind", "receipt_id", "submitted_at", "last_status")


class FeedbackReceiptHistory:
    def __init__(self, path: Path | None = None):
        self.path = path or (app_root() / "data" / "feedback_receipts.json")

    def load(self) -> list[dict[str, str]]:
        if not self.path.is_file():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        if not isinstance(raw, list):
            return []
        items: list[dict[str, str]] = []
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            item = {key: str(entry.get(key, "")) for key in ALLOWED_FIELDS}
            if item["receipt_id"]:
                items.append(item)
        return items[:200]

    def add(self, kind: str, receipt_id: str, status: str) -> dict[str, str]:
        item = {
            "kind": str(kind),
            "receipt_id": str(receipt_id),
            "submitted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "last_status": str(status or "pending"),
        }
        items = [entry for entry in self.load() if entry["receipt_id"] != item["receipt_id"]]
        items.insert(0, item)
        self._save(items[:200])
        return item

    def update_status(self, receipt_id: str, status: str) -> None:
        items = self.load()
        for item in items:
            if item["receipt_id"] == receipt_id:
                item["last_status"] = str(status)
                break
        self._save(items)

    def _save(self, items: list[dict[str, str]]) -> None:
        safe_items = [
            {key: str(item.get(key, "")) for key in ALLOWED_FIELDS}
            for item in items
        ]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(safe_items, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)
