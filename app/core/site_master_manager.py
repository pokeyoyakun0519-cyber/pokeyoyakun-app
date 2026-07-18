from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from core.runtime_paths import app_root
from core.tcg_categories import normalize_keys


LEGACY_SITE_ID_ALIASES = {
    "pokemon_center": "pokemon_center_online",
    "amazon": "amazon_jp",
    "rakuten": "rakuten_books",
    "yodobashi": "yodobashi_lottery",
}


def canonical_site_id(value: object) -> str:
    clean = str(value or "").strip().casefold()
    return LEGACY_SITE_ID_ALIASES.get(clean, clean)


DEFAULT_SITES = [
    {
        "id": "pokemon_center_online",
        "name": "ポケモンセンターオンライン",
        "enabled": True,
        "active": True,
        "site_url": "https://www.pokemoncenter-online.com/",
        "tcg_keys": ["pokemon"],
        "sales_type": "抽選・通常販売",
        "application_method": "Web",
        "purchase_history_required": False,
        "membership_required": True,
        "monitoring_supported": True,
        "notes": "販売方式は商品ごとに異なります。",
    },
    {
        "id": "amazon_jp",
        "name": "Amazon",
        "enabled": True,
        "active": True,
        "site_url": "https://www.amazon.co.jp/",
        "tcg_keys": ["pokemon", "onepiece", "yugioh", "gundam", "other"],
        "sales_type": "通常販売・招待販売",
        "application_method": "Web",
        "purchase_history_required": False,
        "membership_required": True,
        "monitoring_supported": True,
        "notes": "招待販売の場合があります。",
    },
    {
        "id": "rakuten_books",
        "name": "楽天ブックス",
        "enabled": True,
        "active": True,
        "site_url": "https://books.rakuten.co.jp/",
        "tcg_keys": ["pokemon", "onepiece", "yugioh", "gundam", "other"],
        "sales_type": "通常販売",
        "application_method": "Web",
        "purchase_history_required": False,
        "membership_required": True,
        "monitoring_supported": True,
        "notes": "",
    },
    {
        "id": "yodobashi_lottery",
        "name": "ヨドバシ",
        "enabled": True,
        "active": True,
        "site_url": "https://www.yodobashi.com/",
        "tcg_keys": ["pokemon", "onepiece", "yugioh", "gundam", "other"],
        "sales_type": "抽選・通常販売",
        "application_method": "Web",
        "purchase_history_required": True,
        "membership_required": True,
        "monitoring_supported": True,
        "notes": "購入履歴や会員条件が設定される場合があります。",
    },
    {
        "id": "biccamera",
        "name": "ビックカメラ",
        "enabled": True,
        "active": True,
        "site_url": "https://www.biccamera.com/",
        "tcg_keys": ["pokemon", "onepiece", "yugioh", "gundam", "other"],
        "sales_type": "抽選・通常販売",
        "application_method": "Web",
        "purchase_history_required": True,
        "membership_required": True,
        "monitoring_supported": True,
        "notes": "抽選条件は時期によって異なります。",
    },
    {
        "id": "amiami",
        "name": "あみあみ",
        "enabled": False,
        "active": True,
        "site_url": "https://www.amiami.jp/",
        "tcg_keys": ["pokemon", "onepiece", "yugioh", "gundam", "other"],
        "sales_type": "通常販売",
        "application_method": "Web",
        "purchase_history_required": False,
        "membership_required": False,
        "monitoring_supported": True,
        "notes": "",
    },
]


class SiteMasterManager:
    """販売サイトを共通IDで管理し、既存設定と履歴を保持する。"""

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
        sites = self._merge_defaults(loaded)
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
                sites[index] = self._normalize_site({**site, **updated, "id": canonical})
                break
        self.save_sites(sites)

    def delete_site(self, site_id: str) -> None:
        canonical = canonical_site_id(site_id)
        sites = self.load_sites()
        for site in sites:
            if site.get("id") == canonical:
                site["active"] = False
                site["enabled"] = False
                site["notes"] = str(site.get("notes", "") or "利用停止")
                break
        self.save_sites(sites)

    def _merge_defaults(self, loaded: list[dict[str, Any]]) -> list[dict[str, Any]]:
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
            else:
                for key, value in default.items():
                    merged[site_id].setdefault(key, json.loads(json.dumps(value)))
        return [merged[site_id] for site_id in order]

    @staticmethod
    def _normalize_site(raw: dict[str, Any]) -> dict[str, Any]:
        site = dict(raw)
        site_id = canonical_site_id(site.get("id"))
        raw_tcg_keys = site.get("tcg_keys", site.get("tcg", ["other"]))
        tcg_keys, _unknown = normalize_keys(raw_tcg_keys) if raw_tcg_keys else ([], [])
        url = str(site.get("site_url", site.get("url", ""))).strip()
        if url:
            try:
                if urlsplit(url).scheme != "https":
                    url = ""
            except ValueError:
                url = ""
        return {
            **site,
            "id": site_id,
            "name": str(site.get("name", site_id or "名称未設定")).strip() or "名称未設定",
            "enabled": bool(site.get("enabled", False)),
            "active": bool(site.get("active", site.get("enabled", True))),
            "site_url": url,
            "tcg_keys": tcg_keys,
            "sales_type": str(site.get("sales_type", "その他")),
            "application_method": str(site.get("application_method", "Web")),
            "purchase_history_required": bool(site.get("purchase_history_required", False)),
            "membership_required": bool(site.get("membership_required", False)),
            "monitoring_supported": bool(site.get("monitoring_supported", True)),
            "notes": str(site.get("notes", "")),
        }
