from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from core.runtime_paths import app_root


class StoreCandidateManager:
    """未承認店舗を監視対象へ直結させず候補として保存する。"""

    def __init__(self):
        self.path = app_root() / "data" / "store_candidates.json"

    def add_candidate(self, hit: dict[str, Any]) -> bool:
        host = str(hit.get("host", "")).casefold()
        name = str(hit.get("name", "")).strip()
        url = str(hit.get("url", "")).strip()
        parsed = urlparse(url)
        if (
            not host or not name or not url
            or parsed.scheme != "https"
            or (parsed.hostname or "").casefold() != host
        ):
            return False
        items = self.load()
        digest = hashlib.sha256(f"{host}|{name}".encode()).hexdigest()[:16]
        if any(item.get("id") == digest for item in items):
            return False
        items.append({
            "id": digest,
            "name": name,
            "host": host,
            "sample_url": url,
            "status": "管理者確認待ち",
            "created_at": datetime.now().isoformat(timespec="seconds"),
        })
        self._save(items)
        return True

    def load(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        return data if isinstance(data, list) else []

    def _save(self, items: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8"
        )
