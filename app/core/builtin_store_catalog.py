from __future__ import annotations

import json
import re
import unicodedata
from copy import deepcopy
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from core.runtime_paths import bundled_root, is_frozen


SCHEMA_VERSION = 1
CHANNELS = {"physical", "online", "chain", "manufacturer"}
CHAIN_SUPPORT_VALUES = {"full", "partial", "unknown"}
TCG_KEYS = (
    "pokemon", "onepiece", "yugioh", "gundam",
    "union_arena", "dragon_ball_fusion_world", "duelmasters", "weiss", "mtg", "other",
)
TCG_SUPPORT_VALUES = {"supported", "partial", "unsupported", "unknown"}
DISCOVERY_METHODS = {
    "product_search", "category", "reservation", "lottery", "official_news",
    "official_social", "official_app", "store_only", "unsupported",
}
STORE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_]{1,63}$")


class CatalogValidationError(ValueError):
    pass


def catalog_path() -> Path:
    if is_frozen():
        return bundled_root() / "resources" / "builtin_stores.json"
    return Path(__file__).resolve().parents[1] / "resources" / "builtin_stores.json"


def normalize_store_name(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.sub(r"[\s\-_/・･.()（）\[\]【】]+", "", text)


def load_builtin_store_catalog(path: Path | None = None) -> dict[str, Any]:
    source = Path(path) if path is not None else catalog_path()
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CatalogValidationError(f"標準店舗データを読み込めません: {error}") from error
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
        raise CatalogValidationError("標準店舗データのschema_versionが未対応です。")
    defaults = payload.get("defaults", {})
    raw_stores = payload.get("stores", [])
    if not isinstance(defaults, dict) or not isinstance(raw_stores, list):
        raise CatalogValidationError("標準店舗データの構造が正しくありません。")
    stores: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_stores):
        if not isinstance(raw, dict):
            raise CatalogValidationError(f"stores[{index}]がオブジェクトではありません。")
        merged = deepcopy(defaults)
        merged.update(deepcopy(raw))
        store = _validate_store(merged, index)
        store_id = store["canonical_store_id"]
        if store_id in seen:
            raise CatalogValidationError(f"canonical_store_idが重複しています: {store_id}")
        seen.add(store_id)
        stores.append(store)
    return {
        "schema_version": SCHEMA_VERSION,
        "catalog_version": str(payload.get("catalog_version", "")),
        "integrity_mode": str(payload.get("integrity_mode", "bundled_application_resource")),
        "stores": stores,
    }


def build_alias_index(stores: list[dict[str, Any]]) -> dict[str, str]:
    index: dict[str, str] = {}
    for store in stores:
        store_id = str(store["canonical_store_id"])
        values = [
            store_id,
            store.get("display_name", ""),
            *store.get("aliases", []),
            *store.get("legacy_ids", []),
        ]
        for value in values:
            normalized = normalize_store_name(value)
            if normalized:
                index.setdefault(normalized, store_id)
    return index


def match_builtin_store(
    stores: list[dict[str, Any]],
    *,
    name: object = "",
    url: object = "",
    official_social_url: object = "",
    store_code: object = "",
    channel: object = "",
) -> dict[str, Any] | None:
    normalized = normalize_store_name(name)
    aliases = build_alias_index(stores)
    store_id = aliases.get(normalized)
    if store_id:
        matched = next(store for store in stores if store["canonical_store_id"] == store_id)
        group = str(matched["store_group_id"])
        channel_value = str(channel or "")
        if channel_value:
            channel_match = next(
                (store for store in stores if store["store_group_id"] == group and store["channel"] == channel_value),
                None,
            )
            if channel_match:
                return channel_match
        return matched
    social = str(official_social_url or "").strip().rstrip("/").casefold()
    if social:
        social_match = next(
            (
                store for store in stores
                if str(store.get("official_social_url", "")).strip().rstrip("/").casefold() == social
            ),
            None,
        )
        if social_match:
            return social_match
    code = str(store_code or "").strip().casefold()
    if code:
        code_match = next(
            (store for store in stores if code in {str(value).strip().casefold() for value in store.get("store_codes", [])}),
            None,
        )
        if code_match:
            return code_match
    host = (urlparse(str(url or "")).hostname or "").casefold()
    if host:
        matches = [
            store
            for store in stores
            if any(_host_matches(host, domain) for domain in store.get("official_domains", []))
        ]
        if len(matches) == 1:
            return matches[0]
        if matches and len({store["store_group_id"] for store in matches}) == 1:
            # 実店舗／オンラインの別チャンネルでも同一事業者なら既存扱い。
            return matches[0]
    return None


