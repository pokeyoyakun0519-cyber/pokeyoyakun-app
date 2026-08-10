from __future__ import annotations

import re
from typing import Any


class RetailPricePolicy:
    """正規販売情報だけを商品価格として採用するための判定。"""

    EXCLUDED_PATTERNS = (
        ("中古品", r"中古|ユーズド|開封済み|開封品"),
        ("オリパ", r"オリパ|オリジナルパック"),
        ("まとめ売り", r"まとめ売り|大量セット|引退品"),
        ("抱き合わせ販売", r"抱き合わせ|セット販売|\d+\s*(?:個|箱|BOX)セット"),
        ("オークション・フリマ", r"入札|オークション|フリマ|メルカリ|ヤフオク"),
        ("海外版", r"海外版|英語版|北米版|EU版|アジア版|並行輸入"),
        ("プレミア価格表記", r"プレミア価格|希少価格|相場価格"),
        ("販売終了・在庫切れ", r"在庫切れ|販売終了|受付終了|売り切れ"),
    )
    KIND_TOLERANCE = {
        "ブースターパック": 1.15,
        "エクストラブースター": 1.15,
        "スタートデッキ": 1.20,
        "スターターデッキ": 1.20,
        "構築デッキ": 1.20,
        "プレミアムカードコレクション": 1.10,
        "プレミアム商品": 1.10,
        "アクセサリー": 1.25,
        "その他": 1.15,
    }

    @classmethod
    def evaluate(
        cls,
        candidate: dict[str, Any],
        offer: dict[str, Any],
    ) -> dict[str, Any]:
        text = " ".join(
            str(offer.get(key, ""))
            for key in ("title", "text", "notice", "seller", "shipped_by")
        )
        for reason, pattern in cls.EXCLUDED_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                return cls._rejected(reason)

        retailer_id = str(offer.get("site_key", ""))
        seller = str(offer.get("seller", "")).strip()
        shipped_by = str(offer.get("shipped_by", "")).strip()
        verified = bool(offer.get("retailer_verified", False))

        if retailer_id == "amazon_jp":
            amazon_seller = seller.casefold() in {"amazon.co.jp", "amazon japan g.k."}
            amazon_shipping = shipped_by.casefold() in {
                "amazon.co.jp", "amazon japan g.k."
            }
            if not (amazon_seller and amazon_shipping):
                return cls._rejected("Amazonマーケットプレイス第三者出品")
        elif retailer_id in {"yahoo_shopping", "rakuten_marketplace", "dmm_marketplace"}:
            if not (verified and bool(offer.get("official_store_verified", False))):
                return cls._rejected("モール内の公式・正規販売店を確認できません")
        elif retailer_id == "rakuten_books":
            if seller and "楽天ブックス" not in seller:
                return cls._rejected("楽天市場の第三者店舗")
        elif not verified:
            return cls._rejected("販売元を正規販売店として確認できません")

        reference_price = cls._reference_price(candidate)
        sale_price = cls._sale_price(offer)
        result = {
            "accepted": True,
            "exclusion_reason": "",
            "reference_price": reference_price,
            "sale_price": sale_price,
            "price_status": "価格未確認",
            "usable_for_price": False,
            "seller": seller or str(offer.get("site_name", "正規販売店")),
            "shipped_by": shipped_by,
        }

        if reference_price is None:
            return result
        result["price_status"] = f"定価: {reference_price:,}円"
        if sale_price is None:
            return result

        kind = str(candidate.get("product_kind", "その他"))
        tolerance = cls.KIND_TOLERANCE.get(kind, cls.KIND_TOLERANCE["その他"])
        if sale_price > round(reference_price * tolerance):
            return cls._rejected(
                "基準価格を大幅に超過",
                reference_price=reference_price,
                sale_price=sale_price,
            )

        result["price_status"] = (
            f"定価: {reference_price:,}円 / 販売価格: {sale_price:,}円"
        )
        result["usable_for_price"] = True
        return result

    @classmethod
    def normalize_price(
        cls, value: object, *, tax_included: bool = True
    ) -> int | None:
        if isinstance(value, bool) or value is None:
            return None
        match = re.search(r"(\d[\d,]*)", str(value))
        if not match:
            return None
        amount = int(match.group(1).replace(",", ""))
        if amount <= 0:
            return None
        return amount if tax_included else round(amount * 1.10)

    @classmethod
    def _reference_price(cls, candidate: dict[str, Any]) -> int | None:
        for key in ("msrp_tax_included", "reference_price", "official_price"):
            value = cls.normalize_price(candidate.get(key), tax_included=True)
            if value is not None:
                return value
        if candidate.get("msrp") is not None:
            return cls.normalize_price(
                candidate.get("msrp"),
                tax_included=bool(candidate.get("msrp_includes_tax", True)),
            )
        return None

    @classmethod
    def _sale_price(cls, offer: dict[str, Any]) -> int | None:
        for key in ("sale_price_tax_included", "sale_price", "price"):
            if offer.get(key) is None:
                continue
            return cls.normalize_price(
                offer.get(key),
                tax_included=bool(offer.get("price_includes_tax", True)),
            )
        text = str(offer.get("text", ""))
        # 「送料 550円」だけを販売価格として扱わない。
        match = re.search(
            r"(?:販売価格|価格|税込)\s*[:：]?\s*[￥¥]?\s*(\d[\d,]*)\s*円?",
            text,
            re.IGNORECASE,
        )
        return cls.normalize_price(match.group(1)) if match else None

    @staticmethod
    def _rejected(
        reason: str,
        *,
        reference_price: int | None = None,
        sale_price: int | None = None,
    ) -> dict[str, Any]:
        return {
            "accepted": False,
            "exclusion_reason": reason,
            "reference_price": reference_price,
            "sale_price": sale_price,
            "price_status": "除外",
            "usable_for_price": False,
            "seller": "",
            "shipped_by": "",
        }
