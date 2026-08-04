import json
import re
import shutil
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any

from core.plugin_manager import PluginManager
from core.application_site import normalize_application_site
from core.json_file_state import (
    CORRUPT,
    PRODUCT_LIST_FIELDS,
    JsonFileResult,
    ensure_json_writable,
    inspect_json_file,
    restore_json_backup,
)
from core.retail_price_policy import RetailPricePolicy
from core.runtime_paths import app_root
from core.tcg_categories import display_name, normalize_key, normalize_record


class ProductStore:
    """商品データ、プラグイン更新、予約状態を管理する。"""

    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root is not None else app_root()
        self.products_path = self.root / "data" / "products.json"
        self.user_state_path = self.root / "config" / "user_state.json"
        self.plugin_manager = PluginManager()
        self.last_excluded_retail_offers: list[dict[str, str]] = []
        self.last_excluded_products: list[dict[str, str]] = []
        self.last_load_diagnostics: dict[str, Any] = {}
        self.last_merge_diagnostics: dict[str, Any] = {}
        self.last_product_file_result: JsonFileResult | None = None

    def load_products(self) -> list[dict[str, Any]]:
        result = self.inspect_product_file()
        self.last_product_file_result = result
        if result.state == CORRUPT:
            return []
        raw_products = result.data or []
        products = [normalize_record(item)[0] for item in raw_products]
        from core.activity_timeline import ActivityTimeline
        from core.product_master import ProductMasterManager

        master = ProductMasterManager(self.root)
        products = master.synchronize(products)
        timeline = ActivityTimeline(self.root)
        for record in master.last_new_records:
            timeline.add(
                "新商品",
                f'{record.get("canonical_name", "商品")}追加',
                product_id=str(record.get("product_id", "")),
                occurred_at=str(record.get("created_at", "")),
            )
        from core.store_history import StoreHistoryManager

        store_history = StoreHistoryManager(self.root)
        for product in products:
            product_id = str(product.get("product_id", product.get("id", "")))
            for site in product.get("sites", []):
                occurred = str(site.get("created_at") or site.get("detected_at") or site.get("candidate_added_at") or "")
                if not occurred:
                    continue
                status = str(site.get("status", ""))
                action = "抽選追加" if "抽選" in status else "予約追加" if "予約" in status else "商品追加"
                store_id = str(site.get("site_key", site.get("id", "")))
                detail = str(product.get("canonical_name", product.get("name", "商品")))
                store_history.record(store_id, action, detail, occurred_at=occurred)
                timeline.add(action, f'{site.get("name", "店舗")} {action}', product_id=product_id, store_id=store_id, occurred_at=occurred)
        from core.product_image_cache import ProductImageCache

        ProductImageCache(self.root).cleanup(
            active_product_ids={
                str(product.get("product_id", product.get("id", "")))
                for product in products
            }
        )
        visible = self._apply_user_state_and_archive(products)
        per_tcg = Counter(
            normalize_key(item.get("tcg_key"), item.get("tcg"))[0]
            for item in visible
        )
        self.last_load_diagnostics = {
            "storage_type": "json",
            "storage_path": str(self.products_path),
            "raw_count": len(raw_products),
            "normalized_count": len(products),
            "visible_count": len(visible),
            "per_tcg": dict(per_tcg),
            "excluded_products": list(self.last_excluded_products),
            "excluded_retail_offers": list(self.last_excluded_retail_offers),
        }
        return visible

    def update_from_plugins(
        self,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        products, messages = (
            self.plugin_manager.fetch_enabled_products()
        )
        self._save_product_file(products)
        return (
            self.load_products(),
            messages,
        )

    def merge_discovered_products(
        self,
        discovered: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], int]:
        products = self._load_product_file()
        added = 0
        updated = 0
        unchanged = 0
        ambiguous = 0
        from core.product_master import ProductMasterManager

        master = ProductMasterManager(self.root)
        master.last_conflicts = []

        for incoming in discovered:
            product_id = str(incoming.get("product_id") or incoming.get("id") or "")
            id_matches = [
                index
                for index, item in enumerate(products)
                if product_id
                and product_id
                == str(item.get("product_id") or item.get("id") or "")
            ]
            if len(id_matches) == 1:
                match_index, match_method = id_matches[0], "product_id"
            elif len(id_matches) > 1:
                match_index, match_method = None, "ambiguous_product_id"
            else:
                match_index, match_method = master.find_match(products, incoming)

            if match_index is not None:
                merged, changes = master.reconcile_product(
                    products[match_index], incoming
                )
                products[match_index] = merged
                if changes:
                    updated += 1
                else:
                    unchanged += 1
                continue

            if match_method.startswith("ambiguous_"):
                ambiguous += 1
            products.append(dict(incoming))
            added += 1

        if added or updated:
            products.sort(
                key=lambda item: (
                    str(
                        item.get(
                            "release_date",
                            "9999-99-99",
                        )
                    ),
                    str(item.get("name", "")),
                )
            )
            self._save_product_file(products)

        self.last_merge_diagnostics = {
            "discovered": len(discovered),
            "added": added,
            "updated": updated,
            "unchanged": unchanged,
            "ambiguous": ambiguous,
            "release_date_conflicts": list(master.last_conflicts),
        }
        if updated or master.last_conflicts:
            from core.log_manager import LogManager

            logger = LogManager(self.root)
            if updated:
                logger.write(
                    f"商品情報更新: 発見={len(discovered)} 更新={updated} "
                    f"追加={added} 変更なし={unchanged}"
                )
            master.log_conflicts()

        return (
            self.load_products(),
            added,
        )

    def save_reserved_state(
        self,
        product_id: str,
        reserved: bool,
    ) -> None:
        state = self._load_user_state()
        reserved_ids = set(
            state.get("reserved_product_ids", [])
        )

        if reserved:
            reserved_ids.add(product_id)
        else:
            reserved_ids.discard(product_id)

        state["reserved_product_ids"] = sorted(
            reserved_ids
        )
        self._save_user_state(state)

    def save_site_application_state(
        self,
        product_id: str,
        site_key: str,
        site_url: str,
        applied: bool,
        tcg_key: str = "other",
        tcg: str = "",
    ) -> None:
        state = self._load_user_state()
        applications = state.setdefault(
            "site_applications",
            {},
        )
        key = self._site_state_key(
            product_id,
            site_key,
            site_url,
        )
        item = dict(applications.get(key, {}))
        item["applied"] = bool(applied)
        normalized_key = normalize_key(tcg_key, tcg)[0]
        item["tcg_key"] = normalized_key
        item["tcg"] = display_name(normalized_key)
        item["applied_at"] = (
            datetime.now().isoformat(timespec="seconds")
            if applied
            else ""
        )
        if not applied:
            item["result_status"] = "未確認"
        item["updated_at"] = datetime.now().isoformat(
            timespec="seconds"
        )
        applications[key] = item
        self._save_user_state(state)

    def save_site_result(
        self,
        product_id: str,
        site_key: str,
        site_url: str,
        result_status: str,
    ) -> None:
        state = self._load_user_state()
        applications = state.setdefault(
            "site_applications",
            {},
        )
        key = self._site_state_key(
            product_id,
            site_key,
            site_url,
        )
        item = dict(applications.get(key, {}))
        item["result_status"] = result_status
        item["result_checked_at"] = (
            datetime.now().isoformat(timespec="seconds")
            if result_status != "未確認"
            else ""
        )
        item["updated_at"] = datetime.now().isoformat(
            timespec="seconds"
        )
        applications[key] = item
        self._save_user_state(state)

    def get_due_result_sites(
        self,
    ) -> list[dict[str, Any]]:
        return [
            site
            for product in self.load_products()
            for site in product.get("sites", [])
            if site.get("application_state")
            == "抽選結果確認"
        ]


    def reset_reserved_state(self) -> None:
        state = self._load_user_state()
        state["reserved_product_ids"] = []
        self._save_user_state(state)

    def exclude_auto_monitored_product(self, product_id: str) -> bool:
        products = self._load_product_file()
        target = next(
            (item for item in products if str(item.get("id", "")) == product_id),
            None,
        )
        if not target or not bool(target.get("auto_monitored")):
            return False
        from core.auto_monitor_manager import AutoMonitorManager

        state = self._load_user_state()
        excluded = set(state.get("auto_monitor_excluded_keys", []))
        excluded.add(AutoMonitorManager.product_key(target))
        state["auto_monitor_excluded_keys"] = sorted(excluded)
        self._save_user_state(state)
        self._save_product_file(
            [item for item in products if str(item.get("id", "")) != product_id]
        )
        return True

    def _load_product_file(
        self,
    ) -> list[dict[str, Any]]:
        result = self.inspect_product_file()
        self.last_product_file_result = result
        return result.data or []

    def inspect_product_file(self) -> JsonFileResult:
        return inspect_json_file(
            self.products_path,
            list,
            nullable_list_fields=PRODUCT_LIST_FIELDS,
        )

    def restore_products_backup(self) -> bool:
        return restore_json_backup(
            self.products_path,
            list,
            nullable_list_fields=PRODUCT_LIST_FIELDS,
        )

    def _save_product_file(
        self,
        products: list[dict[str, Any]],
    ) -> None:
        ensure_json_writable(
            self.products_path,
            list,
            nullable_list_fields=PRODUCT_LIST_FIELDS,
        )
        self.products_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        backup = self.products_path.with_suffix(".json.bak")
        if self.products_path.exists():
            shutil.copy2(self.products_path, backup)
        temporary = self.products_path.with_suffix(".json.tmp")
        with temporary.open(
            "w",
            encoding="utf-8",
        ) as file:
            json.dump(
                products,
                file,
                ensure_ascii=False,
                indent=2,
            )
        temporary.replace(self.products_path)

    def _load_user_state(
        self,
    ) -> dict[str, Any]:
        if not self.user_state_path.exists():
            return {
                "reserved_product_ids": [],
                "site_applications": {},
                "auto_monitor_excluded_keys": [],
            }

        try:
            with self.user_state_path.open(
                "r",
                encoding="utf-8",
            ) as file:
                data = json.load(file)
            return data if isinstance(data, dict) else {
                "reserved_product_ids": [],
                "site_applications": {},
                "auto_monitor_excluded_keys": [],
            }
        except (
            json.JSONDecodeError,
            OSError,
        ):
            return {
                "reserved_product_ids": [],
                "site_applications": {},
                "auto_monitor_excluded_keys": [],
            }

    def _save_user_state(
        self,
        state: dict[str, Any],
    ) -> None:
        self.user_state_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        backup = self.user_state_path.with_suffix(".json.bak")
        if self.user_state_path.exists():
            shutil.copy2(self.user_state_path, backup)
        temporary = self.user_state_path.with_suffix(".json.tmp")
        with temporary.open(
            "w",
            encoding="utf-8",
        ) as file:
            json.dump(
                state,
                file,
                ensure_ascii=False,
                indent=2,
            )
        temporary.replace(self.user_state_path)

    def _apply_user_state_and_archive(
        self,
        products: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        self.last_excluded_products = []
        self.last_excluded_retail_offers = []
        state = self._load_user_state()
        reserved_ids = set(
            state.get("reserved_product_ids", [])
        )
        applications = state.get(
            "site_applications",
            {},
        )

        visible_products = []
        today = date.today()

        for product in products:
            if product.get("source_type") == "retail_search":
                product["sites"] = self._filter_retail_sites(product)
                if not product["sites"]:
                    self.last_excluded_products.append({
                        "product": str(product.get("name", "")),
                        "reason": "retail_offer_rejected",
                    })
                    continue
            product["reserved"] = (
                product.get("id") in reserved_ids
            )

            product["sites"] = [
                normalize_application_site(site, product=product)
                for site in product.get("sites", [])
                if isinstance(site, dict)
            ]

            for site in product.get("sites", []):
                key = self._site_state_key(
                    str(product.get("id", "")),
                    str(site.get("site_key", "")),
                    str(site.get("url", "")),
                )
                saved = dict(applications.get(key, {}))
                applied = bool(saved.get("applied", site.get("applied", False)))
                result_status = str(
                    saved.get("result_status", site.get("result_status", "未確認"))
                )
                site["applied"] = applied
                site["result_status"] = result_status
                product_key = normalize_key(
                    product.get("tcg_key"), product.get("tcg")
                )[0]
                saved_key = normalize_key(
                    saved.get("tcg_key"), saved.get("tcg")
                )[0] if (saved.get("tcg_key") or saved.get("tcg")) else product_key
                site["tcg_key"] = saved_key
                site["tcg"] = display_name(saved_key)
                site["applied_at"] = str(saved.get("applied_at", site.get("applied_at", "")))
                site["result_checked_at"] = str(
                    saved.get("result_checked_at", site.get("result_checked_at", ""))
                )
                for reference_key in (
                    "receipt_number", "reception_number", "order_number"
                ):
                    if saved.get(reference_key):
                        site[reference_key] = str(saved[reference_key])
                site["application_state"] = self._application_state(
                    site,
                    applied,
                    result_status,
                )

            try:
                release_date = datetime.strptime(
                    str(product["release_date"]),
                    "%Y-%m-%d",
                ).date()

                if (today - release_date).days > 183:
                    self.last_excluded_products.append({
                        "product": str(product.get("name", "")),
                        "reason": "released_more_than_183_days_ago",
                    })
                    continue

            except (
                KeyError,
                TypeError,
                ValueError,
            ):
                pass

            visible_products.append(product)

        return visible_products

    def _filter_retail_sites(self, product: dict[str, Any]) -> list[dict[str, Any]]:
        verified_site_keys = {
            "amazon_jp", "yodobashi_lottery", "yodobashi_retail", "geo",
            "seven_net", "rakuten_books", "lawson_loppi", "premium_bandai",
            "biccamera", "joshin", "edion", "toysrus", "sanyodo",
            "pokemon_center_online",
        }
        output = []
        for raw in product.get("sites", []):
            if not isinstance(raw, dict):
                continue
            site = dict(raw)
            site.setdefault(
                "retailer_verified", site.get("site_key") in verified_site_keys
            )
            decision = RetailPricePolicy.evaluate(product, site)
            if not decision["accepted"]:
                self.last_excluded_retail_offers.append({
                    "product": str(product.get("name", "")),
                    "store": str(site.get("name", "")),
                    "reason": str(decision["exclusion_reason"]),
                })
                continue
            site.update(decision)
            output.append(site)
        return output

    @staticmethod
    def _site_state_key(
        product_id: str,
        site_key: str,
        site_url: str,
    ) -> str:
        return f"{product_id}|{site_key}|{site_url}"

    @classmethod
    def _application_state(
        cls,
        site: dict[str, Any],
        applied: bool,
        result_status: str,
    ) -> str:
        if result_status == "当選":
            return "当選"
        if result_status == "落選":
            return "落選"
        if result_status in {"予約完了", "注文受付", "キャンセル", "その他"}:
            return result_status
        if not applied:
            return "未応募"

        if cls._result_date_is_due(
            str(site.get("result_date", ""))
        ):
            return "抽選結果確認"

        return "抽選受付完了"

    @staticmethod
    def _result_date_is_due(
        value: str,
    ) -> bool:
        if not value.strip():
            return False

        match = re.search(
            r"(?:(\d{4})[./年])?"
            r"\s*(\d{1,2})[./月]"
            r"\s*(\d{1,2})日?",
            value,
        )
        if not match:
            return False

        today = date.today()
        try:
            year = int(match.group(1) or today.year)
            target = date(
                year,
                int(match.group(2)),
                int(match.group(3)),
            )
        except ValueError:
            return False

        return today >= target


    @staticmethod
    def _normalize_name(name: str) -> str:
        return re.sub(
            r"[\s「」『』・･_\-]",
            "",
            name,
        ).lower()
