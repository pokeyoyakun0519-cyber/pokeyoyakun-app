from __future__ import annotations

import ipaddress
import json
import re
import socket
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlsplit

from core.version import APP_VERSION


FEEDBACK_API_ORIGIN = "https://pokeyoyakun.duckdns.org"
MAX_SUBJECT_LENGTH = 160
MAX_BODY_LENGTH = 10_000
MAX_EMAIL_LENGTH = 254
MAX_STORE_NAME_LENGTH = 200
MAX_URL_LENGTH = 2_048
MAX_NOTES_LENGTH = 5_000
MAX_CLIENT_VERSION_LENGTH = 64

TCG_LABELS = {
    "pokemon": "ポケモンカード",
    "onepiece": "ワンピースカード",
    "yugioh": "遊戯王OCG",
    "gundam": "ガンダムカード",
    "other": "その他",
}
FEEDBACK_TYPES = {
    "question": "other",
    "bug": "bug",
    "request": "request",
    "other": "other",
}
SALES_SCOPES = {"reservation", "lottery", "both"}
RECEIPT_PATTERN = re.compile(r"^(FB|SR)-\d{8}-[0-9A-F]{12}$")
EMAIL_PATTERN = re.compile(r"^[^\s@]{1,64}@[^\s@]{1,190}$")
SENSITIVE_PATTERN = re.compile(
    r"(?i)(?:license[_ -]?key|ライセンスキー|access[_ -]?token|"
    r"refresh[_ -]?token|認証トークン|端末ID|device[_ -]?id|"
    r"pc[_ -]?code)\s*[:=]\s*\S+"
)


class FeedbackValidationError(ValueError):
    pass


class SensitiveInputError(FeedbackValidationError):
    pass


class FeedbackApiError(RuntimeError):
    pass


def _clean_required(value: str, label: str, maximum: int) -> str:
    cleaned = str(value).strip()
    if not cleaned:
        raise FeedbackValidationError(f"{label}を入力してください。")
    if len(cleaned) > maximum:
        raise FeedbackValidationError(f"{label}は{maximum:,}文字以内で入力してください。")
    return cleaned


def _clean_optional(value: str, label: str, maximum: int) -> str:
    cleaned = str(value).strip()
    if len(cleaned) > maximum:
        raise FeedbackValidationError(f"{label}は{maximum:,}文字以内で入力してください。")
    return cleaned


def _validate_tcg_keys(values: list[str], *, required: bool) -> list[str]:
    keys: list[str] = []
    for value in values:
        key = str(value).strip().lower()
        if key not in TCG_LABELS:
            raise FeedbackValidationError("未対応のTCGが選択されています。")
        if key not in keys:
            keys.append(key)
    if required and not keys:
        raise FeedbackValidationError("対象TCGを1件以上選択してください。")
    if len(keys) > 5:
        raise FeedbackValidationError("対象TCGは5件以内で選択してください。")
    return keys


def validate_external_url(value: str, label: str) -> str:
    cleaned = _clean_optional(value, label, MAX_URL_LENGTH)
    if not cleaned:
        return ""
    try:
        parsed = urlsplit(cleaned)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            raise ValueError
        _ = parsed.port
        if parsed.username is not None or parsed.password is not None:
            raise ValueError
        hostname = parsed.hostname.rstrip(".").casefold()
        if hostname == "localhost" or hostname.endswith(".localhost"):
            raise ValueError
        try:
            address = ipaddress.ip_address(hostname)
        except ValueError:
            address = None
        if address and not address.is_global:
            raise ValueError
    except (ValueError, UnicodeError):
        raise FeedbackValidationError(
            f"{label}には外部のhttp/https URLを入力してください。"
        ) from None
    return cleaned


def build_feedback_payload(
    *,
    feedback_type: str,
    subject: str,
    body: str,
    tcg_keys: list[str],
    reply_requested: bool,
    reply_email: str,
) -> dict[str, Any]:
    api_type = FEEDBACK_TYPES.get(str(feedback_type))
    if api_type is None:
        raise FeedbackValidationError("投稿種別が不正です。")
    clean_subject = _clean_required(subject, "件名", MAX_SUBJECT_LENGTH)
    clean_body = _clean_required(body, "本文", MAX_BODY_LENGTH)
    if SENSITIVE_PATTERN.search(clean_subject + "\n" + clean_body):
        raise SensitiveInputError(
            "ライセンスキー、認証トークン、端末コードなどの秘密情報を削除してください。"
        )
    clean_email = _clean_optional(reply_email, "返信先メール", MAX_EMAIL_LENGTH)
    if clean_email and not EMAIL_PATTERN.fullmatch(clean_email):
        raise FeedbackValidationError("返信先メールアドレスの形式を確認してください。")
    if reply_requested and not clean_email:
        raise FeedbackValidationError("返信を希望する場合はメールアドレスを入力してください。")
    return {
        "message_type": api_type,
        "subject": clean_subject,
        "body": clean_body,
        "tcg_keys": _validate_tcg_keys(tcg_keys, required=False),
        "reply_requested": bool(reply_requested),
        "reply_email": clean_email or None,
        "client_version": APP_VERSION[:MAX_CLIENT_VERSION_LENGTH],
    }


