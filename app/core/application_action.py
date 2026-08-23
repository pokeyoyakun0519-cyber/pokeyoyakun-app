from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from core.safe_product_url import validate_product_url
from core.restricted_application import UNVERIFIED_RESTRICTED, verification_bucket


APPLICATION_PATH_TYPES = {
    "DIRECT_APPLICATION",
    "OFFICIAL_DETAIL",
    "APP_REQUIRED",
    "SNS_REQUIRED",
    "STORE_ONLY",
    "UNKNOWN",
}
_EXTERNAL_APPLICATION_HOSTS = {
    "livepocket.jp", "t.livepocket.jp", "miniapp.line.me", "select-type.com",
}
_TRUSTED_DISCOVERY_HOSTS = {"nyuka-now.com", "www.nyuka-now.com"}


def application_action(row: dict[str, Any]) -> dict[str, Any]:
    """Return a safe, user-facing action without treating every URL as a form."""
    path_type = _path_type(row)
    label, guidance = {
        "DIRECT_APPLICATION": ("応募ページを開く", ""),
        "OFFICIAL_DETAIL": ("公式詳細を開く", ""),
        "APP_REQUIRED": ("公式案内を開く", "応募は公式アプリが必要"),
        "SNS_REQUIRED": ("公式案内を開く", "応募には公式SNSの確認が必要"),
        "STORE_ONLY": ("店頭受付", "店頭での受付です"),
        "UNKNOWN": ("公式情報を開く", "応募方法を公式情報で確認してください"),
    }[path_type]

    candidates = _candidate_urls(row, path_type)
    if path_type == "UNKNOWN" and not candidates:
        label = "応募ページを開く"
    target = next((url for url in candidates if safe_application_action_url(url, row)), "")
    enabled = bool(target) and not bool(row.get("is_candidate"))
    if verification_bucket(row.get("verification_status")) == UNVERIFIED_RESTRICTED:
        official = str(row.get("official_detail_url") or "").strip()
        discovery = str(row.get("discovery_source_url") or row.get("site_url") or "").strip()
        target = official or discovery
        if target and safe_application_action_url(target, row):
            enabled = True
        if official:
            label = "公式情報を確認する"
            guidance = "応募前に公式ページで期間・商品・条件をご確認ください"
        else:
            label = "情報元を確認する"
            guidance = "公式情報ではありません。店舗公式ページも必ずご確認ください"
    elif row.get("is_candidate"):
        guidance = "公式確認が完了するまで応募操作は利用できません"
    return {
        "application_path_type": path_type,
        "application_action_label": label,
        "application_action_url": target,
        "application_action_enabled": enabled,
        "application_action_guidance": guidance,
    }


def _path_type(row: dict[str, Any]) -> str:
    explicit = str(
        row.get("application_path_type") or row.get("application_path") or ""
    ).strip().upper()
    if explicit in APPLICATION_PATH_TYPES:
        return explicit

    method = str(row.get("application_method") or "").casefold()
    if (
        str(row.get("site_key") or "").casefold() == "otakarasouko"
        and _evidence_has_source_type(row.get("evidence"), "OFFICIAL_STORE_PAGE")
    ):
        # Phase1 Test2 data predates the explicit path field.  Its verified
        # Otakarasouko URL is an announcement for an app-only application.
        return "APP_REQUIRED"
    if "アプリ" in method or " app" in f" {method}":
        return "APP_REQUIRED"
    if any(token in method for token in ("sns", "公式x", "instagram")):
        return "SNS_REQUIRED"
    if any(token in method for token in ("店頭", "店舗受付", "loppi")) and not row.get(
        "application_url"
    ):
        return "STORE_ONLY"

    application_url = str(row.get("application_url") or "").strip()
    if application_url:
        return "DIRECT_APPLICATION"
    if row.get("official_detail_url") or row.get("site_url"):
        return "OFFICIAL_DETAIL"
    return "UNKNOWN"


def _candidate_urls(row: dict[str, Any], path_type: str) -> list[str]:
    if path_type == "DIRECT_APPLICATION":
        keys = ("application_url",)
    elif path_type in {"APP_REQUIRED", "SNS_REQUIRED", "STORE_ONLY"}:
        keys = ("official_detail_url", "site_url", "related_url", "product_url")
    elif path_type == "OFFICIAL_DETAIL":
        keys = ("official_detail_url", "application_url", "site_url", "related_url", "product_url")
    else:
        keys = ("official_detail_url", "application_url", "site_url", "related_url", "product_url")
    output: list[str] = []
    for key in keys:
        value = str(row.get(key) or "").strip()
        if value and value not in output:
            output.append(value)
    return output


def safe_application_action_url(url: str, row: dict[str, Any]) -> bool:
    try:
        validate_product_url(url)
        return True
    except ValueError:
        pass
    if (
        verification_bucket(row.get("verification_status")) == UNVERIFIED_RESTRICTED
        and url == str(row.get("official_detail_url") or "").strip()
        and _host(url) in _EXTERNAL_APPLICATION_HOSTS
    ):
        # Opening a known application-provider page for manual verification is
        # not confirmation and does not enable any in-app application action.
        return True
    if (
        verification_bucket(row.get("verification_status")) == UNVERIFIED_RESTRICTED
        and url == str(row.get("discovery_source_url") or "").strip()
        and _host(url) in _TRUSTED_DISCOVERY_HOSTS
    ):
        return True
    if _host(url) not in _EXTERNAL_APPLICATION_HOSTS:
        return False
    if str(row.get("verification_status") or "").strip().casefold() != "confirmed":
        return False
    return _has_verified_external_evidence(url, row.get("evidence"))


def _has_verified_external_evidence(url: str, evidence: Any) -> bool:
    values = evidence if isinstance(evidence, list) else [evidence]
    for item in values:
        if not isinstance(item, dict):
            continue
        source_type = str(item.get("source_type") or "").strip().upper()
        status = str(item.get("verification_status") or "").strip().casefold()
        try:
            trust = int(item.get("trust") or 0)
        except (TypeError, ValueError):
            trust = 0
        source_url = str(item.get("source_url") or item.get("url") or "").strip()
        extracted = item.get("extracted_fields")
        extracted_url = str(
            extracted.get("application_url") if isinstance(extracted, dict) else ""
        ).strip()
        if (
            source_type in {
                "OFFICIAL_APPLICATION_PAGE", "OFFICIAL_APPLICATION_FORM",
                "OFFICIAL_STORE_PAGE",
            }
            and status == "confirmed"
            and trust >= 80
            and url in {source_url, extracted_url}
        ):
            return True
    return False


def _evidence_has_source_type(evidence: Any, expected: str) -> bool:
    values = evidence if isinstance(evidence, list) else [evidence]
    return any(
        isinstance(item, dict)
        and str(item.get("source_type") or "").strip().upper() == expected
        and str(item.get("verification_status") or "").strip().casefold() == "confirmed"
        for item in values
    )


def _host(url: str) -> str:
    try:
        parsed = urlsplit(str(url or ""))
        if parsed.scheme.casefold() != "https" or parsed.username or parsed.password:
            return ""
        if parsed.port not in (None, 443):
            return ""
        return (parsed.hostname or "").casefold()
    except ValueError:
        return ""
