from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from typing import Any

from core.device_id import get_device_id
from core.online_license_config import OnlineLicenseConfig
from core.version import APP_VERSION


class OnlineLicenseClient:
    def __init__(self):
        self.config_manager = OnlineLicenseConfig()

    def test_connection(
        self,
        server_url: str | None = None,
    ) -> tuple[bool, str]:
        config = self.config_manager.load()
        if server_url is not None:
            config["server_url"] = server_url

        valid, message = self.config_manager.validate_server_url(
            str(config.get("server_url", ""))
        )
        if not valid:
            return False, message

        url = (
            self.config_manager.normalize_server_url(
                str(config["server_url"])
            )
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
            with urllib.request.urlopen(
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
                f"サーバーは応答しましたが、HTTP {error.code} が返されました。",
            )
        except urllib.error.URLError as error:
            return False, self._friendly_connection_error(error)
        except (TimeoutError, socket.timeout):
            return False, self._timeout_message()
        except json.JSONDecodeError:
            return False, "ライセンスサーバーの応答がJSON形式ではありません。"
        except OSError as error:
            return False, f"サーバー応答を確認できませんでした: {error}"

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
                "device_id": get_device_id(),
                "app_version": APP_VERSION,
            },
        )
        return ok, message, data

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
                "device_id": get_device_id(),
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
                "device_id": get_device_id(),
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

        return ok, message, data, server_unavailable

    def _post_json(
        self,
        path: str,
        payload: dict[str, Any],
    ) -> tuple[bool, str, dict[str, Any], bool]:
        config = self.config_manager.load()

        if not config.get("enabled", False):
            return (
                False,
                "オンラインライセンスが無効です。設定を確認してください。",
                {},
                False,
            )

        valid, message = self.config_manager.validate_server_url(
            str(config.get("server_url", ""))
        )
        if not valid:
            return False, message, {}, False

        url = (
            str(config["server_url"]).rstrip("/")
            + path
        )
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
            with urllib.request.urlopen(
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
        except urllib.error.HTTPError as error:
            try:
                data = json.loads(
                    error.read().decode(
                        "utf-8",
                        errors="replace",
                    )
                )
                message = str(
                    data.get(
                        "message",
                        data.get(
                            "detail",
                            f"HTTP {error.code}",
                        ),
                    )
                )
            except Exception:
                message = f"HTTP {error.code}"
            return False, message, {}, False
        except urllib.error.URLError as error:
            return (
                False,
                self._friendly_connection_error(error),
                {},
                True,
            )
        except (TimeoutError, socket.timeout):
            return False, self._timeout_message(), {}, True
        except json.JSONDecodeError:
            return (
                False,
                "ライセンスサーバーの応答がJSON形式ではありません。",
                {},
                False,
            )
        except OSError as error:
            return (
                False,
                f"サーバー応答を処理できませんでした: {error}",
                {},
                True,
            )

        if not isinstance(data, dict):
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
        return ok, message, data, False

    @classmethod
    def _friendly_connection_error(
        cls,
        error: urllib.error.URLError,
    ) -> str:
        reason = getattr(error, "reason", error)
        text = str(reason).lower()
        if isinstance(reason, (TimeoutError, socket.timeout)) or (
            "timed out" in text
        ):
            return cls._timeout_message()
        if "refused" in text:
            return (
                "接続が拒否されました。ライセンスサーバーが"
                "起動しているか確認してください。"
            )
        if "getaddrinfo" in text or "name or service not known" in text:
            return (
                "サーバー名を解決できません。URLまたは"
                "インターネット接続を確認してください。"
            )
        return f"ライセンスサーバーへ接続できません: {reason}"

    @staticmethod
    def _timeout_message() -> str:
        return (
            "接続がタイムアウトしました。サーバー起動・"
            "ポート開放・URLを確認してください。"
        )
