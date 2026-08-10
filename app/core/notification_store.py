import csv
import json
from datetime import datetime
from pathlib import Path

from core.runtime_paths import app_root


class NotificationStore:
    def __init__(self, root: Path | None = None):
        self.path = (Path(root) if root is not None else app_root()) / "config" / "notifications.json"

    def load(self) -> list[dict]:
        if not self.path.exists():
            return []

        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except (OSError, json.JSONDecodeError):
            return []

    def add(
        self,
        title: str,
        message: str,
        category: str = "情報",
        *,
        action_url: str = "",
        action_label: str = "",
        metadata: dict | None = None,
    ) -> None:
        items = self.load()
        items.insert(
            0,
            {
                "title": title,
                "message": message,
                "category": category,
                "created_at": datetime.now().strftime("%Y/%m/%d %H:%M:%S"),
                "read": False,
                "action_url": str(action_url),
                "action_label": str(action_label),
                "metadata": dict(metadata or {}),
            },
        )
        self._save(items[:500])

    def mark_all_read(self) -> None:
        items = self.load()
        for item in items:
            item["read"] = True
        self._save(items)

    def mark_filtered_read(self, indexes: list[int]) -> None:
        items = self.load()
        for index in indexes:
            if 0 <= index < len(items):
                items[index]["read"] = True
        self._save(items)

    def clear(self) -> None:
        self._save([])

    def unread_count(self) -> int:
        return sum(
            1 for item in self.load()
            if not item.get("read", False)
        )

    def export_csv(
        self,
        destination: Path,
        items: list[dict] | None = None,
    ) -> Path:
        rows = self.load() if items is None else items
        destination.parent.mkdir(parents=True, exist_ok=True)

        with destination.open(
            "w",
            encoding="utf-8-sig",
            newline="",
        ) as file:
            writer = csv.writer(file)
            writer.writerow(
                [
                    "日時",
                    "カテゴリ",
                    "タイトル",
                    "メッセージ",
                    "既読",
                ]
            )
            for item in rows:
                writer.writerow(
                    [
                        item.get("created_at", ""),
                        item.get("category", ""),
                        item.get("title", ""),
                        item.get("message", ""),
                        "はい" if item.get("read", False) else "いいえ",
                    ]
                )

        return destination

    def _save(self, items: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(items, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
