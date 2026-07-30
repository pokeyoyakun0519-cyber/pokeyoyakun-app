from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.runtime_paths import app_root
from core.application_site import normalize_application_site
from core.tcg_categories import display_name, normalize_key


class ProductMasterManager:
    """表記揺れを吸収し、商品を安定したproduct_idへ統合する。"""

    _BOX_SUFFIX = re.compile(
        r"(?:\s|　)*(?:BOX|ＢＯＸ|ボックス|1BOX|１ＢＯＸ)(?:\s|　)*$",
        re.IGNORECASE,
    )
    _TRAILING_PRICE = re.compile(
        r"(?:[\s　/／・:：\-]*(?:税込|税抜)?\s*[￥¥]?\s*"
        r"(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?\s*円"
        r"(?:\s*\([^)]*\))?)\s*$",
        re.IGNORECASE,
    )
    _TRAILING_RELEASE_DATE = re.compile(
        r"(?:[\s　/／・:：\-]*(?:発売日|発売予定|販売開始)\s*[:：]?\s*)?"
        r"(?:20\d{2}[年/\-.]\s*\d{1,2}[月/\-.]\s*\d{1,2}日?"
        r"(?:\s*\([^)]*\))?)\s*$",
        re.IGNORECASE,
    )
    _IDENTIFIER_FIELDS = (
        "product_code",
        "jan_code",
        "jan",
        "official_product_id",
        "official_id",
    )
    _BRAND_FIELDS = ("manufacturer", "maker", "brand")
    _UNKNOWN_KINDS = {"", "その他", "不明", "unknown", "none"}

    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root is not None else app_root()
        self.path = self.root / "data" / "product_master.json"
        self.last_new_records: list[dict[str, Any]] = []
        self.last_conflicts: list[dict[str, Any]] = []

    @classmethod
    def normalize_name(cls, value: object) -> str:
        text = cls._strip_trailing_metadata(value)
        text = re.sub(r"(?i)(?:1\s*)?(?:box|ボックス)", " box ", text)
        text = re.sub(r"[\s　\r\n\t]+", " ", text).strip().casefold()
        return re.sub(r"[\s「」『』【】・･_‐―\-:：/／\\|]", "", text)

    @classmethod
    def strong_normalize_name(cls, value: object) -> str:
        """商品種別も一致する場合だけ使う、既存BOX表記互換の比較名。"""
        text = cls._strip_trailing_metadata(value)
        text = cls._BOX_SUFFIX.sub("", text).strip()
        return cls.normalize_name(text)

    @classmethod
    def canonical_name(cls, value: object) -> str:
        text = unicodedata.normalize("NFKC", str(value or "")).strip()
        return cls._BOX_SUFFIX.sub("", text).strip() or text or "商品名未設定"

    @classmethod
    def identity_key(cls, product: dict[str, Any]) -> str:
        tcg_key = normalize_key(product.get("tcg_key"), product.get("tcg"))[0]
        identifiers = cls.identifiers(product)
        if identifiers:
            field, value = identifiers[0]
            return f"{tcg_key}|id:{field}:{value}"
        kind = cls.normalize_product_kind(product.get("product_kind"))
        return "|".join((
            tcg_key,
            kind,
            cls.strong_normalize_name(
                product.get("canonical_name") or product.get("name")
            ),
        ))

    @classmethod
    def identifiers(cls, product: dict[str, Any]) -> list[tuple[str, str]]:
        values: list[tuple[str, str]] = []
        for field in cls._IDENTIFIER_FIELDS:
            value = cls._normalize_identifier(product.get(field))
            if value:
                values.append((field, value))
        return values

    @classmethod
    def normalize_product_kind(cls, value: object) -> str:
        normalized = cls.normalize_name(value)
        return "" if normalized in cls._UNKNOWN_KINDS else normalized

    @classmethod
    def find_match(
        cls,
        products: list[dict[str, Any]],
        incoming: dict[str, Any],
    ) -> tuple[int | None, str]:
        """確実な一致が1件だけのときに限り、既存商品の位置を返す。"""
        incoming_tcg = normalize_key(
            incoming.get("tcg_key"), incoming.get("tcg")
        )[0]
        compatible = [
            (index, item)
            for index, item in enumerate(products)
            if normalize_key(item.get("tcg_key"), item.get("tcg"))[0] == incoming_tcg
            and not cls._has_kind_conflict(item, incoming)
            and not cls._has_brand_conflict(item, incoming)
        ]
        incoming_ids = set(cls.identifiers(incoming))
        if incoming_ids:
            matches = [
                index
                for index, item in compatible
                if incoming_ids
                & set(cls.identifiers(item))
            ]
            if len(matches) == 1:
                return matches[0], "identifier"
            if len(matches) > 1:
                return None, "ambiguous_identifier"

        exact_name = cls.normalize_name(
            incoming.get("canonical_name") or incoming.get("name")
        )
        if exact_name:
            matches = [
                index
                for index, item in compatible
                if cls.normalize_name(
                    item.get("canonical_name") or item.get("name")
                ) == exact_name
            ]
            if len(matches) == 1:
                return matches[0], "normalized_name"
            if len(matches) > 1:
                return None, "ambiguous_normalized_name"

        strong_name = cls.strong_normalize_name(
            incoming.get("canonical_name") or incoming.get("name")
        )
        incoming_kind = cls.normalize_product_kind(incoming.get("product_kind"))
        if strong_name:
            matches = [
                index
                for index, item in compatible
                if cls.strong_normalize_name(
                    item.get("canonical_name") or item.get("name")
                ) == strong_name
                and cls._kinds_compatible_for_strong_match(
                    cls.normalize_product_kind(item.get("product_kind")),
                    incoming_kind,
                )
            ]
            if len(matches) == 1:
                return matches[0], "strong_name"
            if len(matches) > 1:
                return None, "ambiguous_strong_name"
        return None, "no_match"

    def reconcile_product(
        self,
        current: dict[str, Any],
        incoming: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """既存IDを保持したまま、安全に属性と店舗情報を統合する。"""
        target = dict(current)
        changes: dict[str, Any] = {}
        now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

        aliases = list(target.get("aliases", []))
        for alias in (
            target.get("name"),
            incoming.get("name"),
            incoming.get("canonical_name"),
            *incoming.get("aliases", []),
        ):
            text = str(alias or "").strip()
            if text and text not in aliases:
                aliases.append(text)
        if aliases:
            target["aliases"] = aliases

        for key in (
            "official_url",
            "source_name",
            "source_type",
            "image_url",
            "product_image_url",
            "product_kind",
            "manufacturer",
            "maker",
            "brand",
            *self._IDENTIFIER_FIELDS,
        ):
            value = incoming.get(key)
            if value and not target.get(key):
                target[key] = value

        source_urls = {
            str(value).strip()
            for value in (
                *target.get("source_urls", []),
                target.get("official_url"),
                incoming.get("official_url"),
                incoming.get("source_url"),
            )
            if str(value or "").strip()
        }
        if source_urls:
            target["source_urls"] = sorted(source_urls)

        old_date = str(target.get("release_date", "")).strip()
        new_date = str(incoming.get("release_date", "")).strip()
        decision, reason = self._release_date_decision(target, incoming)
        if decision and new_date != old_date:
            history = list(target.get("release_date_history", []))
            entry = {
                "old_release_date": old_date,
                "new_release_date": new_date,
                "changed_at": now,
                "source_name": str(incoming.get("source_name", "")),
                "source_url": str(
                    incoming.get("official_url") or incoming.get("source_url") or ""
                ),
            }
            if not any(
                str(item.get("old_release_date", "")) == old_date
                and str(item.get("new_release_date", "")) == new_date
                for item in history
                if isinstance(item, dict)
            ):
                history.append(entry)
            target["release_date_history"] = history
            target["release_date"] = new_date
            target["release_date_source_priority"] = self._source_priority(incoming)
            observed_at = self._observed_at(incoming) or now
            target["release_date_observed_at"] = observed_at
            target["release_date_updated_at"] = now
            changes["release_date"] = {
                "before": old_date,
                "after": new_date,
                "reason": reason,
            }
        elif old_date and new_date and old_date != new_date:
            conflict = {
                "product_id": str(target.get("product_id") or target.get("id") or ""),
                "product_name": str(target.get("canonical_name") or target.get("name") or ""),
                "kept_release_date": old_date,
                "rejected_release_date": new_date,
                "reason": reason,
                "detected_at": now,
            }
            self.last_conflicts.append(conflict)

        target_sites = [
            dict(site) for site in target.get("sites", []) if isinstance(site, dict)
        ]
        known_sites = {
            (
                str(site.get("site_key", "")),
                str(site.get("url") or site.get("application_url") or site.get("product_url") or ""),
            )
            for site in target_sites
        }
        for raw_site in incoming.get("sites", []):
            if not isinstance(raw_site, dict):
                continue
            site = dict(raw_site)
            key = (
                str(site.get("site_key", "")),
                str(site.get("url") or site.get("application_url") or site.get("product_url") or ""),
            )
            if key not in known_sites:
                target_sites.append(site)
                known_sites.add(key)
        target["sites"] = target_sites

        if target != current:
            changes.setdefault("metadata", {"reason": "merged"})
            target["updated_at"] = now
        return target, changes

    def log_conflicts(self) -> None:
        if not self.last_conflicts:
            return
        from core.log_manager import LogManager

        logger = LogManager(self.root)
        for conflict in self.last_conflicts:
            logger.write(
                "発売日競合: "
                f'{conflict.get("product_name", "")} '
                f'維持={conflict.get("kept_release_date", "")} '
                f'候補={conflict.get("rejected_release_date", "")} '
                f'理由={conflict.get("reason", "")}',
                level="WARNING",
            )

    def synchronize(self, products: list[dict[str, Any]]) -> list[dict[str, Any]]:
        records = self.load()
        now = datetime.now(timezone.utc).astimezone().isoformat(
            timespec="seconds"
        )
        self.last_new_records = []
        self.last_conflicts = []
        resolved: list[dict[str, Any]] = []

        for raw in products:
            product = dict(raw)
            tcg_key = normalize_key(
                product.get("tcg_key"),
                product.get("tcg") or product.get("category"),
            )[0]
            product["tcg_key"] = tcg_key
            product["tcg"] = display_name(tcg_key, product.get("tcg"))
            product["sites"] = [
                normalize_application_site(site, product=product)
                for site in product.get("sites", [])
                if isinstance(site, dict)
            ]
            alias = str(product.get("name", "商品名未設定")).strip()
            identity = self.identity_key(product)
            match_index, _match_method = self.find_match(records, product)
            record = records[match_index] if match_index is not None else None
            if record is None:
                original_id = str(product.get("product_id") or product.get("id") or "").strip()
                product_id = original_id or hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
                record = {
                    "product_id": product_id,
                    "canonical_name": self.canonical_name(alias),
                    "aliases": [alias],
                    "release_date": str(product.get("release_date", "")),
                    "release_date_source_priority": self._source_priority(product),
                    "release_date_observed_at": (
                        self._observed_at(product) or now
                    ),
                    "tcg_key": tcg_key,
                    "official_url": str(product.get("official_url", "")),
                    "source_name": str(product.get("source_name", "")),
                    "source_type": str(product.get("source_type", "")),
                    "image_url": str(product.get("image_url", product.get("product_image_url", ""))),
                    "price": product.get("reference_price", product.get("msrp")),
                    "identity_key": identity,
                    "created_at": str(product.get("created_at") or now),
                    "updated_at": now,
                }
                if product.get("release_date_history"):
                    record["release_date_history"] = list(
                        product["release_date_history"]
                    )
                for key in (
                    "product_kind",
                    "manufacturer",
                    "maker",
                    "brand",
                    *self._IDENTIFIER_FIELDS,
                ):
                    if product.get(key):
                        record[key] = product[key]
                records.append(record)
                self.last_new_records.append(dict(record))
            else:
                merged_record, _changes = self.reconcile_product(record, product)
                record.clear()
                record.update(merged_record)

            for key, source_key in (
                ("official_url", "official_url"),
                ("image_url", "image_url"),
            ):
                value = product.get(source_key) or product.get("product_image_url" if key == "image_url" else source_key)
                if value and not record.get(key):
                    record[key] = value
            price = product.get("reference_price", product.get("msrp"))
            if price and not record.get("price"):
                record["price"] = price
            record["identity_key"] = self.identity_key(record)

            product["product_id"] = str(record["product_id"])
            product["id"] = str(record["product_id"])
            product["canonical_name"] = str(record["canonical_name"])
            product["aliases"] = list(record.get("aliases", []))
            product["release_date"] = str(record.get("release_date", ""))
            if record.get("release_date_history"):
                product["release_date_history"] = list(record["release_date_history"])
            for key in (
                "release_date_updated_at",
                "release_date_observed_at",
                "release_date_source_priority",
                "source_urls",
            ):
                if record.get(key):
                    product[key] = record[key]
            product.setdefault("created_at", record.get("created_at", now))
            resolved.append(product)

        self._save_if_changed(records)
        return self._merge_products(resolved)

    def load(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        return data if isinstance(data, list) else []

    def _save_if_changed(self, records: list[dict[str, Any]]) -> None:
        current = self.load()
        if current == records:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)

    @classmethod
    def _strip_trailing_metadata(cls, value: object) -> str:
        text = unicodedata.normalize("NFKC", str(value or ""))
        text = re.sub(r"[\r\n\t]+", " ", text).strip()
        previous = None
        while text != previous:
            previous = text
            text = cls._TRAILING_PRICE.sub("", text).strip()
            text = cls._TRAILING_RELEASE_DATE.sub("", text).strip()
        return text

    @staticmethod
    def _normalize_identifier(value: object) -> str:
        return re.sub(
            r"[^0-9a-z]",
            "",
            unicodedata.normalize("NFKC", str(value or "")).casefold(),
        )

    @classmethod
    def _brand(cls, product: dict[str, Any]) -> str:
        for field in cls._BRAND_FIELDS:
            if product.get(field):
                return cls.normalize_name(product[field])
        return ""

    @classmethod
    def _has_kind_conflict(
        cls, left: dict[str, Any], right: dict[str, Any]
    ) -> bool:
        left_kind = cls.normalize_product_kind(left.get("product_kind"))
        right_kind = cls.normalize_product_kind(right.get("product_kind"))
        return bool(left_kind and right_kind and left_kind != right_kind)

    @classmethod
    def _has_brand_conflict(
        cls, left: dict[str, Any], right: dict[str, Any]
    ) -> bool:
        left_brand = cls._brand(left)
        right_brand = cls._brand(right)
        return bool(left_brand and right_brand and left_brand != right_brand)

    @staticmethod
    def _kinds_compatible_for_strong_match(left: str, right: str) -> bool:
        return not (left and right and left != right)

    @classmethod
    def _source_priority(cls, product: dict[str, Any]) -> int:
        explicit = product.get("release_date_source_priority")
        try:
            if explicit is not None:
                return max(0, int(explicit))
        except (TypeError, ValueError):
            pass
        source_type = str(product.get("source_type", "")).casefold()
        source_name = str(product.get("source_name", "")).casefold()
        if (
            source_type in {"official", "official_source", "auto_monitor"}
            or "メーカー公式" in source_name
            or source_name.endswith("公式")
        ):
            return 300
        if (
            source_type in {"retail_search", "official_store", "card_shop"}
            or "ショップ" in source_name
            or "ストア" in source_name
            or product.get("sites")
        ):
            return 200
        return 100

    @staticmethod
    def _observed_at(product: dict[str, Any]) -> str:
        for key in (
            "release_date_observed_at",
            "source_checked_at",
            "fetched_at",
            "detected_at",
            "updated_at",
            "auto_added_at",
        ):
            value = str(product.get(key, "")).strip()
            if value:
                return value
        return ""

    @staticmethod
    def _parse_timestamp(value: str) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(
                tzinfo=datetime.now().astimezone().tzinfo
            )
        return parsed.astimezone(timezone.utc)

    def _release_date_decision(
        self,
        current: dict[str, Any],
        incoming: dict[str, Any],
    ) -> tuple[bool, str]:
        old_date = str(current.get("release_date", "")).strip()
        new_date = str(incoming.get("release_date", "")).strip()
        if not new_date:
            return False, "incoming_date_unknown"
        if not old_date:
            return True, "existing_date_unknown"
        if new_date == old_date:
            return False, "same_date"

        old_priority = self._source_priority(current)
        new_priority = self._source_priority(incoming)
        if new_priority < old_priority:
            return False, "lower_priority_source"

        old_observed = self._parse_timestamp(
            str(
                current.get("release_date_observed_at")
                or current.get("release_date_updated_at")
                or ""
            )
        )
        new_observed = self._parse_timestamp(self._observed_at(incoming))
        if old_observed and new_observed and new_observed < old_observed:
            return False, "older_observation"

        history = [
            item
            for item in current.get("release_date_history", [])
            if isinstance(item, dict)
        ]
        if new_priority <= old_priority and any(
            str(item.get("old_release_date", "")) == new_date
            for item in history
        ):
            return False, "historical_date_rollback"
        return True, "trusted_newer_observation"

    @staticmethod
    def _merge_products(products: list[dict[str, Any]]) -> list[dict[str, Any]]:
        merged: dict[str, dict[str, Any]] = {}
        order: list[str] = []
        for product in products:
            product_id = str(product.get("product_id", product.get("id", "")))
            if product_id not in merged:
                merged[product_id] = product
                merged[product_id]["sites"] = list(product.get("sites", []))
                order.append(product_id)
                continue
            target = merged[product_id]
            known = {
                (str(site.get("site_key", "")), str(site.get("url", "")))
                for site in target.get("sites", [])
            }
            for site in product.get("sites", []):
                key = (str(site.get("site_key", "")), str(site.get("url", "")))
                if key not in known:
                    target.setdefault("sites", []).append(site)
                    known.add(key)
            target["aliases"] = sorted(set(target.get("aliases", [])) | set(product.get("aliases", [])))
        return [merged[key] for key in order]