def _validate_store(store: dict[str, Any], index: int) -> dict[str, Any]:
    store_id = str(store.get("canonical_store_id", "")).strip().casefold()
    group_id = str(store.get("store_group_id", "")).strip().casefold()
    if not STORE_ID_PATTERN.fullmatch(store_id):
        raise CatalogValidationError(f"stores[{index}]のcanonical_store_idが不正です。")
    if not STORE_ID_PATTERN.fullmatch(group_id):
        raise CatalogValidationError(f"stores[{index}]のstore_group_idが不正です。")
    channel = str(store.get("channel", ""))
    chain_support = str(store.get("chain_support", "unknown"))
    discovery_method = str(store.get("discovery_method", "unsupported"))
    if channel not in CHANNELS or chain_support not in CHAIN_SUPPORT_VALUES:
        raise CatalogValidationError(f"stores[{index}]の区分値が不正です。")
    if discovery_method not in DISCOVERY_METHODS:
        raise CatalogValidationError(f"stores[{index}]のdiscovery_methodが不正です。")
    domains = _normalize_domains(store.get("official_domains", []), index)
    urls = (
        "official_url", "product_search_template", "reservation_url", "lottery_url",
        "official_news_url", "evidence_url",
    )
    for key in urls:
        value = str(store.get(key, "")).strip()
        if not value:
            store[key] = ""
            continue
        test_value = value.replace("{query}", "test")
        parsed = urlparse(test_value)
        host = (parsed.hostname or "").casefold()
        if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port not in (None, 443):
            raise CatalogValidationError(f"stores[{index}].{key}は安全なHTTPS URLではありません。")
        if not any(_host_matches(host, domain) for domain in domains):
            raise CatalogValidationError(f"stores[{index}].{key}が公式ドメイン外です。")
        store[key] = value
    social = str(store.get("official_social_url", "")).strip()
    if social:
        parsed = urlparse(social)
        if parsed.scheme != "https" or (parsed.hostname or "").casefold() not in {"x.com", "www.instagram.com"}:
            raise CatalogValidationError(f"stores[{index}].official_social_urlが不正です。")
    tcg_support = dict(store.get("tcg_support", {}))
    supported_keys = []
    for key in TCG_KEYS:
        value = str(tcg_support.get(key, "unknown"))
        if value not in TCG_SUPPORT_VALUES:
            raise CatalogValidationError(f"stores[{index}].tcg_support.{key}が不正です。")
        tcg_support[key] = value
        if value in {"supported", "partial"}:
            supported_keys.append(key)
    if bool(store.get("default_enabled", False)):
        raise CatalogValidationError(f"stores[{index}]の標準監視は安全のためOFFである必要があります。")
    monitoring_supported = bool(store.get("monitoring_supported", False))
    if monitoring_supported and not any(str(store.get(key, "")) for key in urls[1:5]):
        raise CatalogValidationError(f"stores[{index}]は監視URLなしで監視可能になっています。")
    return {
        **store,
        "canonical_store_id": store_id,
        "store_group_id": group_id,
        "display_name": str(store.get("display_name", "")).strip(),
        "aliases": sorted({str(value).strip() for value in store.get("aliases", []) if str(value).strip()}),
        "legacy_ids": sorted({str(value).strip().casefold() for value in store.get("legacy_ids", []) if str(value).strip()}),
        "official_domains": domains,
        "channel": channel,
        "chain_support": chain_support,
        "tcg_support": tcg_support,
        "supported_tcg_keys": supported_keys,
        "confirmed_locations": list(store.get("confirmed_locations", [])),
        "store_codes": list(store.get("store_codes", [])),
        "monitoring_supported": monitoring_supported,
        "default_enabled": False,
        "active": bool(store.get("active", True)),
    }


def _normalize_domains(value: object, index: int) -> list[str]:
    if not isinstance(value, list):
        raise CatalogValidationError(f"stores[{index}].official_domainsが配列ではありません。")
    domains = []
    for raw in value:
        domain = str(raw).strip().casefold().strip(".")
        if not domain or "/" in domain or ":" in domain or domain == "localhost":
            raise CatalogValidationError(f"stores[{index}]の公式ドメインが不正です。")
        domains.append(domain)
    return sorted(set(domains))


def _host_matches(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)
