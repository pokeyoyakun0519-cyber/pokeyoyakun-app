from __future__ import annotations

import json
from pathlib import Path

from core.runtime_paths import app_root


class FavoritesManager:
    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root is not None else app_root()
        self.path = self.root / "config" / "favorites.json"

    def load(self) -> dict[str, list[str]]:
        default = {"products": [], "stores": []}
        if not self.path.exists():
            return default
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return default
        if not isinstance(data, dict):
            return default
        return {
            "products": sorted({str(value) for value in data.get("products", []) if value}),
            "stores": sorted({str(value) for value in data.get("stores", []) if value}),
        }

    def is_favorite(self, kind: str, item_id: object) -> bool:
        return str(item_id) in self.load()[self._key(kind)]

    def set_favorite(self, kind: str, item_id: object, enabled: bool) -> None:
        key = self._key(kind)
        data = self.load()
        values = set(data[key])
        value = str(item_id)
        if enabled:
            values.add(value)
        else:
            values.discard(value)
        data[key] = sorted(values)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)

    @staticmethod
    def _key(kind: str) -> str:
        if kind not in {"product", "store"}:
            raise ValueError("お気に入り種別はproductまたはstoreです。")
        return kind + "s"
