from __future__ import annotations

import json
from typing import Any

from core.runtime_paths import app_root


DEFAULT_CONFIG = {
    "enabled": False,
    "server_url": "http://127.0.0.1:8765",
    "timeout_seconds": 10,
    "offline_grace_hours": 72,
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

        result["server_url"] = str(
            result.get(
                "server_url",
                DEFAULT_CONFIG["server_url"],
            )
        ).rstrip("/")
        result["timeout_seconds"] = max(
            3,
            min(
                60,
                int(
                    result.get(
                        "timeout_seconds",
                        10,
                    )
                ),
            ),
        )
        result["offline_grace_hours"] = max(
            0,
            min(
                720,
                int(
                    result.get(
                        "offline_grace_hours",
                        72,
                    )
                ),
            ),
        )
        result["enabled"] = bool(
            result.get("enabled", False)
        )
        return result

    def save(
        self,
        config: dict[str, Any],
    ) -> None:
        value = dict(DEFAULT_CONFIG)
        value.update(config)
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
