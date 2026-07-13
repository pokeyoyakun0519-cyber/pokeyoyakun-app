from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from typing import Any

from core.runtime_paths import app_root


class EmailAccountManager:
    MAX_ACCOUNTS = 3

    def __init__(self):
        self.path = (
            app_root()
            / "config"
            / "email_accounts.json"
        )

    def load_accounts(
        self,
    ) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []

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
            return []

        if not isinstance(data, list):
            return []

        output = []
        for item in data[: self.MAX_ACCOUNTS]:
            if isinstance(item, dict):
                output.append(dict(item))
        return output

    def add_account(
        self,
        display_name: str,
        email_address: str,
    ) -> dict[str, Any]:
        accounts = self.load_accounts()

        if len(accounts) >= self.MAX_ACCOUNTS:
            raise ValueError(
                "メールアカウントは最大3件までです。"
            )

        email = email_address.strip().lower()
        if not self._valid_email(email):
            raise ValueError(
                "メールアドレスの形式を確認してください。"
            )

        if any(
            str(item.get("email", "")).lower()
            == email
            for item in accounts
        ):
            raise ValueError(
                "同じメールアドレスは登録済みです。"
            )

        account = {
            "id": uuid.uuid4().hex[:16],
            "display_name": (
                display_name.strip()
                or f"メール{len(accounts) + 1}"
            ),
            "email": email,
            "provider": "gmail",
            "enabled": True,
            "connection_status": "未連携",
            "last_checked": "",
            "created_at": datetime.now().isoformat(
                timespec="seconds"
            ),
        }
        accounts.append(account)
        self._save(accounts)
        return account

    def remove_account(
        self,
        account_id: str,
    ) -> bool:
        accounts = self.load_accounts()
        filtered = [
            item
            for item in accounts
            if str(item.get("id", ""))
            != account_id
        ]

        if len(filtered) == len(accounts):
            return False

        self._save(filtered)
        return True

    def set_enabled(
        self,
        account_id: str,
        enabled: bool,
    ) -> bool:
        accounts = self.load_accounts()
        changed = False

        for item in accounts:
            if str(item.get("id", "")) != account_id:
                continue

            item["enabled"] = bool(enabled)
            changed = True
            break

        if changed:
            self._save(accounts)

        return changed


    def mark_checked(
        self,
        account_id: str,
    ) -> bool:
        accounts = self.load_accounts()
        changed = False

        for item in accounts:
            if str(item.get("id", "")) != account_id:
                continue

            item["last_checked"] = datetime.now().isoformat(
                timespec="seconds"
            )
            changed = True
            break

        if changed:
            self._save(accounts)

        return changed

    def update_connection_status(
        self,
        account_id: str,
        status: str,
    ) -> bool:
        accounts = self.load_accounts()
        changed = False

        for item in accounts:
            if str(item.get("id", "")) != account_id:
                continue

            item["connection_status"] = status[:40]
            changed = True
            break

        if changed:
            self._save(accounts)

        return changed

    def _save(
        self,
        accounts: list[dict[str, Any]],
    ) -> None:
        self.path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        self.path.write_text(
            json.dumps(
                accounts[: self.MAX_ACCOUNTS],
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    @staticmethod
    def _valid_email(
        value: str,
    ) -> bool:
        return bool(
            re.fullmatch(
                r"[^@\s]+@[^@\s]+\.[^@\s]+",
                value,
            )
        )
