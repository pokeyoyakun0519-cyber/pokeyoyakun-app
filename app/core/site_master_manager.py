from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from core.builtin_store_catalog import (
    build_alias_index,
    load_builtin_store_catalog,
    normalize_store_name,
)
from core.retail_plugin_registry import BUILTIN_RETAIL_PLUGINS
from core.runtime_paths import app_root
from core.tcg_categories import normalize_keys


_CATALOG = load_builtin_store_catalog()
BUILTIN_STORE_RECORDS = _CATALOG["stores"]
_ALIAS_INDEX = build_alias_index(BUILTIN_STORE_RECORDS)

LEGACY_SITE_ID_ALIASES = {
    "pokemon_center": "pokemon_center_online",
    "amazon": "amazon_jp",
    "rakuten": "rakuten_books",
    "yodobashi": "yodobashi_online",
}
for _store in BUILTIN_STORE_RECORDS:
    for _legacy_id in _store.get("legacy_ids", []):
        LEGACY_SITE_ID_ALIASES[str(_legacy_id)] = str(
            _store["canonical_store_id"]
        )


def canonical_site_id(value: object) -> str:
    clean = str(value or "").strip().casefold()
    if clean in LEGACY_SITE_ID_ALIASES:
        return LEGACY_SITE_ID_ALIASES[clean]
    return _ALIAS_INDEX.get(normalize_store_name(clean), clean)


def _plugin_url(plugin: dict[str, Any]) -> str:
    return str(plugin.get("search_url") or plugin.get("index_url") or "")


def _builtin_site(plugin: dict[str, Any]) -> dict[str, Any]:
    site_id = canonical_site_id(plugin.get("id"))
    tcg_keys, _unknown = normalize_keys(plugin.get("tcg", ["other"]))
    url = _plugin_url(plugin)
    return {
        "id": site_id,
        "name": str(plugin.get("name", site_id)),
        "enabled": bool(plugin.get("enabled", True)) and not bool(plugin.get("security_disabled")),
        "active": not bool(plugin.get("security_disabled")),
        "site_url": url,
        "tcg_keys": tcg_keys,
        "sales_type": "抽選・予約・通常販売",
        "application_method": str(plugin.get("application_method", "Web")),
        "purchase_history_required": False,
        "membership_required": True,
        "notes": str(plugin.get("disabled_reason", "")),
        "built_in": True,
        "monitoring_supported": not bool(plugin.get("security_disabled")),
        "monitoring_default": False,
    }


def _catalog_site(record: dict[str, Any]) -> dict[str, Any]:
    method_labels = {
        "product_search": "公開商品検索",
        "category": "公開カテゴリ",
        "reservation": "公開予約ページ",
        "lottery": "公開抽選ページ",
        "official_news": "公式ニュース",
        "official_social": "公式SNS",
        "official_app": "公式アプリ",
        "store_only": "店頭",
        "unsupported": "監視不可",
    }
    return {
        "id": str(record["canonical_store_id"]),
        "canonical_store_id": str(record["canonical_store_id"]),
        "store_group_id": str(record["store_group_id"]),
        "name": str(record["display_name"]),
        "display_name": str(record["display_name"]),
        "aliases": list(record.get("aliases", [])),
        "official_domains": list(record.get("official_domains", [])),
        "official_url": str(record.get("official_url", "")),
        "enabled": False,
        "active": bool(record.get("active", True)),
        "site_url": str(
            record.get("product_search_template")
            or record.get("lottery_url")
            or record.get("reservation_url")
            or record.get("official_news_url")
            or record.get("official_url", "")
        ),
        "channel": str(record.get("channel", "chain")),
        "tcg_keys": list(record.get("supported_tcg_keys", [])),
        "tcg_support": dict(record.get("tcg_support", {})),
        "chain_support": str(record.get("chain_support", "unknown")),
        "confirmed_locations": list(record.get("confirmed_locations", [])),
        "last_confirmed_at": str(record.get("last_confirmed_at", "")),
        "evidence_url": str(record.get("evidence_url", "")),
        "evidence_type": str(record.get("evidence_type", "unconfirmed")),
        "discovery_method": str(record.get("discovery_method", "unsupported")),
        "product_search_template": str(record.get("product_search_template", "")),
        "reservation_url": str(record.get("reservation_url", "")),
        "lottery_url": str(record.get("lottery_url", "")),
        "official_news_url": str(record.get("official_news_url", "")),
        "official_social_url": str(record.get("official_social_url", "")),
        "requires_login": bool(record.get("requires_login", False)),
        "requires_app": bool(record.get("requires_app", False)),
        "monitoring_supported": bool(record.get("monitoring_supported", False)),
        "monitoring_reason": str(record.get("monitoring_reason", "")),
        "marketplace_policy": str(record.get("marketplace_policy", "none")),
        "sales_type": "抽選・予約・通常販売",
        "application_method": method_labels.get(
            str(record.get("discovery_method", "unsupported")),
            "監視不可",
        ),
        "purchase_history_required": False,
        "membership_required": bool(record.get("requires_login", False)),
        "notes": str(record.get("notes", "")),
        "built_in": True,
        "catalog_version": str(_CATALOG.get("catalog_version", "")),
        "monitoring_default": False,
        "new": True,
    }


