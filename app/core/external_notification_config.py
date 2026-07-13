import json

from core.runtime_paths import app_root


DEFAULT_CONFIG = {
    "discord_enabled": False,
    "discord_webhook_url": "",
    "email_enabled": False,
    "smtp_host": "",
    "smtp_port": 587,
    "smtp_use_tls": True,
    "smtp_username": "",
    "smtp_password": "",
    "email_from": "",
    "email_to": "",
    "notify_source_changes": True,
    "notify_lottery_wins": True,
    "notify_errors": True,
}


class ExternalNotificationConfig:
    def __init__(self):
        self.path = (
            app_root()
            / "config"
            / "external_notification_settings.json"
        )

    def load(self) -> dict:
        if not self.path.exists():
            self.save(DEFAULT_CONFIG)
            return dict(DEFAULT_CONFIG)

        try:
            data = json.loads(
                self.path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError):
            return dict(DEFAULT_CONFIG)

        result = dict(DEFAULT_CONFIG)
        if isinstance(data, dict):
            result.update(data)

        try:
            result["smtp_port"] = int(
                result.get("smtp_port", 587)
            )
        except (TypeError, ValueError):
            result["smtp_port"] = 587

        return result

    def save(self, config: dict) -> None:
        result = dict(DEFAULT_CONFIG)
        result.update(config)

        try:
            result["smtp_port"] = int(
                result.get("smtp_port", 587)
            )
        except (TypeError, ValueError):
            result["smtp_port"] = 587

        self.path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        self.path.write_text(
            json.dumps(
                result,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
