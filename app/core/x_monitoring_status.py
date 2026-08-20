from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.json_file_state import inspect_json_file
from core.x_recent_search import XRecentSearch


class XMonitoringStatus:
    """Read-only X monitoring status built exclusively from saved local state."""

    def __init__(self, root: Path | None = None):
        self.client = XRecentSearch(root)
        self.root = self.client.root

    def rows(self) -> list[dict[str, Any]]:
        state = self.client._load_state()
        candidates_result = inspect_json_file(
            self.root / "data" / "information_candidates.json", list
        )
        candidates = candidates_result.data or []
        output = []
        for account in self.client.load_trusted_accounts():
            username = str(account.get("username", ""))
            tcg = str(account.get("tcg", ""))
            key = f"{username.casefold()}:{tcg}"
            timeline = state.get("timeline", {}).get(key, {})
            matching = [
                item for item in candidates
                if isinstance(item, dict)
                and str(item.get("x_account") or item.get("username", "")).casefold()
                == username.casefold()
                and str(item.get("tcg_key", "")) == tcg
            ]
            output.append(
                {
                    **account,
                    "last_fetch": self._timestamp(timeline.get("last_request_at")),
                    "last_post_detected": max(
                        (str(item.get("detected_at") or item.get("created_at") or "") for item in matching),
                        default="",
                    ),
                    "candidate_count": sum(
                        item.get("verification_status") in {"pending", "candidate", "confirming"}
                        for item in matching
                    ),
                    "confirmed_count": sum(
                        item.get("verification_status") == "confirmed" for item in matching
                    ),
                    "error": "429 backoff"
                    if float(timeline.get("retry_at", 0) or 0) > datetime.now(timezone.utc).timestamp()
                    else "",
                }
            )
        return output

    @staticmethod
    def _timestamp(value: object) -> str:
        try:
            return datetime.fromtimestamp(float(value), timezone.utc).isoformat(timespec="seconds")
        except (TypeError, ValueError, OSError):
            return ""