DEFAULT_SITES = [_catalog_site(record) for record in BUILTIN_STORE_RECORDS]
_default_by_id = {str(site["id"]): site for site in DEFAULT_SITES}
for _plugin in BUILTIN_RETAIL_PLUGINS:
    _plugin_site = _builtin_site(_plugin)
    _plugin_id = str(_plugin_site["id"])
    if _plugin_id in _default_by_id:
        _default = _default_by_id[_plugin_id]
        if not _default.get("site_url"):
            _default["site_url"] = _plugin_site.get("site_url", "")
        _default["plugin_id"] = str(_plugin.get("id", ""))
        continue
    DEFAULT_SITES.append(_plugin_site)


class SiteMasterManager:
    """販売サイトの共通IDと有効状態を後方互換で管理する。"""

    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root is not None else app_root()
        self.path = self.root / "config" / "site_master.json"
        self.backup_path = self.path.with_suffix(".json.bak")

    def load_sites(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            sites = json.loads(json.dumps(DEFAULT_SITES))
            self.save_sites(sites)
            return sites
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            loaded = data if isinstance(data, list) else []
        except (OSError, json.JSONDecodeError):
            return json.loads(json.dumps(DEFAULT_SITES))

        sites = self._merge_builtins(loaded)
        if sites != loaded:
            self.save_sites(sites)
        return sites

    def save_sites(self, sites: list[dict[str, Any]]) -> None:
        normalized = [self._normalize_site(site) for site in sites if isinstance(site, dict)]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            shutil.copy2(self.path, self.backup_path)
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)

    def rollback(self) -> bool:
        if not self.backup_path.exists():
            return False
        shutil.copy2(self.backup_path, self.path)
        return True

    def add_site(self, site: dict[str, Any]) -> bool:
        candidate = self._normalize_site(site)
        sites = self.load_sites()
        if any(item.get("id") == candidate["id"] for item in sites):
            return False
        sites.append(candidate)
        self.save_sites(sites)
        return True

    def update_site(self, site_id: str, updated: dict[str, Any]) -> None:
        canonical = canonical_site_id(site_id)
        sites = self.load_sites()
        for index, site in enumerate(sites):
            if site.get("id") == canonical:
                merged = {**site, **updated, "id": canonical}
                sites[index] = self._normalize_site(merged)
                break
        self.save_sites(sites)

    def delete_site(self, site_id: str) -> None:
        """履歴と設定IDを維持するため物理削除せず利用停止にする。"""
        canonical = canonical_site_id(site_id)
        sites = self.load_sites()
        for site in sites:
            if site.get("id") == canonical:
                site["active"] = False
                site["enabled"] = False
                site["notes"] = str(site.get("notes", "") or "利用停止")
                break
        self.save_sites(sites)

    def _merge_builtins(self, loaded: list[dict[str, Any]]) -> list[dict[str, Any]]:
        merged: dict[str, dict[str, Any]] = {}
        order: list[str] = []
        for raw in loaded:
            site = self._normalize_site(raw)
            site_id = site["id"]
            if not site_id or site_id in merged:
                continue
            merged[site_id] = site
            order.append(site_id)
        for default in DEFAULT_SITES:
            site_id = str(default["id"])
            if site_id not in merged:
                merged[site_id] = json.loads(json.dumps(default))
                order.append(site_id)
                continue
            # 名称などユーザー編集項目は維持し、不足メタデータだけ補完する。
            for key, value in default.items():
                merged[site_id].setdefault(key, json.loads(json.dumps(value)))
        return [merged[site_id] for site_id in order]

    @staticmethod
    def _normalize_site(raw: dict[str, Any]) -> dict[str, Any]:
        site = dict(raw)
        site_id = canonical_site_id(site.get("id"))
        raw_tcg_keys = site.get("tcg_keys", site.get("tcg", ["other"]))
        # カタログで取扱未確認を空配列としている店舗は、誤って「その他対応」にしない。
        tcg_keys, _unknown = normalize_keys(raw_tcg_keys) if raw_tcg_keys else ([], [])
        url = str(site.get("site_url", site.get("url", ""))).strip()
        if url:
            try:
                parsed = urlsplit(url.format(query=""))
                if parsed.scheme != "https":
                    url = ""
            except (ValueError, KeyError):
                url = ""
        return {
            **site,
            "id": site_id,
            "canonical_store_id": site_id,
            "store_group_id": str(site.get("store_group_id", site_id)),
            "name": str(site.get("name", site_id or "名称未設定")).strip() or "名称未設定",
            "enabled": bool(site.get("enabled", False)),
            "active": bool(site.get("active", site.get("enabled", True))),
            "site_url": url,
            "tcg_keys": tcg_keys,
            "tcg_support": dict(site.get("tcg_support", {})),
            "chain_support": str(site.get("chain_support", "unknown")),
            "confirmed_locations": list(site.get("confirmed_locations", [])),
            "last_confirmed_at": str(site.get("last_confirmed_at", "")),
            "evidence_url": str(site.get("evidence_url", "")),
            "evidence_type": str(site.get("evidence_type", "unconfirmed")),
            "discovery_method": str(site.get("discovery_method", "unsupported")),
            "monitoring_supported": bool(site.get("monitoring_supported", False)),
            "monitoring_reason": str(site.get("monitoring_reason", "")),
            "channel": str(site.get("channel", "chain")),
            "sales_type": str(site.get("sales_type", "その他")),
            "application_method": str(site.get("application_method", "Web")),
            "purchase_history_required": bool(site.get("purchase_history_required", False)),
            "membership_required": bool(site.get("membership_required", False)),
            "notes": str(site.get("notes", "")),
            "built_in": bool(site.get("built_in", False)),
            "monitoring_default": bool(site.get("monitoring_default", False)),
            "new": bool(site.get("new", False)),
        }
