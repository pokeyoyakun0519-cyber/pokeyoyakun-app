from __future__ import annotations

import hashlib
import ipaddress
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse
from urllib.request import Request

from core.runtime_paths import app_root
from core.secure_https import build_https_opener


class ProductImageCache:
    """商品画像をHTTPSで一度だけ取得し、版が変わるまで再利用する。"""

    MAX_BYTES = 8_000_000

    def __init__(self, root: Path | None = None, downloader: Callable[[str], tuple[bytes, str]] | None = None):
        self.root = Path(root) if root is not None else app_root()
        self.cache_dir = self.root / "cache" / "product_images"
        self.metadata_path = self.cache_dir / "index.json"
        self.downloader = downloader or self._download

    def get(self, product_id: object, image_url: object, *, version: object = "") -> Path | None:
        url = str(image_url or "").strip()
        if not self._safe_url(url):
            return None
        key = str(product_id)
        metadata = self._load_metadata()
        current = metadata.get(key, {})
        cached = self.cache_dir / str(current.get("filename", ""))
        if (
            current.get("url") == url
            and str(current.get("version", "")) == str(version or "")
            and cached.is_file()
        ):
            current["last_accessed_at"] = datetime.now().isoformat(timespec="seconds")
            metadata[key] = current
            self._save_metadata(metadata)
            return cached

        payload, content_type = self.downloader(url)
        if not payload or len(payload) > self.MAX_BYTES or not content_type.casefold().startswith("image/"):
            return None
        extension = self._extension(content_type)
        filename = hashlib.sha256(f"{key}|{url}|{version}".encode("utf-8")).hexdigest()[:24] + extension
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        target = self.cache_dir / filename
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_bytes(payload)
        temporary.replace(target)
        old_filename = str(current.get("filename", ""))
        if old_filename and old_filename != filename:
            (self.cache_dir / old_filename).unlink(missing_ok=True)
        now = datetime.now().isoformat(timespec="seconds")
        metadata[key] = {
            "url": url, "version": str(version or ""), "filename": filename,
            "content_type": content_type, "updated_at": now, "last_accessed_at": now,
        }
        self._save_metadata(metadata)
        return target

    def cached_path(self, product_id: object, image_url: object, *, version: object = "") -> Path | None:
        current = self._load_metadata().get(str(product_id), {})
        path = self.cache_dir / str(current.get("filename", ""))
        if (
            current.get("url") == str(image_url or "").strip()
            and str(current.get("version", "")) == str(version or "")
            and path.is_file()
        ):
            return path
        return None

    def cleanup(self, *, max_age_days: int = 90, active_product_ids: set[str] | None = None, now: datetime | None = None) -> int:
        current_time = now or datetime.now()
        metadata = self._load_metadata()
        removed = 0
        active = active_product_ids if active_product_ids is not None else set(metadata)
        for key, item in list(metadata.items()):
            try:
                accessed = datetime.fromisoformat(str(item.get("last_accessed_at", "")))
            except ValueError:
                accessed = datetime.min
            if key not in active or current_time - accessed > timedelta(days=max_age_days):
                (self.cache_dir / str(item.get("filename", ""))).unlink(missing_ok=True)
                metadata.pop(key, None)
                removed += 1
        if removed:
            self._save_metadata(metadata)
        return removed

    def _download(self, url: str) -> tuple[bytes, str]:
        request = Request(url, headers={"User-Agent": "PokeyoyaKun/ProductImageCache"})
        with build_https_opener().open(request, timeout=20) as response:
            final_url = response.geturl()
            if not self._safe_url(final_url):
                return b"", ""
            return response.read(self.MAX_BYTES + 1), str(response.headers.get_content_type())

    @staticmethod
    def _safe_url(url: str) -> bool:
        try:
            parsed = urlparse(url)
            host = (parsed.hostname or "").casefold().strip(".")
            if parsed.scheme != "https" or not host or parsed.port not in (None, 443) or parsed.username:
                return False
            if host == "localhost" or host.endswith((".localhost", ".local")):
                return False
            try:
                ipaddress.ip_address(host)
                return False
            except ValueError:
                return True
        except ValueError:
            return False

    @staticmethod
    def _extension(content_type: str) -> str:
        return {"image/png": ".png", "image/webp": ".webp", "image/gif": ".gif"}.get(content_type.casefold(), ".jpg")

    def _load_metadata(self) -> dict:
        if not self.metadata_path.exists():
            return {}
        try:
            data = json.loads(self.metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save_metadata(self, metadata: dict) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        temporary = self.metadata_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.metadata_path)
