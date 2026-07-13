from __future__ import annotations

import json
from typing import Any

from core.runtime_paths import app_root


class RetailPluginState:
    def __init__(self):
        self.path = (
            app_root()
            / "config"
            / "retail_plugin_state.json"
        )

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {
                "disabled_ids": [],
            }

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
            return {
                "disabled_ids": [],
            }

        if not isinstance(data, dict):
            return {
                "disabled_ids": [],
            }

        disabled = data.get(
            "disabled_ids",
            [],
        )
        if not isinstance(disabled, list):
            disabled = []

        return {
            "disabled_ids": sorted(
                {
                    str(item)
                    for item in disabled
                    if str(item).strip()
                }
            ),
        }

    def is_enabled(
        self,
        plugin_id: str,
        default: bool = True,
    ) -> bool:
        if not default:
            return False

        disabled = set(
            self.load().get(
                "disabled_ids",
                [],
            )
        )
        return plugin_id not in disabled

    def set_enabled(
        self,
        plugin_id: str,
        enabled: bool,
    ) -> None:
        state = self.load()
        disabled = set(
            state.get(
                "disabled_ids",
                [],
            )
        )

        if enabled:
            disabled.discard(plugin_id)
        else:
            disabled.add(plugin_id)

        self.path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        self.path.write_text(
            json.dumps(
                {
                    "disabled_ids": sorted(
                        disabled
                    ),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
