from __future__ import annotations

import re
from typing import Iterable


APPLICATION_TITLE_PATTERN = re.compile(
    r"(?:抽選|応募|予約|入荷|再入荷|販売)(?:受付|開始|案内|情報|について|のお知らせ|中止|終了|予定|商品)*"
)
PRODUCT_NAME_PATTERN = re.compile(
    r"(?:BOX|パック|デッキ|カードセット|プレミアムセット|スターター|構築済み)",
    re.IGNORECASE,
)
APPLICATION_RECORD_TYPES = {"APPLICATION", "APPLICATION_CANDIDATE", "APPLICATION_CONFIRMED"}


def is_product_record(record: dict) -> bool:
    """Return whether a saved record belongs in the product catalog UI.

    This is deliberately a presentation policy: it never mutates or removes the
    saved record, so application history remains available to the dashboard.
    """
    information_type = str(record.get("information_type", "")).strip().upper()
    if information_type in APPLICATION_RECORD_TYPES:
        return False

    if any(
        str(record.get(key, "")).strip()
        for key in ("official_product_id", "product_code", "jan_code")
    ):
        return True

    name = str(record.get("name", "")).strip()
    kind = str(record.get("product_kind", "")).strip()
    if PRODUCT_NAME_PATTERN.search(name) or PRODUCT_NAME_PATTERN.search(kind):
        return True

    source_type = str(record.get("source_type", "")).strip().casefold()
    application_source = source_type in {
        "retail_search", "application", "application_candidate",
        "trusted_store_x", "official_x",
    }
    return not (application_source and APPLICATION_TITLE_PATTERN.search(name))


def product_records(records: Iterable[dict]) -> list[dict]:
    return [record for record in records if isinstance(record, dict) and is_product_record(record)]
