from __future__ import annotations

import re
from typing import Any

from core.tcg_categories import display_name, normalize_key


_APPLICATION_STATUS = re.compile(
    r"(?:応募|申込|申し込み|抽選)(?:情報)?(?:受付|実施|販売|開始|中|あり)|"
    r"予約(?:情報)?(?:受付|開始|中|可能|あり)|受付中"
)
_NON_SPECIFIC_STATUS = {"販売・抽選情報あり", "販売情報あり", "商品掲載あり", "販売予定"}


def has_application_evidence(site: dict[str, Any]) -> bool:
    """商品掲載ではなく、実在する応募・予約情報かを判定する。"""
    if str(site.get("application_url", "")).strip():
        return True
    if any(str(site.get(key, "")).strip() for key in (
        "application_period", "order_period", "application_start_at",
        "application_end_at", "result_announcement_at",
    )):
        return True
    if bool(site.get("applied")):
        return True
    if str(site.get("application_state", "")).strip() not in {"", "未応募"}:
        return True
    if str(site.get("result_status", "")).strip() not in {"", "未確認"}:
        return True
    status = str(site.get("status", "")).strip()
    return status not in _NON_SPECIFIC_STATUS and bool(_APPLICATION_STATUS.search(status))


def normalize_application_site(
    site: dict[str, Any],
    *,
    product: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """旧sitesを保ったまま、TCGと商品／応募URLの意味を揃える。"""
    normalized = dict(site)
    product = product or {}
    tcg_key = normalize_key(
        normalized.get("tcg_key", product.get("tcg_key")),
        normalized.get("tcg") or normalized.get("category")
        or product.get("tcg") or product.get("category"),
    )[0]
    normalized["tcg_key"] = tcg_key
    normalized["tcg"] = display_name(tcg_key)

    related_url = str(normalized.get("url", "")).strip()
    product_url = str(normalized.get("product_url", "")).strip()
    if not product_url and related_url:
        normalized["product_url"] = related_url

    if has_application_evidence(normalized):
        application_url = str(normalized.get("application_url", "")).strip()
        if not application_url and related_url:
            normalized["application_url"] = related_url
    else:
        # 旧実装が商品URLを応募URLへコピーしたデータは、明確な根拠がなければ戻す。
        if normalized.get("application_url") == related_url:
            normalized.pop("application_url", None)
    return normalized
