from __future__ import annotations

import json
import threading
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any

from core.favorites_manager import FavoritesManager
from core.notification_store import NotificationStore
from core.product_store import ProductStore
from core.runtime_paths import app_root
from core.site_master_manager import SiteMasterManager
from core.source_manager import SourceManager
from core.tcg_categories import display_name


GROUP_ORDER = ("products", "applications", "stores", "notifications", "favorites", "sources")
GROUP_LABELS = {
    "products": "商品",
    "applications": "応募情報",
    "stores": "店舗・サイト",
    "notifications": "通知",
    "favorites": "お気に入り",
    "sources": "公式情報ソース",
}
SIMPLE_GROUPS = frozenset(GROUP_ORDER[:-1])


def normalize_search_text(value: object) -> str:
    return " ".join(
        unicodedata.normalize("NFKC", str(value or "")).casefold().split()
    )


class GlobalSearchService:
    """ローカルデータを横断し、画面遷移可能な共通結果へ変換する。"""

    def __init__(self, root: Path | None = None, *, limit_per_group: int = 20):
        self.root = Path(root) if root is not None else app_root()
        self.limit_per_group = max(1, int(limit_per_group))
        self._load_lock = threading.Lock()

    def search(
        self,
        query: str,
        *,
        mode: str = "simple",
        datasets: dict[str, Any] | None = None,
    ) -> dict[str, list[dict[str, str]]]:
        terms = [term for term in normalize_search_text(query).split(" ") if term]
        if not terms:
            return {}
        if datasets is None:
            with self._load_lock:
                data = self._load_datasets()
        else:
            data = datasets
        groups: dict[str, list[dict[str, str]]] = defaultdict(list)
        products = [item for item in data.get("products", []) if isinstance(item, dict)]
        stores = [item for item in data.get("stores", []) if isinstance(item, dict)]
        favorites = data.get("favorites", {}) if isinstance(data.get("favorites", {}), dict) else {}
        favorite_products = {str(value) for value in favorites.get("products", [])}
        favorite_stores = {str(value) for value in favorites.get("stores", [])}

        for product in products:
            product_id = str(product.get("product_id", product.get("id", "")))
            product_name = str(product.get("canonical_name") or product.get("name") or "商品名未設定")
            product_text = self._text(product_name, product.get("aliases"), self._tcg_terms(product.get("tcg_key")), product.get("tcg"), product.get("category"), product.get("product_kind"), product.get("keywords"))
            if self._matches(terms, product_text):
                groups["products"].append(self._result(
                    "products", product_name,
                    self._join(product.get("tcg"), product.get("release_date"), product.get("category")),
                    "product", product_id,
                ))
            if product_id in favorite_products and self._matches(terms, self._text("お気に入り", product_text)):
                groups["favorites"].append(self._result(
                    "favorites", f"★ {product_name}", "お気に入り商品", "product", product_id,
                ))
            for site in product.get("sites", []):
                if not isinstance(site, dict):
                    continue
                site_name = str(site.get("name") or site.get("site_name") or "店舗未設定")
                application_text = self._text(
                    product_text, site_name, site.get("status"), site.get("application_state"),
                    site.get("application_method"), site.get("application_conditions"),
                    site.get("conditions"), site.get("category"), site.get("keywords"),
                )
                if self._matches(terms, application_text):
                    groups["applications"].append(self._result(
                        "applications", product_name,
                        self._join(site_name, site.get("status") or site.get("application_state"), site.get("application_method")),
                        "application", product_id,
                    ))

        for store in stores:
            store_id = str(store.get("id", store.get("site_key", "")))
            store_name = str(store.get("name") or "店舗名未設定")
            store_text = self._text(
                store_name, store.get("aliases"), store.get("tcg_keys"), store.get("sales_type"),
                store.get("application_method"), store.get("notes"), store.get("site_url"),
                self._tcg_terms(store.get("tcg_keys")),
            )
            if self._matches(terms, store_text):
                groups["stores"].append(self._result(
                    "stores", store_name,
                    self._join(store.get("sales_type"), store.get("application_method"), store.get("tcg_keys")),
                    "site_master", store_id,
                ))
            if store_id in favorite_stores and self._matches(terms, self._text("お気に入り", store_text)):
                groups["favorites"].append(self._result(
                    "favorites", f"★ {store_name}", "お気に入り店舗", "site_master", store_id,
                ))

        for item in data.get("notifications", []):
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "通知")
            if self._matches(terms, self._text(title, item.get("message"), item.get("category"), item.get("created_at"))):
                groups["notifications"].append(self._result(
                    "notifications", title,
                    self._join(item.get("category"), item.get("created_at")),
                    "notifications", "",
                ))

        if mode == "detailed":
            for source in data.get("sources", []):
                if not isinstance(source, dict):
                    continue
                name = str(source.get("name") or "公式情報ソース")
                detected_names = [
                    item.get("name", "") for item in source.get("detected_products", [])
                    if isinstance(item, dict)
                ]
                if self._matches(terms, self._text(
                    name, source.get("tcg"), self._tcg_terms(source.get("tcg_key")), source.get("last_title"),
                    source.get("last_status"), source.get("url"), detected_names,
                )):
                    groups["sources"].append(self._result(
                        "sources", name,
                        self._join(source.get("tcg"), source.get("last_status")),
                        "sources", str(source.get("id", "")),
                    ))

        allowed = GROUP_ORDER if mode == "detailed" else tuple(group for group in GROUP_ORDER if group in SIMPLE_GROUPS)
        return {
            group: groups[group][: self.limit_per_group]
            for group in allowed if groups.get(group)
        }

    def _load_datasets(self) -> dict[str, Any]:
        return {
            "products": ProductStore(self.root).load_products(),
            "stores": SiteMasterManager(self.root).load_sites(),
            "notifications": NotificationStore(self.root).load(),
            "favorites": FavoritesManager(self.root).load(),
            "sources": self._load_sources_read_only(),
        }

    def _load_sources_read_only(self) -> list[dict[str, Any]]:
        path = self.root / "config" / "sources.json"
        if not path.exists():
            return [dict(item) for item in SourceManager.DEFAULT_SOURCES]
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        return value if isinstance(value, list) else []

    @staticmethod
    def _matches(terms: list[str], text: str) -> bool:
        return all(term in text for term in terms)

    @staticmethod
    def _text(*values: object) -> str:
        flattened = []
        for value in values:
            if isinstance(value, (list, tuple, set)):
                flattened.extend(str(item) for item in value)
            elif isinstance(value, dict):
                flattened.extend(f"{key} {item}" for key, item in value.items())
            else:
                flattened.append(str(value or ""))
        return normalize_search_text(" ".join(flattened))

    @staticmethod
    def _join(*values: object) -> str:
        return " ｜ ".join(str(value) for value in values if value not in (None, "", [], {}))

    @staticmethod
    def _tcg_terms(values: object) -> list[str]:
        keys = values if isinstance(values, (list, tuple, set)) else [values]
        return [
            f"{key} {display_name(str(key))}"
            for key in keys if str(key or "").strip()
        ]

    @staticmethod
    def _result(group: str, title: str, detail: str, target: str, item_id: str) -> dict[str, str]:
        return {
            "group": group, "title": title, "detail": detail,
            "target": target, "item_id": item_id,
        }
