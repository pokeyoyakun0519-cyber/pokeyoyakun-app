from __future__ import annotations

import json
import os
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

    def summary(self) -> dict[str, str]:
        """Summarize saved state without making an X request or exposing secrets."""
        state_result = inspect_json_file(self.client.state_path, dict)
        state = state_result.data or {}
        timeline = state.get("timeline", {}) if isinstance(state, dict) else {}
        entries = [value for value in timeline.values() if isinstance(value, dict)]
        retry_at = max((float(value.get("retry_at", 0) or 0) for value in entries), default=0)
        last_request = max((float(value.get("last_request_at", 0) or 0) for value in entries), default=0)
        now = datetime.now(timezone.utc).timestamp()
        if retry_at > now:
            return {"state": "Rate Limit中", "last_success": self._timestamp(last_request),
                    "message": "X APIの再試行待ちです。"}
        if last_request:
            age = now - last_request
            return {
                "state": "正常" if age <= 3600 else "更新待ち",
                "last_success": self._timestamp(last_request),
                "message": "保存済みの監視結果を表示しています。",
            }
        if not os.environ.get("POKEYOYA_X_BEARER_TOKEN", "").strip():
            return {
                "state": "未設定", "last_success": "",
                "message": "X APIトークン未設定のため停止中です。User Editionには秘密情報を同梱しません。",
            }
        return {"state": "更新待ち", "last_success": "", "message": "初回取得を待っています。"}

    @staticmethod
    def _timestamp(value: object) -> str:
        try:
            return datetime.fromtimestamp(
                float(value), timezone.utc
            ).astimezone().strftime("%Y/%m/%d %H:%M")
        except (TypeError, ValueError, OSError):
            return ""
