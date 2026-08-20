from __future__ import annotations

from typing import Any, Mapping


CARD = "CARD"
SUPPLY = "SUPPLY"
COLLAB_LIMITED = "COLLAB_LIMITED"
PRODUCT_CATEGORIES = (CARD, SUPPLY, COLLAB_LIMITED)
PRODUCT_CATEGORY_LABELS = {
    CARD: "カード商品",
    SUPPLY: "サプライ",
    COLLAB_LIMITED: "コラボ・限定",
}

SUPPLY_TERMS = (
    "スリーブ",
    "プレイマット",
    "デッキケース",
    "ストレージ",
    "バインダー",
    "アクセサリー",
    "サプライセット",
)
LIMITED_TERMS = (
    "コラボ",
    "周年",
    "イベント限定",
    "店舗限定",
    "記念商品",
    "数量限定",
    "キャンペーン商品",
    "特別セット",
)
LIMITED_PRODUCT_TERMS = SUPPLY_TERMS + (
    "カード",
    "セット",
    "BOX",
    "ボックス",
    "パック",
    "デッキ",
)


def normalize_product_category(record: Mapping[str, Any] | str | None) -> str:
    if isinstance(record, Mapping):
        value = record.get("product_category") or record.get("product_type")
    else:
        value = record
    normalized = str(value or "").strip().upper()
    return normalized if normalized in PRODUCT_CATEGORIES else CARD


def detect_product_category(text: object) -> str:
    value = str(text or "")
    if any(term in value for term in LIMITED_TERMS) and any(
        term.casefold() in value.casefold() for term in LIMITED_PRODUCT_TERMS
    ):
        return COLLAB_LIMITED
    if any(term in value for term in SUPPLY_TERMS):
        return SUPPLY
    return CARD
