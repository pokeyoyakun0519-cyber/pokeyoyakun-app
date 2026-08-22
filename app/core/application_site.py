from __future__ import annotations

import re
import unicodedata
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from core.tcg_categories import display_name, normalize_key


_APPLICATION_STATUS = re.compile(
    r"(?:応募|申込|申し込み|抽選)(?:情報)?(?:受付|実施|販売|開始|中|あり)|"
    r"予約(?:情報)?(?:受付|開始|中|可能|あり)|受付中"
)
_NON_SPECIFIC_STATUS = {"販売・抽選情報あり", "販売情報あり", "商品掲載あり", "販売予定"}
_APPLICATION_ARTICLE_TYPES = {"application", "lottery", "reservation"}
_NON_APPLICATION_ARTICLE_TYPES = {
    "excluded", "event", "general_news", "needs_review", "product_info",
    "product_schedule", "regular_sale",
}
_APPLICATION_METHOD = re.compile(r"応募|申込|申し込み|抽選|予約|受付")
_TRACKING_QUERY_KEYS = {
    "fbclid", "gclid", "ref_src", "ref_url", "twclid", "xclid",
}
_STRONG_APPLICATION_FIELDS = (
    "application_period", "order_period", "application_start_at",
    "application_end_at", "result_announcement_at", "result_date",
)
_CONTEXTUAL_APPLICATION_FIELDS = (
    "purchase_period", "receipt_period", "target_store", "target_stores",
)
_SALES_MODES = {"ONLINE", "STORE", "HYBRID", "UNKNOWN"}
_ONLINE_SALES_EVIDENCE = re.compile(
    r"(?:web|online|オンライン|ネット(?:応募|抽選|受付|販売)|"
    r"ウェブ|応募フォーム|公式アプリ|アプリ受付|通販|(?<![a-z])ec(?![a-z]))",
    re.IGNORECASE,
)
_STORE_SALES_EVIDENCE = re.compile(
    r"(?:店頭|店舗(?:受付|抽選|販売|購入|受取)|受取店舗|店舗へ来店|"
    r"店舗にて|店頭で|Loppi)",
    re.IGNORECASE,
)


def _url_identity(value: Any) -> str:
    """追跡情報を除いた比較専用URLを返す。元のURLは変更しない。"""
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parsed = urlsplit(text)
        if parsed.scheme.casefold() not in {"http", "https"} or not parsed.netloc:
            return ""
        query = [
            (key, item)
            for key, item in parse_qsl(parsed.query, keep_blank_values=True)
            if key.casefold() not in _TRACKING_QUERY_KEYS
            and not key.casefold().startswith("utm_")
        ]
        return urlunsplit((
            parsed.scheme.casefold(),
            parsed.netloc.casefold(),
            parsed.path.rstrip("/") or "/",
            urlencode(query, doseq=True),
            "",
        ))
    except (TypeError, ValueError):
        return ""


def _has_independent_application_evidence(site: dict[str, Any]) -> bool:
    if any(bool(site.get(key)) for key in _STRONG_APPLICATION_FIELDS):
        return True
    article_type = str(site.get("article_type", "") or "").strip().casefold()
    if article_type in _APPLICATION_ARTICLE_TYPES:
        return True
    product_article = article_type in _NON_APPLICATION_ARTICLE_TYPES
    if not product_article and any(
        bool(site.get(key)) for key in _CONTEXTUAL_APPLICATION_FIELDS
    ):
        return True
    method = str(site.get("application_method", "") or "").strip()
    if not product_article and method and _APPLICATION_METHOD.search(method):
        return True
    if bool(site.get("applied")):
        return True
    if str(site.get("application_state", "") or "").strip() not in {"", "未応募"}:
        return True
    if str(site.get("result_status", "") or "").strip() not in {"", "未確認"}:
        return True
    return any(
        status not in _NON_SPECIFIC_STATUS and bool(_APPLICATION_STATUS.search(status))
        for status in (
            str(site.get(key, "") or "").strip()
            for key in ("status", "application_status", "reception_status")
        )
    )


def _duplicates_related_url(site: dict[str, Any]) -> bool:
    application_url = _url_identity(site.get("application_url"))
    if not application_url:
        return False
    return any(
        application_url == related
        for related in (
            _url_identity(site.get("url")),
            _url_identity(site.get("product_url")),
            _url_identity(site.get("source_url")),
        )
        if related
    )


def has_application_evidence(site: dict[str, Any]) -> bool:
    """商品掲載ではなく、実在する応募・予約情報かを判定する。"""
    application_url = str(site.get("application_url", "") or "").strip()
    if application_url and not _duplicates_related_url(site):
        return True
    return _has_independent_application_evidence(site)


def sales_mode_from_evidence(site: dict[str, Any]) -> str:
    """明示された販売・応募経路だけから販売方式を返す。"""
    aliases = {
        "PHYSICAL": "STORE",
        "CHAIN": "STORE",
        "WEB": "ONLINE",
        "EC": "ONLINE",
    }
    for key in ("sales_mode", "sales_method_hint", "channel"):
        direct = str(site.get(key) or "").strip().upper()
        direct = aliases.get(direct, direct)
        if direct in _SALES_MODES and direct != "UNKNOWN":
            return direct

    values: list[str] = []
    for key in (
        "application_method", "application_conditions", "conditions",
        "notice", "period_evidence", "sales_type", "sales_method_hint", "channel",
    ):
        value = site.get(key)
        if isinstance(value, (list, tuple, set)):
            values.extend(str(item) for item in value)
        elif value:
            values.append(str(value))
    text = unicodedata.normalize("NFKC", " ".join(values))
    online = bool(_ONLINE_SALES_EVIDENCE.search(text))
    store = bool(_STORE_SALES_EVIDENCE.search(text))

    application_url = str(site.get("application_url") or "").strip()
    try:
        host = (urlsplit(application_url).hostname or "").casefold()
    except ValueError:
        host = ""
    if any(marker in host for marker in (
        "pokemoncenter-online", "p-bandai.jp", "premium-bandai",
    )):
        online = True

    target_store = bool(site.get("target_store") or site.get("target_stores"))
    branch_source = str(site.get("source_type") or "").strip().upper() in {
        "OFFICIAL_SHOP_BRANCH", "OFFICIAL_STORE_PAGE",
    }
    if target_store and branch_source:
        store = True

    if online and store:
        return "HYBRID"
    if online:
        return "ONLINE"
    if store:
        return "STORE"
    return "UNKNOWN"


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
    normalized["sales_mode"] = sales_mode_from_evidence(normalized)

    # 旧実装が商品URLを応募URLへコピーした値は、応募固有の根拠がなければ
    # 応募判定より先にメモリ上だけで除去する。
    if (
        _duplicates_related_url(normalized)
        and not _has_independent_application_evidence(normalized)
    ):
        normalized.pop("application_url", None)

    related_url = str(normalized.get("url", "")).strip()
    product_url = str(normalized.get("product_url", "")).strip()
    if not product_url and related_url:
        normalized["product_url"] = related_url

    if has_application_evidence(normalized):
        application_url = str(normalized.get("application_url", "")).strip()
        if not application_url and related_url:
            normalized["application_url"] = related_url
    return normalized
