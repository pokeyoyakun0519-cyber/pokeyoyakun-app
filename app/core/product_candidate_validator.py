import re
from typing import Any


PRODUCT_TERMS = (
    "強化拡張パック",
    "拡張パック",
    "ブースターパック",
    "ハイクラスパック",
    "スターターセットex",
    "スターターセット",
    "スタートデッキ",
    "スターターデッキ",
    "構築デッキ",
    "プレミアムデッキセット",
    "デッキセット",
    "デッキビルドパック",
    "ストラクチャーデッキ",
    "LIMITED PACK",
    "PREMIUM PACK",
    "WORLD PREMIERE PACK",
    "基本パック",
    "コンセプトパック",
    "スペシャルパック",
)

REJECT_PHRASES = (
    "遊びです",
    "遊び方",
    "対戦する",
    "対戦をする",
    "参加する",
    "参加できます",
    "デッキを組んで",
    "デッキを組む",
    "その場で開封",
    "その場で構築",
    "プレイヤーでもすぐに参加",
    "イベント",
    "大会",
    "キャンペーン",
    "ルール",
    "カード検索",
    "収録カードを使って",
)

TITLEISH_TAGS = (
    "h1",
    "h2",
    "title",
    "img_alt",
    "product_info",
)


class ProductCandidateValidator:
    """商品名候補の誤検知を減らすための共通判定。"""

    def evaluate(
        self,
        name: str,
        *,
        source_url: str = "",
        evidence_type: str = "",
        release_date: str = "",
    ) -> dict[str, Any]:
        normalized = re.sub(r"\s+", " ", name).strip()
        reasons: list[str] = []
        score = 0.0

        if not normalized:
            return {
                "accepted": False,
                "review_required": False,
                "confidence": 0.0,
                "reasons": ["商品名が空です"],
            }

        if any(term in normalized for term in PRODUCT_TERMS):
            score += 0.35
        else:
            reasons.append("商品種別キーワードがありません")

        if re.search(r"[「『][^」』]{2,80}[」』]", normalized):
            score += 0.25
        elif re.search(r"(?:ex|EX)\b", normalized):
            score += 0.10
        else:
            reasons.append("明確な商品名表記がありません")

        if evidence_type in TITLEISH_TAGS:
            score += 0.20
        elif evidence_type:
            score += 0.05

        if release_date:
            score += 0.10

        if "/ex/" in source_url:
            score += 0.10
        elif "/info/" in source_url:
            score -= 0.05

        if len(normalized) > 60:
            score -= 0.30
            reasons.append("候補名が長すぎます")

        punctuation_count = len(
            re.findall(r"[、。！？!?]", normalized)
        )
        if punctuation_count >= 2:
            score -= 0.25
            reasons.append("説明文の可能性があります")

        matched_rejects = [
            phrase
            for phrase in REJECT_PHRASES
            if phrase in normalized
        ]
        if matched_rejects:
            score -= 0.55
            reasons.append(
                "説明・イベント文言を含みます: "
                + "、".join(matched_rejects[:3])
            )

        if normalized.endswith(("です", "ます", "できます")):
            score -= 0.20
            reasons.append("説明文の語尾です")

        if "1つ" in normalized or "1つ」" in normalized:
            score -= 0.15
            reasons.append("遊び方説明の可能性があります")

        score = max(0.0, min(1.0, score))
        accepted = score >= 0.72
        review_required = 0.45 <= score < 0.72

        return {
            "accepted": accepted,
            "review_required": review_required,
            "confidence": round(score, 3),
            "reasons": reasons,
        }

    def clean_name(self, name: str) -> str:
        value = re.sub(r"\s+", " ", name).strip()
        value = value.strip("「」『』[]【】 ")
        value = re.sub(
            r"\s*(?:が|を)?\s*\d{1,2}月\d{1,2}日.*$",
            "",
            value,
        ).strip(" 、。！!")
        return value[:120]
