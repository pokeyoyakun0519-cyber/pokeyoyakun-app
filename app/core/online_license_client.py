from __future__ import annotations

import json
import socket
import ssl
import urllib.error
import urllib.request
from typing import Any, Callable
from urllib.parse import urlsplit

from core.device_id import get_device_id
from core.online_license_config import (
    OnlineLicenseConfig,
    validate_public_server_url,
)
from core.online_license_token import verify_online_token
from core.secure_https import TlsConfigurationError, build_https_opener
from core.version import APP_VERSION


class HttpsOnlyRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Keep every redirect on the configured HTTPS origin."""

    def __init__(self, server_url: str):
        super().__init__()
        approved = urlsplit(validate_public_server_url(server_url))
        self._approved_origin = (
            approved.scheme.lower(),
            approved.hostname,
            approved.port or 443,
        )

    def redirect_request(
        self,
        req,
        fp,
        code,
        msg,
        headers,
        newurl,
    ):
        try:
            redirected = urlsplit(newurl)
            redirected_port = redirected.port or 443
        except ValueError as error:
            raise urllib.error.URLError(
                "不正なライセンスAPIリダイレクトを拒否しました。"
            ) from error

        redirected_origin = (
            redirected.scheme.lower(),
            redirected.hostname,
            redirected_port,
        )
        if (
            redirected.scheme.lower() != "https"
            or redirected.username
            or redirected.password
            or redirected_origin != self._approved_origin
        ):
            raise urllib.error.URLError(
                "HTTPSの同一ホスト以外へのリダイレクトを拒否しました。"
            )
        return super().redirect_request(
            req,
            fp,
            code,
            msg,
            headers,
            newurl,
        )


class OnlineLicenseClient:
    def __init__(
        self,
        *,
        device_id_provider: Callable[[], str] | None = None,
    ):
        self.config_manager = OnlineLicenseConfig()
        self._device_id_provider = device_id_provider
        self.last_response_diagnostic: dict[str, Any] = {}

    def _device_id(self) -> str:
        if self._device_id_provider is not None:
            return self._device_id_provider()
        return get_device_id()

    def test_connection(self) -> tuple[bool, str]:
        config = self.config_manager.load()

        try:
            approved_server_url = validate_public_server_url(
                str(config.get("server_url", ""))
            )
        except ValueError as error:
            return False, str(error)

        url = (
            approved_server_url
            + "/health"
        )
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "PokeyoyaKun/" + APP_VERSION,
            },
            method="GET",
        )

        try:
            opener = build_https_opener(
                HttpsOnlyRedirectHandler(approved_server_url)
            )
            with opener.open(
                request,
                timeout=int(config["timeout_seconds"]),
            ) as response:
                raw = response.read().decode(
                    "utf-8",
                    errors="replace",
                )
                data = json.loads(raw)
        except urllib.error.HTTPError as error:
            return (
                False,
                self._http_error_message(error, url),
            )
        except urllib.error.URLError as error:
            return False, self._friendly_connection_error(error, url)
        except TlsConfigurationError as error:
            return False, f"TLS設定エラー（接続先: {url}）: {error}"
        except (TimeoutError, socket.timeout):
            return False, self._timeout_message(url)
        except json.JSONDecodeError:
            return False, "ライセンスサーバーの応答がJSON形式ではありません。"
        except OSError as error:
            return False, f"通信エラー（接続先: {url}）: {error}"

        if not isinstance(data, dict):
            return False, "ライセンスサーバーの応答形式が正しくありません。"
        if bool(data.get("ok", False)):
            return True, "ライセンスサーバーへ接続できました。"
        return False, str(
            data.get(
                "message",
                "サーバーの準備が完了していません。",
            )
        )

    def activate(
        self,
        license_key: str,
    ) -> tuple[bool, str, dict[str, Any]]:
        key = license_key.strip().upper()
        if not key:
            return False, "ライセンスキーを入力してください。", {}

        ok, message, data, _ = self._request_and_cache(
            "/api/v1/licenses/activate",
            {
                "license_key": key,
                "device_id": self._device_id(),
                "app_version": APP_VERSION,
            },
        )
        return ok, message, data

    def request_subscription_code(
        self,
        email: str,
    ) -> tuple[bool, str, dict[str, Any]]:
        normalized_email = email.strip().casefold()
        if not normalized_email or "@" not in normalized_email:
            return False, "メールアドレスを確認してください。", {}

        ok, message, data, _ = self._post_json(
            "/api/v1/subscriptions/auth/request-code",
            {
                "email": normalized_email,
                "app_version": APP_VERSION,
            },
        )
        return ok, message, data

    def activate_subscription(
        self,
        email: str,
        code: str,
    ) -> tuple[bool, str, dict[str, Any]]:
        normalized_email = email.strip().casefold()
        normalized_code = code.strip()
        if not normalized_email or "@" not in normalized_email:
            return False, "メールアドレスを確認してください。", {}
        if len(normalized_code) != 6 or not normalized_code.isdecimal():
            return False, "6桁の認証コードを入力してください。", {}

        device_id = self._device_id()
        ok, message, data, _ = self._post_json(
            "/api/v1/subscriptions/auth/verify-code",
            {
                "email": normalized_email,
                "code": normalized_code,
                "device_id": device_id,
                "app_version": APP_VERSION,
            },
        )
        if not ok:
            return ok, message, data

        internal_key = str(data.get("license_key", "")).strip().upper()
        if not internal_key:
            return False, "自動認証用ライセンスを受信できませんでした。", {}
        token_ok, token_message, _claims = verify_online_token(
            data.get("license_token"),
            internal_key,
            device_id,
        )
        if not token_ok:
            self.last_response_diagnostic.update(
                category="signature_error",
                message=token_message,
                token_present=bool(data.get("license_token")),
                token_key_id=self._token_key_id(data.get("license_token")),
            )
            return (
                False,
                "サーバー署名を検証できません: " + token_message,
                {},
            )
        return True, message, data

    def verify(
        self,
        license_key: str,
    ) -> tuple[bool, str, dict[str, Any]]:
        key = license_key.strip().upper()
        if not key:
            return False, "ライセンスキーを入力してください。", {}

        ok, message, data, _ = self._request_and_cache(
            "/api/v1/licenses/verify",
            {
                "license_key": key,
                "device_id": self._device_id(),
                "app_version": APP_VERSION,
            },
        )
        return ok, message, data

    def deactivate(
        self,
        license_key: str,
    ) -> tuple[bool, str, dict[str, Any]]:
        ok, message, data, _ = self._post_json(
            "/api/v1/licenses/deactivate",
            {
                "license_key": license_key.strip().upper(),
                "device_id": self._device_id(),
            },
        )
        return ok, message, data

    def _request_and_cache(
        self,
        path: str,
        payload: dict[str, Any],
    ) -> tuple[bool, str, dict[str, Any], bool]:
        ok, message, data, server_unavailable = self._post_json(
            path,
            payload,
        )
        if ok:
            token_ok, token_message, _claims = verify_online_token(
                data.get("license_token"),
                str(payload.get("license_key", "")),
                str(payload.get("device_id", "")),
            )
            if not token_ok:
                self.last_response_diagnostic.update(
                    {
                        "category": "signature_error",
                        "message": token_message,
                        "token_present": bool(data.get("license_token")),
                        "token_key_id": self._token_key_id(
                            data.get("license_token")
                        ),
                    }
                )
                return (
                    False,
                    "サーバー署名を検証できません: " + token_message,
                    {},
                    False,
                )
        return ok, message, data, server_unavailable

    def _post_json(
        self,
        path: str,
        payload: dict[str, Any],
    ) -> tuple[bool, str, dict[str, Any], bool]:
        config = self.config_manager.load()
        self.last_response_diagnostic = {
            "path": path,
            "category": "not_sent",
        }

        if not config.get("enabled", False):
            self.last_response_diagnostic.update(
                category="configuration_error",
                message="オンラインライセンスが無効です。",
            )
            return (
                False,
                "オンラインライセンスが無効です。設定を確認してください。",
                {},
                False,
            )

        try:
            approved_server_url = validate_public_server_url(
                str(config.get("server_url", ""))
            )
        except ValueError as error:
            self.last_response_diagnostic.update(
                category="configuration_error",
                message=str(error),
            )
            return False, str(error), {}, False

        url = (
            approved_server_url
            + path
        )
        self.last_response_diagnostic["url"] = url
        body = json.dumps(
            payload,
            ensure_ascii=False,
        ).encode("utf-8")

        request = urllib.request.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "User-Agent": (
                    "PokeyoyaKun/"
                    + APP_VERSION
                ),
            },
            method="POST",
        )

        try:
            opener = build_https_opener(
                HttpsOnlyRedirectHandler(approved_server_url)
            )
            with opener.open(
                request,
                timeout=int(
                    config["timeout_seconds"]
                ),
            ) as response:
                raw = response.read().decode(
                    "utf-8",
                    errors="replace",
                )
                data = json.loads(raw)
                http_status = int(getattr(response, "status", 200) or 200)
        except urllib.error.HTTPError as error:
            raw = error.read(4096).decode("utf-8", errors="replace")
            data, json_error = self._decode_response_body(raw)
            secrets_to_hide = self._payload_secrets(payload)
            safe_body = self._sanitize_response(
                data if data is not None else raw,
                secrets=secrets_to_hide,
            )
            message = self._message_from_response(data)
            message = self._redact_text(message, secrets_to_hide)
            self.last_response_diagnostic.update(
                http_status=int(error.code),
                category="http_error" if not json_error else "http_json_error",
                response_json=safe_body,
                message=" ".join(message.split())[:300],
            )
            return (
                False,
                self._format_http_error(error.code, url, message),
                {},
                False,
            )
        except urllib.error.URLError as error:
            message = self._friendly_connection_error(error, url)
            self.last_response_diagnostic.update(
                category=self._url_error_category(error),
                message=message,
            )
            return (
                False,
                message,
                {},
                True,
            )
        except TlsConfigurationError as error:
            self.last_response_diagnostic.update(
                category="tls_error",
                message=str(error),
            )
            return False, f"TLS設定エラー（接続先: {url}）: {error}", {}, True
        except (TimeoutError, socket.timeout):
            self.last_response_diagnostic.update(
                category="timeout",
                message=self._timeout_message(url),
            )
            return False, self._timeout_message(url), {}, True
        except json.JSONDecodeError as error:
            self.last_response_diagnostic.update(
                http_status=locals().get("http_status", 200),
                category="json_error",
                response_json=self._sanitize_response(
                    locals().get("raw", ""),
                    secrets=self._payload_secrets(payload),
                ),
                message=str(error),
            )
            return (
                False,
                "ライセンスサーバーの応答がJSON形式ではありません。",
                {},
                False,
            )
        except OSError as error:
            self.last_response_diagnostic.update(
                category="io_error",
                message=str(error),
            )
            return (
                False,
                f"通信エラー（接続先: {url}）: {error}",
                {},
                True,
            )

        if not isinstance(data, dict):
            self.last_response_diagnostic.update(
                http_status=http_status,
                category="invalid_response",
                response_json=self._sanitize_response(
                    data,
                    secrets=self._payload_secrets(payload),
                ),
                message="JSONオブジェクトではありません。",
            )
            return (
                False,
                "ライセンスサーバーの応答形式が正しくありません。",
                {},
                False,
            )

        ok = bool(data.get("ok", False))
        message = str(
            data.get(
                "message",
                "認証結果を取得しました。",
            )
        )
        secrets_to_hide = self._payload_secrets(payload)
        message = self._redact_text(message, secrets_to_hide)
        self.last_response_diagnostic.update(
            http_status=http_status,
            category="ok" if ok else "api_rejected",
            response_json=self._sanitize_response(
                data,
                secrets=secrets_to_hide,
            ),
            message=" ".join(message.split())[:300],
            token_present=bool(data.get("license_token")),
            token_key_id=self._token_key_id(data.get("license_token")),
        )
        return ok, message, data, False

    @classmethod
    def _sanitize_response(
        cls,
        value: Any,
        path: tuple[str, ...] = (),
        *,
        secrets: tuple[str, ...] = (),
    ) -> Any:
        """Keep response structure for diagnostics without secrets or identifiers."""
        if isinstance(value, dict):
            sanitized = {}
            for key, item in value.items():
                key_text = str(key)
                lowered = key_text.lower()
                item_path = path + (lowered,)
                if lowered in {
                    "license_key",
                    "device_id",
                    "email",
                    "code",
                    "stripe_customer_id",
                    "stripe_subscription_id",
                    "customer_id",
                    "subscription_id",
                }:
                    sanitized[key_text] = "[非表示]"
                elif lowered == "value" and "signature" in path:
                    sanitized[key_text] = "[署名値非表示]"
                else:
                    sanitized[key_text] = cls._sanitize_response(
                        item,
                        item_path,
                        secrets=secrets,
                    )
            return sanitized
        if isinstance(value, list):
            return [
                cls._sanitize_response(item, path, secrets=secrets)
                for item in value
            ]
        if isinstance(value, str):
            return cls._redact_text(value, secrets)[:1000]
        return value

    @staticmethod
    def _payload_secrets(payload: dict[str, Any]) -> tuple[str, ...]:
        return tuple(
            str(payload.get(key, ""))
            for key in ("license_key", "email", "code", "device_id")
            if str(payload.get(key, ""))
        )

    @staticmethod
    def _redact_text(value: str, secrets: tuple[str, ...]) -> str:
        output = str(value)
        for secret in secrets:
            output = output.replace(secret, "[機密情報非表示]")
        return output

    @staticmethod
    def _token_key_id(token: Any) -> str:
        if not isinstance(token, dict):
            return ""
        signature = token.get("signature")
        if not isinstance(signature, dict):
            return ""
        return str(signature.get("key_id", ""))

    @staticmethod
    def _decode_response_body(raw: str) -> tuple[Any | None, bool]:
        try:
            return json.loads(raw), False
        except (TypeError, json.JSONDecodeError):
            return None, True

    @staticmethod
    def _message_from_response(data: Any) -> str:
        if not isinstance(data, dict):
            return ""
        return str(data.get("message") or data.get("detail") or data.get("error") or "")

    @classmethod
    def _format_http_error(cls, code: int, url: str, message: str) -> str:
        message = " ".join(message.split())[:300]
        suffix = f" サーバー応答: {message}" if message else ""
        return f"HTTP {code}（接続先: {url}）。{suffix}".rstrip()

    @staticmethod
    def _url_error_category(error: urllib.error.URLError) -> str:
        reason = getattr(error, "reason", error)
        text = str(reason).lower()
        if isinstance(reason, (TimeoutError, socket.timeout)) or "timed out" in text:
            return "timeout"
        if isinstance(reason, ssl.SSLCertVerificationError) or "certificate" in text:
            return "tls_error"
        if isinstance(reason, socket.gaierror) or "getaddrinfo" in text:
            return "dns_error"
        return "connection_error"

    @classmethod
    def _friendly_connection_error(
        cls,
        error: urllib.error.URLError,
        url: str,
    ) -> str:
        reason = getattr(error, "reason", error)
        text = str(reason).lower()
        if isinstance(reason, (TimeoutError, socket.timeout)) or (
            "timed out" in text
        ):
            return cls._timeout_message(url)
        if isinstance(reason, ssl.SSLCertVerificationError) or any(
            token in text
            for token in (
                "certificate verify failed",
                "certificate_verify_failed",
                "hostname mismatch",
                "ssl: certificate",
            )
        ):
            return (
                f"TLS証明書を検証できませんでした（接続先: {url}）。"
                "PCの日付と証明書チェーンを確認してください。"
            )
        if isinstance(reason, socket.gaierror) or any(
            token in text
            for token in (
                "getaddrinfo",
                "name or service not known",
                "nodename nor servname",
                "no such host is known",
            )
        ):
            return (
                f"DNSでサーバー名を解決できません（接続先: {url}）。"
                "インターネット接続とDNS設定を確認してください。"
            )
        if "refused" in text:
            return (
                f"接続が拒否されました（接続先: {url}）。サーバーが"
                "起動しているか確認してください。"
            )
        return f"ライセンスAPIへ接続できません（接続先: {url}）: {reason}"

    @staticmethod
    def _timeout_message(url: str) -> str:
        return (
            f"接続がタイムアウトしました（接続先: {url}）。"
            "ネットワーク、DNS、サーバーのHTTPS 443番ポートを確認してください。"
        )

    @classmethod
    def _http_error_message(
        cls,
        error: urllib.error.HTTPError,
        url: str,
        *,
        secret: str = "",
    ) -> str:
        message = ""
        try:
            payload = json.loads(
                error.read(4096).decode("utf-8", errors="replace")
            )
            if isinstance(payload, dict):
                message = str(
                    payload.get("message")
                    or payload.get("detail")
                    or payload.get("error")
                    or ""
                )
        except (OSError, ValueError, json.JSONDecodeError):
            message = ""
        if secret:
            message = message.replace(secret, "[ライセンスキー非表示]")
        message = " ".join(message.split())[:300]
        return cls._format_http_error(error.code, url, message)
