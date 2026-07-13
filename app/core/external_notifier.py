import json
import smtplib
import ssl
import urllib.error
import urllib.request
from email.message import EmailMessage
from typing import Any

from core.external_notification_config import (
    ExternalNotificationConfig,
)
from core.log_manager import LogManager
from core.retry_policy import RetryPolicy


class ExternalNotificationError(Exception):
    pass


class ExternalNotifier:
    USER_AGENT = "PokeyoyaKun-Notifier/0.29"

    CATEGORY_COLORS = {
        "テスト": 0x66C0F4,
        "公式情報": 0xF5A623,
        "抽選": 0x57F287,
        "エラー": 0xED4245,
        "情報": 0x5865F2,
    }

    CATEGORY_ICONS = {
        "テスト": "🧪",
        "公式情報": "📢",
        "抽選": "🏆",
        "エラー": "⚠️",
        "情報": "ℹ️",
    }

    def __init__(self):
        self.config_manager = ExternalNotificationConfig()
        self.log_manager = LogManager()
        self.retry_policy = RetryPolicy(
            attempts=3,
            initial_delay_seconds=1.0,
            backoff_multiplier=2.0,
            max_delay_seconds=4.0,
        )

    def send(
        self,
        title: str,
        message: str,
        category: str = "情報",
        *,
        url: str = "",
        fields: list[dict[str, Any]] | None = None,
    ) -> dict:
        config = self.config_manager.load()
        results = {
            "discord": "disabled",
            "email": "disabled",
        }

        if config.get("discord_enabled", False):
            try:
                self._send_discord(
                    config,
                    title,
                    message,
                    category,
                    url=url,
                    fields=fields or [],
                )
                results["discord"] = "sent"
            except Exception as error:
                results["discord"] = f"error: {error}"
                self.log_manager.write(
                    f"Discord通知失敗: {error}",
                    level="ERROR",
                )

        if config.get("email_enabled", False):
            try:
                self._send_email(
                    config,
                    title,
                    message,
                    category,
                    url=url,
                    fields=fields or [],
                )
                results["email"] = "sent"
            except Exception as error:
                results["email"] = f"error: {error}"
                self.log_manager.write(
                    f"メール通知失敗: {error}",
                    level="ERROR",
                )

        return results

    def send_test(self) -> dict:
        return self.send(
            "ポケヨヤ君 テスト通知",
            "外部通知の送信テストです。",
            "テスト",
            url="https://discord.com",
            fields=[
                {
                    "name": "状態",
                    "value": "Discord Embed表示テスト",
                    "inline": False,
                }
            ],
        )

    def _send_discord(
        self,
        config: dict,
        title: str,
        message: str,
        category: str,
        *,
        url: str,
        fields: list[dict[str, Any]],
    ) -> None:
        webhook_url = str(
            config.get("discord_webhook_url", "")
        ).strip()

        if not webhook_url:
            raise ExternalNotificationError(
                "Discord Webhook URLが未設定です。"
            )

        color = self.CATEGORY_COLORS.get(
            category,
            self.CATEGORY_COLORS["情報"],
        )
        icon = self.CATEGORY_ICONS.get(
            category,
            self.CATEGORY_ICONS["情報"],
        )

        embed = {
            "title": f"{icon} {title}",
            "description": message[:4000],
            "color": color,
            "footer": {
                "text": f"ポケヨヤ君 • {category}",
            },
        }

        if url.startswith(("http://", "https://")):
            embed["url"] = url

        safe_fields = []
        for field in fields[:20]:
            name = str(field.get("name", "項目"))[:256]
            value = str(field.get("value", "-"))[:1024]
            safe_fields.append(
                {
                    "name": name,
                    "value": value,
                    "inline": bool(field.get("inline", False)),
                }
            )

        if safe_fields:
            embed["fields"] = safe_fields

        payload = {
            "username": "ポケヨヤ君",
            "embeds": [embed],
            "allowed_mentions": {
                "parse": [],
            },
        }

        request = urllib.request.Request(
            webhook_url,
            data=json.dumps(
                payload,
                ensure_ascii=False,
            ).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "User-Agent": self.USER_AGENT,
            },
            method="POST",
        )

        def send_request():
            with urllib.request.urlopen(
                request,
                timeout=15,
            ) as response:
                return getattr(response, "status", 204)

        try:
            status = self.retry_policy.run(send_request)
        except urllib.error.HTTPError as error:
            body = error.read().decode(
                "utf-8",
                errors="replace",
            )
            raise ExternalNotificationError(
                f"Discord HTTP {error.code}: {body[:300]}"
            ) from error
        except urllib.error.URLError as error:
            raise ExternalNotificationError(
                f"Discordへ接続できません: {error.reason}"
            ) from error

        if status not in (200, 204):
            raise ExternalNotificationError(
                f"DiscordがHTTP {status}を返しました。"
            )

    def _send_email(
        self,
        config: dict,
        title: str,
        message: str,
        category: str,
        *,
        url: str,
        fields: list[dict[str, Any]],
    ) -> None:
        host = str(config.get("smtp_host", "")).strip()
        port = int(config.get("smtp_port", 587))
        username = str(
            config.get("smtp_username", "")
        ).strip()
        password = str(
            config.get("smtp_password", "")
        )
        email_from = str(
            config.get("email_from", "")
        ).strip()
        email_to = str(
            config.get("email_to", "")
        ).strip()

        if not host:
            raise ExternalNotificationError(
                "SMTPサーバーが未設定です。"
            )

        if not email_from or not email_to:
            raise ExternalNotificationError(
                "送信元または送信先メールアドレスが未設定です。"
            )

        lines = [message]

        for field in fields:
            lines.append(
                f"{field.get('name', '項目')}: "
                f"{field.get('value', '-')}"
            )

        if url.startswith(("http://", "https://")):
            lines.append("")
            lines.append(f"確認URL: {url}")

        mail = EmailMessage()
        mail["Subject"] = (
            f"[ポケヨヤ君][{category}] {title}"
        )
        mail["From"] = email_from
        mail["To"] = email_to
        mail.set_content("\n".join(lines))

        use_tls = bool(
            config.get("smtp_use_tls", True)
        )

        def send_mail_once():
            if port == 465:
                context = ssl.create_default_context()
                with smtplib.SMTP_SSL(
                    host,
                    port,
                    timeout=20,
                    context=context,
                ) as server:
                    if username:
                        server.login(username, password)
                    server.send_message(mail)
                return

            with smtplib.SMTP(
                host,
                port,
                timeout=20,
            ) as server:
                server.ehlo()

                if use_tls:
                    context = ssl.create_default_context()
                    server.starttls(context=context)
                    server.ehlo()

                if username:
                    server.login(username, password)

                server.send_message(mail)

        try:
            self.retry_policy.run(send_mail_once)
        except (
            OSError,
            smtplib.SMTPException,
        ) as error:
            raise ExternalNotificationError(
                f"メール送信に失敗しました: {error}"
            ) from error
