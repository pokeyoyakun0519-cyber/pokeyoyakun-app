from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from core.builtin_store_catalog import (
    build_alias_index,
    load_builtin_store_catalog,
    match_builtin_store,
    normalize_store_name,
)
from core.runtime_paths import app_root


CANDIDATE_STATES = {
    "new", "reviewing", "approved", "rejected", "duplicate",
    "insufficient_evidence", "monitoring_unsupported",
}


class StoreCandidateManager:
    """未知店舗をサイトマスタへ直結させず、根拠付き候補として保存する。"""

    def __init__(self, root: Path | None = None):
        self.path = (Path(root) if root is not None else app_root()) / "data" / "store_candidates.json"
        self.catalog = load_builtin_store_catalog()["stores"]
        self.alias_index = build_alias_index(self.catalog)
        self.last_result: dict[str, Any] = {}

    def add_candidate(self, hit: dict[str, Any]) -> bool:
        now = datetime.now().isoformat(timespec="seconds")
        name = str(hit.get("name", "")).strip()
        url = str(hit.get("official_url_candidate") or hit.get("url", "")).strip()
        safety_error = self._url_safety_error(url)
        if not name or safety_error:
            self.last_result = {
                "saved": False,
                "status": "insufficient_evidence" if not name else "rejected",
                "reason": "店舗名がありません" if not name else safety_error,
            }
            return False

        host = (urlparse(url).hostname or "").casefold()
        supplied_host = str(hit.get("host", host)).strip().casefold()
        if supplied_host and supplied_host != host:
            self.last_result = {"saved": False, "status": "rejected", "reason": "URLとhostが一致しません"}
            return False

        known = match_builtin_store(
            self.catalog,
            name=name,
            url=url,
            official_social_url=hit.get("official_social_url", ""),
            store_code=hit.get("store_code", ""),
            channel=hit.get("channel", ""),
        )
        if known:
            self.last_result = {
                "saved": False,
                "status": "duplicate",
                "reason": "標準店舗と一致",
                "canonical_store_id": known["canonical_store_id"],
            }
            return False

        confidence = max(0.0, min(1.0, float(hit.get("confidence", 0.5))))
        evidence = self._evidence(hit, url, now)
        if not evidence:
            self.last_result = {
                "saved": False, "status": "insufficient_evidence", "reason": "発見根拠がありません"
            }
            return False

        items = self.load()
        normalized_name = normalize_store_name(name)
        duplicate = next(
            (
                item for item in items
                if str(item.get("host", "")).casefold() == host
                or normalize_store_name(item.get("name")) == normalized_name
                or (
                    hit.get("official_social_url")
                    and item.get("official_social_url") == hit.get("official_social_url")
                )
                or (hit.get("store_code") and item.get("store_code") == hit.get("store_code"))
            ),
            None,
        )
        if duplicate:
            existing = list(duplicate.get("evidence", []))
            known_keys = {(str(item.get("source_url", "")), str(item.get("url", ""))) for item in existing}
            for item in evidence:
                key = (item["source_url"], item["url"])
                if key not in known_keys:
                    existing.append(item)
            duplicate["evidence"] = existing[-20:]
            duplicate["last_detected_at"] = now
            duplicate["confidence"] = max(float(duplicate.get("confidence", 0)), confidence)
            try:
                self._save(items)
            except OSError as error:
                self.last_result = {"saved": False, "status": "duplicate", "reason": f"候補更新失敗: {error}"}
                return False
            self.last_result = {"saved": False, "status": "duplicate", "reason": "既存候補と重複"}
            return False

        digest = hashlib.sha256(f"{host}|{normalized_name}".encode()).hexdigest()[:16]
        status = "new" if bool(hit.get("monitoring_supported", True)) else "monitoring_unsupported"
        candidate = {
            "id": digest,
            "name": name,
            "normalized_name": normalized_name,
            "chain_name": str(hit.get("chain_name", name)),
            "channel": str(hit.get("channel", "unknown")),
            "store_code": str(hit.get("store_code", "")),
            "official_social_url": str(hit.get("official_social_url", "")),
            "host": host,
            "official_url_candidate": url,
            "sample_url": url,
            "source_url": str(hit.get("source_url", "")),
            "product_name": str(hit.get("product_name", "")),
            "tcg_key": str(hit.get("tcg_key", "unknown")) or "unknown",
            "discovery_type": str(hit.get("discovery_type", "unknown")),
            "application_period": str(hit.get("application_period", "")),
            "confidence": confidence,
            "similar_store_ids": list(hit.get("similar_store_ids", [])),
            "monitoring_supported": bool(hit.get("monitoring_supported", True)),
            "status": "管理者確認待ち",
            "candidate_state": status,
            "review_status": "管理者確認待ち",
            "evidence": evidence,
            "detected_at": now,
            "created_at": now,
            "last_detected_at": now,
        }
        items.append(candidate)
        try:
            self._save(items)
        except OSError as error:
            self.last_result = {"saved": False, "status": "new", "reason": f"候補保存失敗: {error}"}
            return False
        self.last_result = {"saved": True, "status": status, "reason": "候補を保存", "id": digest}
        return True

    def update_status(self, candidate_id: str, status: str) -> bool:
        if status not in CANDIDATE_STATES:
            raise ValueError(f"未対応の候補状態です: {status}")
        items = self.load()
        for item in items:
            if item.get("id") == candidate_id:
                item["status"] = status
                item["candidate_state"] = status
                item["updated_at"] = datetime.now().isoformat(timespec="seconds")
                self._save(items)
                return True
        return False

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
        handle, temporary_name = tempfile.mkstemp(prefix="store_candidates_", suffix=".json.tmp", dir=self.path.parent)
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as file:
                json.dump(items, file, ensure_ascii=False, indent=2)
                file.flush()
                os.fsync(file.fileno())
            Path(temporary_name).replace(self.path)
        finally:
            Path(temporary_name).unlink(missing_ok=True)

    @staticmethod
    def _evidence(hit: dict[str, Any], url: str, detected_at: str) -> list[dict[str, str]]:
        source_url = str(hit.get("source_url", "")).strip()
        evidence_type = str(hit.get("evidence_type", "detected_link")).strip()
        if not source_url and not hit.get("allow_direct_evidence", True):
            return []
        return [{
            "type": evidence_type,
            "source_url": source_url,
            "url": url,
            "text": str(hit.get("evidence_text", hit.get("name", "")))[:500],
            "detected_at": detected_at,
        }]

    @staticmethod
    def _url_safety_error(url: str) -> str:
        try:
            parsed = urlparse(url)
            port = parsed.port
        except ValueError:
            return "URL形式が不正です"
        if parsed.scheme != "https" or parsed.username or parsed.password or port not in (None, 443):
            return "安全なHTTPS URLではありません"
        host = (parsed.hostname or "").casefold().strip(".")
        if not host or host == "localhost" or host.endswith((".local", ".localhost")):
            return "ローカルホストは候補にできません"
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if address is not None:
            return "IPアドレス直指定は候補にできません"
        if host in {
            "x.com", "twitter.com", "www.instagram.com", "instagram.com",
            "www.facebook.com", "facebook.com", "www.youtube.com", "youtube.com",
            "www.tiktok.com", "tiktok.com", "linktr.ee",
        }:
            return "SNS・リンク集だけを店舗公式URLにはできません"
        return ""
