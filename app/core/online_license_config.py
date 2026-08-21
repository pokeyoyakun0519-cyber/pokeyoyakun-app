from __future__ import annotations

import ipaddress
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from core.release_config import ReleaseConfig
from core.runtime_paths import app_root


ENDPOINT_PATH = (
    Path(__file__).resolve().parent
    / "online_license_endpoint.json"
)
PRODUCTION_PUBLIC_URL = "https://api.pokeyoyakun.com"
UNCONFIGURED_PUBLIC_URL = ""


def load_bundled_public_url(
    path: Path = ENDPOINT_PATH,
) -> str:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        value = str(data.get("public_url", "")).strip().rstrip("/")
    except (OSError, AttributeError, json.JSONDecodeError):
        return UNCONFIGURED_PUBLIC_URL
    return value or UNCONFIGURED_PUBLIC_URL


def validate_public_server_url(url: str) -> str:
    value = str(url).strip().rstrip("/")
    try:
        parsed = urlsplit(value)
        hostname = str(parsed.hostname or "").lower()
        port = parsed.port
    except ValueError as error:
        raise ValueError("ライセンスサーバーURLが不正です。") from error

    if parsed.scheme.lower() != "https":
        raise ValueError("ライセンスサーバーはHTTPS URLだけ使用できます。")
    if not hostname or parsed.username or parsed.password:
        raise ValueError("固定ホスト名を含むHTTPS URLを設定してください。")
    if port not in (None, 443):
        raise ValueError("公開ライセンスAPIはHTTPS標準ポート443だけ使用できます。")
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise ValueError("ライセンスサーバーURLにパスやクエリを含められません。")

    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        raise ValueError("IPアドレスではなくDDNSまたは独自ドメインを設定してください。")

    if hostname.endswith((".invalid", ".example")) or hostname in {
        "example.com",
        "license.example.com",
    }:
        raise ValueError("本番用の固定ホスト名が未設定です。")
    return value


def is_public_endpoint_configured(url: str) -> bool:
    try:
        validate_public_server_url(url)
    except ValueError:
        return False
    return True


def _default_config() -> dict[str, Any]:
    server_url = load_bundled_public_url()
    return {
        "schema_version": 3,
        "enabled": is_public_endpoint_configured(server_url),
        "server_url": server_url,
        "timeout_seconds": 10,
        "offline_grace_hours": 0,
    }


DEFAULT_CONFIG = _default_config()


class OnlineLicenseConfig:
    def __init__(self, release_config: ReleaseConfig | None = None):
        self.release_config = release_config or ReleaseConfig()
        self.path = (
            app_root()
            / "config"
            / "online_license_settings.json"
        )

    def load(self) -> dict[str, Any]:
        defaults = _default_config()
        data: object = {}
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                data = {}

        result = dict(defaults)
        if isinstance(data, dict):
            result.update(data)

        if self.release_config.is_development:
            server_url = str(
                result.get("server_url", defaults["server_url"])
            ).strip().rstrip("/")
        else:
            # User Editionの配布版は同梱した公開HTTPS先だけを使用する。
            server_url = str(defaults["server_url"])

        endpoint_configured = is_public_endpoint_configured(server_url)
        result["server_url"] = server_url
        result["endpoint_configured"] = endpoint_configured
        if self.release_config.is_development:
            result["enabled"] = bool(
                result.get("enabled", defaults["enabled"])
            ) and endpoint_configured
        else:
            # User Editionでは、旧版が保存したenabled=falseや開発用URLを
            # 本番固定endpointへ合成しない。同梱endpointの検証結果を正とする。
            result["enabled"] = endpoint_configured
        result["configuration_error"] = (
            ""
            if endpoint_configured
            else "本番用HTTPSライセンスホスト名が未設定、または安全でないURLです。"
        )
        result["timeout_seconds"] = self._bounded_int(
            result.get("timeout_seconds"),
            default=10,
            minimum=3,
            maximum=60,
        )
        result["offline_grace_hours"] = 0
        result["schema_version"] = 3
        return result

    def save(self, config: dict[str, Any]) -> None:
        value = _default_config()
        value.update(config)
        value.pop("endpoint_configured", None)
        value.pop("configuration_error", None)
        value["schema_version"] = 3

        if self.release_config.is_development:
            server_url = str(value.get("server_url", ""))
            if bool(value.get("enabled", False)):
                server_url = validate_public_server_url(server_url)
            else:
                server_url = server_url.strip().rstrip("/")
        else:
            server_url = load_bundled_public_url()
            value["enabled"] = is_public_endpoint_configured(server_url)

        value["server_url"] = server_url
        value["timeout_seconds"] = self._bounded_int(
            value.get("timeout_seconds"),
            default=10,
            minimum=3,
            maximum=60,
        )
        value["offline_grace_hours"] = 0
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def normalize_server_url(value: str) -> str:
        return value.strip().rstrip("/")

    @classmethod
    def validate_server_url(cls, value: str) -> tuple[bool, str]:
        try:
            validate_public_server_url(value)
        except ValueError as error:
            return False, str(error)
        return True, "設定可能なHTTPS URLです。"

    @staticmethod
    def _bounded_int(
        value: Any,
        *,
        default: int,
        minimum: int,
        maximum: int,
    ) -> int:
        try:
            number = int(value)
        except (TypeError, ValueError):
            number = default
        return max(minimum, min(maximum, number))
