from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode, urlsplit

from core.runtime_paths import app_root
from core.version import APP_VERSION
from core.secure_https import TlsConfigurationError, build_https_opener


PUBLIC_ROADMAP_ORIGIN = "https://pokeyoyakun.duckdns.org"
CACHE_TTL_SECONDS = 5 * 60
PUBLIC_ITEM_FIELDS = {
    "cluster_id",
    "title",
    "summary",
    "tcg_keys",
    "message_count",
    "status",
    "updated_at",
}
TCG_LABELS = {
    "pokemon": "ポケモンカード",
    "onepiece": "ワンピースカード",
    "yugioh": "遊戯王OCG",
    "gundam": "ガンダムカード",
    "other": "その他",
}
STATUS_LABELS = {
    "received": "受付済み",
    "considering": "検討中",
    "planned": "実装予定",
    "in_development": "開発中",
    "completed": "完成",
    "declined": "見送り",
}


class PublicRoadmapError(RuntimeError):
    pass


class PublicRoadmapValidationError(ValueError):
    pass


@dataclass(frozen=True)
class RoadmapResult:
    payload: dict[str, Any]
    from_cache: bool = False
    offline: bool = False


def _safe_int(value: Any, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise PublicRoadmapError(f"公開ロードマップの{label}が不正です。")
    return value


def sanitize_public_item(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PublicRoadmapError("公開ロードマップ項目の形式が不正です。")
    cluster_id = _safe_int(value.get("cluster_id"), "ID", minimum=1)
    title = str(value.get("title", "")).strip()
    summary = str(value.get("summary", "")).strip()
    updated_at = str(value.get("updated_at", "")).strip()
    status = str(value.get("status", "")).strip()
    if not title or not summary or not updated_at:
        raise PublicRoadmapError("公開ロードマップの表示項目が不足しています。")
    if status not in STATUS_LABELS:
        raise PublicRoadmapError("公開ロードマップに未知の状態が含まれています。")
    raw_tcg_keys = value.get("tcg_keys")
    if not isinstance(raw_tcg_keys, list):
        raise PublicRoadmapError("公開ロードマップのTCG情報が不正です。")
    tcg_keys: list[str] = []
    for raw_key in raw_tcg_keys:
        key = str(raw_key).strip().lower()
        if key not in TCG_LABELS:
            raise PublicRoadmapError("公開ロードマップに未知のTCGが含まれています。")
        if key not in tcg_keys:
            tcg_keys.append(key)
    return {
        "cluster_id": cluster_id,
        "title": title,
        "summary": summary,
        "tcg_keys": tcg_keys,
        "message_count": _safe_int(value.get("message_count"), "要望件数"),
        "status": status,
        "updated_at": updated_at,
    }


def sanitize_public_list(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or not isinstance(value.get("items"), list):
        raise PublicRoadmapError("公開ロードマップ一覧の形式が不正です。")
    items = [sanitize_public_item(item) for item in value["items"]]
    categories = value.get("categories", list(TCG_LABELS))
    if not isinstance(categories, list):
        categories = list(TCG_LABELS)
    clean_categories = [
        key for key in TCG_LABELS if key in {str(item) for item in categories}
    ]
    generated_at = value.get("generated_at")
    return {
        "total": _safe_int(value.get("total", len(items)), "総件数"),
        "page": _safe_int(value.get("page", 1), "ページ", minimum=1),
        "page_size": _safe_int(
            value.get("page_size", max(1, len(items))), "ページサイズ", minimum=1
        ),
        "generated_at": str(generated_at).strip() if generated_at else None,
        "categories": clean_categories,
        "items": items,
    }


class PublicRoadmapHttpsRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self):
        super().__init__()
        approved = urlsplit(PUBLIC_ROADMAP_ORIGIN)
        self._approved_origin = (
            approved.scheme.lower(),
            approved.hostname,
            approved.port or 443,
        )

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        try:
            redirected = urlsplit(newurl)
            origin = (
                redirected.scheme.lower(),
                redirected.hostname,
                redirected.port or 443,
            )
        except (TypeError, ValueError) as error:
            raise urllib.error.URLError("不正なリダイレクトを拒否しました。") from error
        if (
            redirected.scheme.lower() != "https"
            or redirected.username is not None
            or redirected.password is not None
            or origin != self._approved_origin
        ):
            raise urllib.error.URLError(
                "HTTPSの同一ホスト・同一ポート以外へのリダイレクトを拒否しました。"
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class PublicRoadmapCache:
    def __init__(self, path: Path | None = None):
        self.path = path or (app_root() / "data" / "public_roadmap_cache.json")

    def _load(self) -> dict[str, Any]:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return {"schema_version": 1, "lists": {}, "details": {}}
        if not isinstance(value, dict) or value.get("schema_version") != 1:
            return {"schema_version": 1, "lists": {}, "details": {}}
        return value

    def get(self, section: str, key: str) -> dict[str, Any] | None:
        section_data = self._load().get(section, {})
        if not isinstance(section_data, dict):
            return None
        value = section_data.get(key)
        if not isinstance(value, dict):
            return None
        try:
            payload = (
                sanitize_public_list(value.get("payload"))
                if section == "lists"
                else sanitize_public_item(value.get("payload"))
            )
            cached_at = float(value.get("cached_at"))
        except (PublicRoadmapError, TypeError, ValueError):
            return None
        return {
            "payload": payload,
            "etag": str(value.get("etag", "")),
            "cached_at": cached_at,
        }

    def put(
        self,
        section: str,
        key: str,
        payload: dict[str, Any],
        etag: str,
        cached_at: float,
    ) -> None:
        clean_payload = (
            sanitize_public_list(payload)
            if section == "lists"
            else sanitize_public_item(payload)
        )
        data = self._load()
        target = data.setdefault(section, {})
        if not isinstance(target, dict):
            target = {}
            data[section] = target
        target[key] = {
            "payload": clean_payload,
            "etag": str(etag),
            "cached_at": float(cached_at),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(self.path)


class PublicRoadmapClient:
    def __init__(
        self,
        timeout_seconds: int = 15,
        cache: PublicRoadmapCache | None = None,
        clock: Callable[[], float] = time.time,
        opener=None,
    ):
        self.timeout_seconds = max(3, min(60, int(timeout_seconds)))
        self.cache = cache or PublicRoadmapCache()
        self.clock = clock
        self._opener = opener

    def list_roadmap(
        self,
        tcg_key: str = "",
        status: str = "",
        *,
        force: bool = False,
    ) -> RoadmapResult:
        tcg_key = str(tcg_key).strip().lower()
        status = str(status).strip().lower()
        if tcg_key and tcg_key not in TCG_LABELS:
            raise PublicRoadmapValidationError("未対応のTCGフィルターです。")
        if status and status not in STATUS_LABELS:
            raise PublicRoadmapValidationError("未対応の状態フィルターです。")
        query = {"page": 1, "page_size": 100}
        if tcg_key:
            query["tcg_key"] = tcg_key
        if status:
            query["status"] = status
        cache_key = urlencode(sorted(query.items()))
        path = "/api/v1/public/roadmap?" + urlencode(query)
        return self._get(path, "lists", cache_key, sanitize_public_list, force)

    def roadmap_detail(self, cluster_id: int, *, force: bool = False) -> RoadmapResult:
        cluster_id = _safe_int(cluster_id, "ID", minimum=1)
        return self._get(
            f"/api/v1/public/roadmap/{cluster_id}",
            "details",
            str(cluster_id),
            sanitize_public_item,
            force,
        )

    def _get(self, path, section, cache_key, sanitizer, force):
        now = float(self.clock())
        cached = self.cache.get(section, cache_key)
        if (
            cached is not None
            and not force
            and 0 <= now - cached["cached_at"] < CACHE_TTL_SECONDS
        ):
            return RoadmapResult(cached["payload"], from_cache=True)

        headers = {
            "Accept": "application/json",
            "User-Agent": "PokeyoyaKun/" + APP_VERSION,
        }
        if cached and cached["etag"]:
            headers["If-None-Match"] = cached["etag"]
        request = urllib.request.Request(
            PUBLIC_ROADMAP_ORIGIN + path, headers=headers, method="GET"
        )
        try:
            opener = self._opener or build_https_opener(
                PublicRoadmapHttpsRedirectHandler()
            )
            with opener.open(request, timeout=self.timeout_seconds) as response:
                status_code = getattr(response, "status", None)
                if status_code is None:
                    status_code = response.getcode()
                if status_code == 304:
                    return self._validated_cache(section, cache_key, cached, now)
                if status_code != 200:
                    raise PublicRoadmapError(
                        f"公開ロードマップAPIがHTTP {status_code}を返しました。"
                    )
                value = json.loads(response.read().decode("utf-8", errors="replace"))
                payload = sanitizer(value)
                etag = str(response.headers.get("ETag", ""))
                try:
                    self.cache.put(section, cache_key, payload, etag, now)
                except OSError:
                    # 読み取り専用環境でも、取得できた公開情報は画面へ返す。
                    pass
                return RoadmapResult(payload)
        except urllib.error.HTTPError as error:
            if error.code == 304:
                return self._validated_cache(section, cache_key, cached, now)
            message = f"公開ロードマップAPIがHTTP {error.code}を返しました。"
            return self._offline_or_raise(cached, message, error)
        except urllib.error.URLError as error:
            reason = getattr(error, "reason", error)
            return self._offline_or_raise(
                cached, f"公開ロードマップへ接続できません: {reason}", error
            )
        except TlsConfigurationError as error:
            return self._offline_or_raise(cached, str(error), error)
        except (TimeoutError, socket.timeout) as error:
            return self._offline_or_raise(
                cached, "接続がタイムアウトしました。", error
            )
        except (json.JSONDecodeError, OSError) as error:
            return self._offline_or_raise(
                cached, "公開ロードマップの応答を確認できませんでした。", error
            )

    def _validated_cache(self, section, cache_key, cached, now):
        if cached is None:
            raise PublicRoadmapError("304応答に対応するキャッシュがありません。")
        self.cache.put(
            section, cache_key, cached["payload"], cached["etag"], now
        )
        return RoadmapResult(cached["payload"], from_cache=True)

    @staticmethod
    def _offline_or_raise(cached, message, error):
        if cached is not None:
            return RoadmapResult(cached["payload"], from_cache=True, offline=True)
        raise PublicRoadmapError(message) from error
