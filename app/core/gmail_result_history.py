from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from core.runtime_paths import app_root


class GmailResultHistory:
    def __init__(self):
        self.path = (
            app_root()
            / "data"
            / "gmail_result_history.json"
        )

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {
                "processed": {},
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
                "processed": {},
            }

        if not isinstance(data, dict):
            return {
                "processed": {},
            }

        processed = data.get("processed", {})
        if not isinstance(processed, dict):
            processed = {}

        return {
            "processed": processed,
        }

    def is_processed(
        self,
        account_id: str,
        message_id: str,
    ) -> bool:
        key = self._key(
            account_id,
            message_id,
        )
        return key in self.load().get(
            "processed",
            {},
        )

    def mark_processed(
        self,
        account_id: str,
        message_id: str,
        result: dict[str, Any],
    ) -> None:
        state = self.load()
        processed = state.setdefault(
            "processed",
            {},
        )
        key = self._key(
            account_id,
            message_id,
        )
        processed[key] = {
            "status": str(
                result.get("status", "")
            ),
            "product_name": str(
                result.get(
                    "product_name",
                    "",
                )
            ),
            "site_name": str(
                result.get(
                    "site_name",
                    "",
                )
            ),
            "tcg_key": str(result.get("tcg_key", "other")),
            "tcg": str(result.get("tcg", "その他")),
            "processed_at": datetime.now().isoformat(
                timespec="seconds"
            ),
        }

        # Keep the most recent 1000 results.
        items = list(processed.items())
        if len(items) > 1000:
            items = items[-1000:]
            state["processed"] = dict(items)

        self.path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        self.path.write_text(
            json.dumps(
                state,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    @staticmethod
    def _key(
        account_id: str,
        message_id: str,
    ) -> str:
        return (
            str(account_id)
            + "|"
            + str(message_id)
        )
