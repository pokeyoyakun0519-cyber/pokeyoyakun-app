from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any

from core.runtime_paths import app_root
from core.tcg_categories import normalize_key


class ProductMasterManager:
    """表記揺れを吸収し、商品を安定したproduct_idへ統合する。"""

    _BOX_SUFFIX = re.compile(
        r"(?:\s|　)*(?:BOX|ＢＯＸ|ボックス|1BOX|１ＢＯＸ)(?:\s|　)*$",
        re.IGNORECASE,
    )

    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root is not None else app_root()
        self.path = self.root / "data" / "product_master.json"
        self.last_new_records: list[dict[str, Any]] = []

    @classmethod
    def normalize_name(cls, value: object) -> str:
        text = unicodedata.normalize("NFKC", str(value or "")).strip()
        text = cls._BOX_SUFFIX.sub("", text)
        return re.sub(r"[\s　「」『』【】・･_\-‐―]", "", text).casefold()

    @classmethod
    def canonical_name(cls, value: object) -> str:
        text = unicodedata.normalize("NFKC", str(value or "")).strip()
        return cls._BOX_SUFFIX.sub("", text).strip() or text or "商品名未設定"

    @classmethod
    def identity_key(cls, product: dict[str, Any]) -> str:
        tcg_key = normalize_key(product.get("tcg_key"), product.get("tcg"))[0]
        return "|".join((
            tcg_key,
            cls.normalize_name(product.get("canonical_name") or product.get("name")),
            str(product.get("release_date", "")).strip(),
        ))

    def synchronize(self, products: list[dict[str, Any]]) -> list[dict[str, Any]]:
        records = self.load()
        by_identity = {str(item.get("identity_key", "")): item for item in records}
        by_alias = {
            (str(item.get("tcg_key", "other")), self.normalize_name(alias)): item
            for item in records
            for alias in [item.get("canonical_name", ""), *item.get("aliases", [])]
            if alias
        }
        now = datetime.now().isoformat(timespec="seconds")
        self.last_new_records = []
        resolved: list[dict[str, Any]] = []

        for raw in products:
            product = dict(raw)
            tcg_key = normalize_key(product.get("tcg_key"), product.get("tcg"))[0]
            alias = str(product.get("name", "商品名未設定")).strip()
            identity = self.identity_key(product)
            record = by_identity.get(identity) or by_alias.get((tcg_key, self.normalize_name(alias)))
            if record is None:
                original_id = str(product.get("product_id") or product.get("id") or "").strip()
                product_id = original_id or hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
                record = {
                    "product_id": product_id,
                    "canonical_name": self.canonical_name(alias),
                    "aliases": [alias],
                    "release_date": str(product.get("release_date", "")),
                    "tcg_key": tcg_key,
                    "official_url": str(product.get("official_url", "")),
                    "image_url": str(product.get("image_url", product.get("product_image_url", ""))),
                    "price": product.get("reference_price", product.get("msrp")),
                    "identity_key": identity,
                    "created_at": str(product.get("created_at") or now),
                    "updated_at": now,
                }
                records.append(record)
                by_identity[identity] = record
                self.last_new_records.append(dict(record))
            elif alias and alias not in record.get("aliases", []):
                record.setdefault("aliases", []).append(alias)
                record["updated_at"] = now

            for key, source_key in (
                ("official_url", "official_url"),
                ("image_url", "image_url"),
                ("release_date", "release_date"),
            ):
                value = product.get(source_key) or product.get("product_image_url" if key == "image_url" else source_key)
                if value and not record.get(key):
                    record[key] = value
            price = product.get("reference_price", product.get("msrp"))
            if price and not record.get("price"):
                record["price"] = price

            product["product_id"] = str(record["product_id"])
            product["id"] = str(record["product_id"])
            product["canonical_name"] = str(record["canonical_name"])
            product["aliases"] = list(record.get("aliases", []))
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
