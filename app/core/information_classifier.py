from __future__ import annotations

import re
from typing import Any


PRODUCT = "PRODUCT"
APPLICATION = "APPLICATION"
RESTOCK = "RESTOCK"
NEWS = "NEWS"

_NON_PRODUCT_TERMS = (
    "イベント", "大会", "デッキレシピ", "買取", "キャンペーン",
    "お知らせ", "ニュース", "ルール", "カードリスト",
)
_SUPPLY_TERMS = (
    "スリーブ", "デッキシールド", "デッキケース", "プレイマット",
    "カードケース", "ラバーマット", "アクセサリー", "サプライ",
)
_APPLICATION_TERMS = ("抽選", "予約", "応募", "受付")
_RESTOCK_TERMS = ("再販", "再入荷", "再販売")
_PRODUCT_KINDS = (
    "拡張パック", "強化拡張パック", "ブースターパック",
    "エクストラブースター", "スタートデッキ", "スターターデッキ",
    "スターターセット", "構築デッキ", "デッキセット",
    "カードセット", "カードコレクション", "box", "パック",
)


def classify_information(record: dict[str, Any]) -> str:
    """Classify a fetched record without mutating it.

    Product is intentionally conservative: news-like text cannot become a
    product merely because it mentions a card game.
    """
    text = " ".join(
        str(record.get(key, ""))
        for key in ("name", "title", "status", "product_kind", "body")
    ).casefold()
    if any(term in text for term in _RESTOCK_TERMS):
        return RESTOCK
    if any(term in text for term in _APPLICATION_TERMS):
        return APPLICATION
    if any(term in text for term in _NON_PRODUCT_TERMS):
        return NEWS
    if any(term.casefold() in text for term in _SUPPLY_TERMS):
        return NEWS
    return PRODUCT if has_product_evidence(record) else NEWS


def has_product_evidence(record: dict[str, Any]) -> bool:
    if str(record.get("release_date", "")).strip():
        return True
    if any(
        str(record.get(key, "")).strip()
        for key in ("jan", "jan_code", "product_code", "official_product_id")
    ):
        return True
    if record.get("msrp") not in (None, ""):
        return True
    kind = str(record.get("product_kind", "")).casefold()
    if any(term.casefold() in kind for term in _PRODUCT_KINDS):
        return True
    url = str(record.get("official_url", ""))
    return bool(
        record.get("manufacturer_official")
        and re.search(r"/(?:products?|product)/", url, re.IGNORECASE)
    )
