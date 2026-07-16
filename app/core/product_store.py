import json
import re
from datetime import date, datetime
from typing import Any

from core.plugin_manager import PluginManager
from core.runtime_paths import app_root
from core.tcg_categories import normalize_record


class ProductStore:
    """商品データ、プラグイン更新、予約状態を管理する。"""

    def __init__(self):
        root = app_root()
        self.products_path = root / "data" / "products.json"
        self.user_state_path = root / "config" / "user_state.json"
        self.plugin_manager = PluginManager()

    def load_products(self) -> list[dict[str, Any]]:
        products = [normalize_record(item)[0] for item in self._load_product_file()]
        return self._apply_user_state_and_archive(products)

    def update_from_plugins(
        self,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        products, messages = (
            self.plugin_manager.fetch_enabled_products()
        )
        self._save_product_file(products)
        return (
            self._apply_user_state_and_archive(products),
            messages,
        )

    def merge_discovered_products(
        self,
        discovered: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], int]:
        products = self._load_product_file()
        added = 0

        existing_ids = {
            str(product.get("id", ""))
            for product in products
        }
        existing_keys = {
            (
                self._normalize_name(
                    str(product.get("name", ""))
                ),
                str(product.get("release_date", "")),
            )
            for product in products
        }

        for product in discovered:
            product_id = str(product.get("id", ""))
            key = (
                self._normalize_name(
                    str(product.get("name", ""))
                ),
                str(product.get("release_date", "")),
            )

            if (
                product_id in existing_ids
                or key in existing_keys
            ):
                continue

            products.append(product)
            existing_ids.add(product_id)
            existing_keys.add(key)
            added += 1

        if added:
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

        return (
            self._apply_user_state_and_archive(products),
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
            if result_status in {"当選", "落選"}
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

    def _load_product_file(
        self,
    ) -> list[dict[str, Any]]:
        if not self.products_path.exists():
            return []

        try:
            with self.products_path.open(
                "r",
                encoding="utf-8",
            ) as file:
                data = json.load(file)
            return data if isinstance(data, list) else []
        except (
            json.JSONDecodeError,
            OSError,
        ):
            return []

    def _save_product_file(
        self,
        products: list[dict[str, Any]],
    ) -> None:
        self.products_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        with self.products_path.open(
            "w",
            encoding="utf-8",
        ) as file:
            json.dump(
                products,
                file,
                ensure_ascii=False,
                indent=2,
            )

    def _load_user_state(
        self,
    ) -> dict[str, Any]:
        if not self.user_state_path.exists():
            return {
                "reserved_product_ids": [],
                "site_applications": {},
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
            }
        except (
            json.JSONDecodeError,
            OSError,
        ):
            return {
                "reserved_product_ids": [],
                "site_applications": {},
            }

    def _save_user_state(
        self,
        state: dict[str, Any],
    ) -> None:
        self.user_state_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        with self.user_state_path.open(
            "w",
            encoding="utf-8",
        ) as file:
            json.dump(
                state,
                file,
                ensure_ascii=False,
                indent=2,
            )

    def _apply_user_state_and_archive(
        self,
        products: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
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
            product["reserved"] = (
                product.get("id") in reserved_ids
            )

            for site in product.get("sites", []):
                key = self._site_state_key(
                    str(product.get("id", "")),
                    str(site.get("site_key", "")),
                    str(site.get("url", "")),
                )
                saved = dict(applications.get(key, {}))
                applied = bool(saved.get("applied", False))
                result_status = str(
                    saved.get("result_status", "未確認")
                )
                site["applied"] = applied
                site["result_status"] = result_status
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
                    continue

            except (
                KeyError,
                TypeError,
                ValueError,
            ):
                pass

            visible_products.append(product)

        return visible_products

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
