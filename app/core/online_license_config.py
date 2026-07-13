from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

from core.runtime_paths import app_root


DEFAULT_CONFIG = {
    "schema_version": 2,
    "enabled": True,
    "server_url": "http://180.24.86.226:8765",
    "timeout_seconds": 10,
    "offline_grace_hours": 72,
}

LEGACY_LOCAL_URLS = {
    "http://127.0.0.1:8765",
    "http://localhost:8765",
}


class OnlineLicenseConfig:
    def __init__(self):
        self.path = (
            app_root()
            / "config"
            / "online_license_settings.json"
        )

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return dict(DEFAULT_CONFIG)

        try:
            data = json.loads(
                self.path.read_text(
                    encoding="utf-8"
                )
            )
        except (
            OSError,
            json.JSONDecodeError,
        ):
            return dict(DEFAULT_CONFIG)

        result = dict(DEFAULT_CONFIG)
        if isinstance(data, dict):
            result.update(data)

        # Ver.1.23.0 User Editionの初期設定は無効かつlocalhostだった。
        # 認証前には設定画面へ進めないため、未移行の初期値だけを
        # 公開サーバー向けの新しい既定値へ置き換える。
        if (
            isinstance(data, dict)
            and "schema_version" not in data
            and not bool(data.get("enabled", False))
            and self.normalize_server_url(
                str(data.get("server_url", ""))
            ) in LEGACY_LOCAL_URLS
        ):
            result.update(DEFAULT_CONFIG)

        result["server_url"] = self.normalize_server_url(
            str(
                result.get(
                    "server_url",
                    DEFAULT_CONFIG["server_url"],
                )
            )
        )
        result["timeout_seconds"] = self._bounded_int(
            result.get("timeout_seconds"),
            default=10,
            minimum=3,
            maximum=60,
        )
        result["offline_grace_hours"] = self._bounded_int(
            result.get("offline_grace_hours"),
            default=72,
            minimum=0,
            maximum=720,
        )
        result["enabled"] = bool(
            result.get("enabled", True)
        )
        result["schema_version"] = 2
        return result

    def save(
        self,
        config: dict[str, Any],
    ) -> None:
        value = dict(DEFAULT_CONFIG)
        value.update(config)
        value["schema_version"] = 2
        value["server_url"] = self.normalize_server_url(
            str(value.get("server_url", ""))
        )

        valid, message = self.validate_server_url(
            value["server_url"]
        )
        if not valid:
            raise ValueError(message)

        value["timeout_seconds"] = self._bounded_int(
            value.get("timeout_seconds"),
            default=10,
            minimum=3,
            maximum=60,
        )
        value["offline_grace_hours"] = self._bounded_int(
            value.get("offline_grace_hours"),
            default=72,
            minimum=0,
            maximum=720,
        )
        self.path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        self.path.write_text(
            json.dumps(
                value,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    @staticmethod
    def normalize_server_url(value: str) -> str:
        return value.strip().rstrip("/")

    @classmethod
    def validate_server_url(
        cls,
        value: str,
    ) -> tuple[bool, str]:
        url = cls.normalize_server_url(value)
        if not url:
            return False, "ライセンスサーバーURLを入力してください。"

        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return False, "URLは http:// または https:// から入力してください。"
        if not parsed.hostname:
            return False, "ライセンスサーバーURLのホスト名またはIPアドレスが不正です。"
        if parsed.username or parsed.password:
            return False, "URLにユーザー名やパスワードを含めることはできません。"
        if parsed.query or parsed.fragment:
            return False, "URLにクエリ文字列や # を含めることはできません。"

        try:
            port = parsed.port
        except ValueError:
            return False, "ポート番号が不正です。"

        if port is not None and not 1 <= port <= 65535:
            return False, "ポート番号は1～65535で指定してください。"

        return True, "設定可能なURLです。"

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
