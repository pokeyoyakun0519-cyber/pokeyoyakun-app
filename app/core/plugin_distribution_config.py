from __future__ import annotations

import json
from typing import Any

from core.runtime_paths import app_root


DEFAULT_CONFIG = {
    "enabled": False,
    "manifest_url": "http://127.0.0.1:8780/plugins/manifest.json",
    "check_on_startup": True,
    "timeout_seconds": 15,
}


class PluginDistributionConfig:
    def __init__(self):
        self.path = (
            app_root()
            / "config"
            / "plugin_distribution_settings.json"
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

        result["enabled"] = bool(
            result.get("enabled", False)
        )
        result["check_on_startup"] = bool(
            result.get("check_on_startup", True)
        )
        result["manifest_url"] = str(
            result.get(
                "manifest_url",
                DEFAULT_CONFIG["manifest_url"],
            )
        ).strip()
        result["timeout_seconds"] = max(
            3,
            min(
                60,
                int(
                    result.get(
                        "timeout_seconds",
                        15,
                    )
                ),
            ),
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
