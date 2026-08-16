from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from core.config_manager import ConfigManager
from core.scheduler_config import SchedulerConfig


SETUP_VERSION = 1
SUPPORTED_TCG_KEYS = (
    "pokemon", "onepiece", "gundam", "union_arena", "yugioh",
)


class SetupCoordinator:
    """初回セットアップを検証し、既存設定へ完了時だけ反映する。"""

    def __init__(self, root: Path | None = None):
        self.config_manager = ConfigManager(root)
        self.root = self.config_manager.root
        self.scheduler_config = SchedulerConfig(self.root)

    def is_completed(self) -> bool:
        return bool(
            self.config_manager.load().get("general", {}).get("setup_completed", False)
        )

    def current_values(self) -> dict[str, Any]:
        config = self.config_manager.load()
        general = config.get("general", {})
        games = config.get("games", {})
        scheduler = self.scheduler_config.load()
        return {
            "ui_mode": "detailed" if general.get("ui_mode") == "detailed" else "simple",
            "tcg_keys": [key for key in SUPPORTED_TCG_KEYS if games.get(key, True)],
            "show_popup": bool(general.get("show_popup", True)),
            "play_notification_sound": bool(general.get("play_notification_sound", True)),
            "gmail_setup_now": False,
            "monitoring_enabled": bool(scheduler.get("enabled", False)),
            "interval_minutes": int(scheduler.get("interval_minutes", 30)),
        }

    def complete(self, values: dict[str, Any]) -> dict[str, Any]:
        normalized = self._validate(values)
        original_config = self.config_manager.load()
        original_scheduler = self.scheduler_config.load()
        updated_config = deepcopy(original_config)
        general = updated_config.setdefault("general", {})
        general.update({
            "setup_completed": True,
            "setup_version": SETUP_VERSION,
            "ui_mode": normalized["ui_mode"],
            "show_popup": normalized["show_popup"],
            "play_notification_sound": normalized["play_notification_sound"],
        })
        games = updated_config.setdefault("games", {})
        for key in SUPPORTED_TCG_KEYS:
            games[key] = key in normalized["tcg_keys"]
        updated_scheduler = dict(original_scheduler)
        updated_scheduler.update({
            "enabled": normalized["monitoring_enabled"],
            "interval_minutes": normalized["interval_minutes"],
        })

        self.config_manager.save(updated_config)
        try:
            self.scheduler_config.save(updated_scheduler)
        except Exception:
            # 2つ目の保存に失敗した場合も、既存設定を変更したままにしない。
            self.config_manager.save(original_config)
            raise
        return normalized

    @staticmethod
    def _validate(values: dict[str, Any]) -> dict[str, Any]:
        mode = str(values.get("ui_mode", "simple"))
        if mode not in {"simple", "detailed"}:
            raise ValueError("表示モードを選択してください。")
        selected = [
            key for key in SUPPORTED_TCG_KEYS
            if key in {str(value) for value in values.get("tcg_keys", [])}
        ]
        if not selected:
            raise ValueError("監視対象TCGを1つ以上選択してください。")
        try:
            interval = int(values.get("interval_minutes", 30))
        except (TypeError, ValueError) as error:
            raise ValueError("監視頻度を選択してください。") from error
        if interval not in {15, 30, 60, 180, 360}:
            raise ValueError("監視頻度が正しくありません。")
        return {
            "ui_mode": mode,
            "tcg_keys": selected,
            "show_popup": bool(values.get("show_popup", True)),
            "play_notification_sound": bool(values.get("play_notification_sound", True)),
            "gmail_setup_now": bool(values.get("gmail_setup_now", False)),
            "monitoring_enabled": bool(values.get("monitoring_enabled", False)),
            "interval_minutes": interval,
        }