def build_store_request_payload(
    *,
    store_name: str,
    official_url: str,
    discovery_url: str,
    tcg_keys: list[str],
    sales_scope: str,
    notes: str,
) -> dict[str, Any]:
    clean_name = _clean_required(store_name, "店舗名", MAX_STORE_NAME_LENGTH)
    clean_notes = _clean_optional(notes, "補足", MAX_NOTES_LENGTH)
    if SENSITIVE_PATTERN.search(clean_name + "\n" + clean_notes):
        raise SensitiveInputError(
            "ライセンスキー、認証トークン、端末コードなどの秘密情報を削除してください。"
        )
    if sales_scope not in SALES_SCOPES:
        raise FeedbackValidationError("予約・抽選の種別を選択してください。")
    return {
        "store_name": clean_name,
        "official_url": validate_external_url(official_url, "公式URL"),
        "discovery_url": validate_external_url(discovery_url, "情報を発見したURL"),
        "tcg_keys": _validate_tcg_keys(tcg_keys, required=True),
        "sales_scope": sales_scope,
        "notes": clean_notes,
        "client_version": APP_VERSION[:MAX_CLIENT_VERSION_LENGTH],
    }


class FeedbackHttpsRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self):
        super().__init__()
        approved = urlsplit(FEEDBACK_API_ORIGIN)
        self._approved_origin = (
            approved.scheme.lower(),
            approved.hostname,
            approved.port or 443,
        )

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        try:
            redirected = urlsplit(newurl)
            origin = (
                redirected.scheme.lower(),
                redirected.hostname,
                redirected.port or 443,
            )
        except ValueError as error:
            raise urllib.error.URLError("不正なリダイレクトを拒否しました。") from error
        if (
            redirected.scheme.lower() != "https"
            or redirected.username
            or redirected.password
            or origin != self._approved_origin
        ):
            raise urllib.error.URLError(
                "HTTPSの同一ホスト・同一ポート以外へのリダイレクトを拒否しました。"
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class FeedbackApiClient:
    def __init__(self, timeout_seconds: int = 15):
        self.timeout_seconds = max(3, min(60, int(timeout_seconds)))

    def submit_feedback(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._accepted(
            self._request("POST", "/api/v1/feedback", payload),
            "FB-",
        )

    def submit_store_request(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._accepted(
            self._request("POST", "/api/v1/store-requests", payload),
            "SR-",
        )

    def receipt_status(self, kind: str, receipt_id: str) -> dict[str, Any]:
        receipt = str(receipt_id).strip().upper()
        if not RECEIPT_PATTERN.fullmatch(receipt):
            raise FeedbackValidationError("受付番号の形式が正しくありません。")
        if kind == "店舗追加依頼":
            path = f"/api/v1/store-requests/receipts/{receipt}"
        else:
            path = f"/api/v1/feedback/receipts/{receipt}"
        result = self._request("GET", path)
        if str(result.get("receipt_id", "")) != receipt:
            raise FeedbackApiError("受付サーバーの応答に別の受付番号が含まれています。")
        return {
            key: result[key]
            for key in ("receipt_id", "status", "created_at", "updated_at")
            if key in result
        }

    @staticmethod
    def _accepted(result: dict[str, Any], prefix: str) -> dict[str, str]:
        receipt_id = str(result.get("receipt_id", "")).strip().upper()
        status = str(result.get("status", "")).strip()
        if (
            not RECEIPT_PATTERN.fullmatch(receipt_id)
            or not receipt_id.startswith(prefix)
            or not status
        ):
            raise FeedbackApiError("受付サーバーから有効な受付番号を取得できませんでした。")
        return {"receipt_id": receipt_id, "status": status}

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = FEEDBACK_API_ORIGIN + path
        body = None
        headers = {
            "Accept": "application/json",
            "User-Agent": "PokeyoyaKun/" + APP_VERSION,
        }
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        opener = urllib.request.build_opener(FeedbackHttpsRedirectHandler())
        try:
            with opener.open(request, timeout=self.timeout_seconds) as response:
                data = json.loads(response.read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as error:
            message = f"サーバーがHTTP {error.code}を返しました。"
            try:
                detail = json.loads(error.read().decode("utf-8", errors="replace"))
                message = str(detail.get("detail", message))
            except Exception:
                pass
            raise FeedbackApiError(message) from error
        except urllib.error.URLError as error:
            reason = getattr(error, "reason", error)
            if "timed out" in str(reason).lower():
                raise FeedbackApiError("接続がタイムアウトしました。時間をおいて再度お試しください。") from error
            raise FeedbackApiError(f"フィードバック受付へ接続できません: {reason}") from error
        except (TimeoutError, socket.timeout) as error:
            raise FeedbackApiError("接続がタイムアウトしました。時間をおいて再度お試しください。") from error
        except (json.JSONDecodeError, OSError) as error:
            raise FeedbackApiError("受付サーバーの応答を確認できませんでした。") from error
        if not isinstance(data, dict):
            raise FeedbackApiError("受付サーバーの応答形式が正しくありません。")
        return data
