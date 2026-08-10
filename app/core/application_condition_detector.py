from __future__ import annotations

import re
from typing import Any


class ApplicationConditionDetector:
    """公開文面から応募条件を抽出し、曖昧な条件は断定しない。"""

    RULES = (
        ("app_required", "アプリ必須", r"(?:公式|専用)?アプリ(?:から|で|のみ|限定|必須)|アプリ受付", r"アプリ"),
        ("membership_required", "会員登録必須", r"(?:会員登録|会員資格|会員ID|アカウント)(?:が)?必須|会員限定", r"会員|アカウント|ID"),
        ("credit_card_required", "クレジットカード必須", r"クレジットカード(?:登録|決済)?(?:が)?必須|クレカ限定", r"クレジットカード|クレカ"),
        ("store_pickup_only", "店舗受取限定", r"店(?:頭|舗)受取(?:のみ|限定)|受取店舗限定", r"店舗受取|店頭受取"),
        ("identity_verification", "本人確認", r"本人確認(?:書類)?(?:が)?必須|身分証(?:明書)?(?:が)?必要", r"本人確認|身分証"),
        ("purchase_history", "過去購入履歴", r"(?:過去|期間内)の?購入履歴(?:が)?(?:必須|必要)|購入実績(?:が)?必要", r"購入履歴|購入実績"),
        ("region_limited", "地域限定", r"(?:お住まい|居住(?:者|地)?|配送先).{0,12}(?:限定|のみ)|(?:地域|都道府県)限定", r"地域|居住|都道府県"),
        ("age_limit", "年齢制限", r"\d{1,2}歳(?:以上|以下|未満)|年齢制限", r"年齢"),
        ("in_store_only", "店頭受付のみ", r"店頭(?:での)?(?:受付|応募)(?:のみ|限定)|Web受付なし", r"店頭受付|店頭応募"),
        ("bundle_sale", "抱き合わせ", r"抱き合わせ|対象商品.{0,20}(?:同時購入|セット購入)(?:が)?必須", r"セット販売|同時購入"),
        ("payment_method", "支払方法指定", r"(?:支払|決済)方法.{0,16}(?:限定|指定)|(?:現金|クレジットカード|代引き)(?:のみ|限定)", r"支払方法|決済方法"),
        ("no_cancellation", "キャンセル不可", r"キャンセル(?:は|が)?(?:不可|できません|お受けできません)", r"キャンセル"),
    )

    @classmethod
    def detect(cls, source: dict[str, Any]) -> list[dict[str, Any]]:
        text = "\n".join(
            str(source.get(key, ""))
            for key in (
                "application_conditions", "application_method", "notice", "status",
                "period_evidence", "description", "text",
            )
            if source.get(key)
        )
        compact = re.sub(r"\s+", " ", text).strip()
        output = []
        for key, label, strong_pattern, weak_pattern in cls.RULES:
            strong = re.search(strong_pattern, compact, re.IGNORECASE)
            weak = strong or re.search(weak_pattern, compact, re.IGNORECASE)
            if not weak:
                continue
            confident = strong is not None
            output.append({
                "key": key,
                "label": label,
                "confidence": 0.9 if confident else 0.55,
                "display": label if confident else f"{label}（要確認）",
                "requires_confirmation": not confident,
                "evidence": weak.group(0)[:120],
            })
        return output
