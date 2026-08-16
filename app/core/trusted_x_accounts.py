from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from core.json_file_state import CORRUPT, ensure_json_writable, inspect_json_file
from core.runtime_paths import app_root, bundled_root


OFFICIAL_MANUFACTURER = "OFFICIAL_MANUFACTURER"
OFFICIAL_STORE = "OFFICIAL_STORE"
OFFICIAL_SHOP_BRANCH = "OFFICIAL_SHOP_BRANCH"
TRUSTED_INFORMATION = "TRUSTED_INFORMATION"
GENERAL_INFORMATION = "GENERAL_INFORMATION"
SOURCE_TYPES = {
    OFFICIAL_MANUFACTURER,
    OFFICIAL_STORE,
    OFFICIAL_SHOP_BRANCH,
    TRUSTED_INFORMATION,
    GENERAL_INFORMATION,
}
_LEGACY_SOURCE_TYPES = {
    "manufacturer_official": OFFICIAL_MANUFACTURER,
    "store_official": OFFICIAL_SHOP_BRANCH,
    "trusted_information": TRUSTED_INFORMATION,
    "general_information": GENERAL_INFORMATION,
}


class TrustedXAccountRegistry:
    """Editable account configuration with separate runtime observations.

    Reading never rewrites either JSON file.  Administrative changes are
    explicit and runtime counters stay outside the curated configuration.
    """

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root is not None else app_root()
        self.config_path = self.root / "config" / "trusted_x_accounts.json"
        self.state_path = self.root / "cache" / "trusted_x_account_state.json"

    def load(self) -> list[dict[str, Any]]:
        path = self._source_path()
        result = inspect_json_file(path, list)
        if result.state == CORRUPT:
            return []
        output: list[dict[str, Any]] = []
        for raw in result.data or []:
            normalized = self.normalize(raw)
            if normalized:
                output.append(normalized)
        return output

    def load_with_observations(self) -> list[dict[str, Any]]:
        runtime = self.load_runtime_state()
        output = []
        for account in self.load():
            observed = dict(runtime.get("|".join(self._key(account)), {}))
            detected = int(observed.get("detected_count", 0) or 0)
            output.append({
                **account,
                "last_seen_tweet_id": str(
                    observed.get("last_seen_tweet_id", observed.get("latest_tweet_id", ""))
                ),
                "last_checked_at": str(
                    observed.get("last_checked_at", observed.get("last_fetched_at", ""))
                ),
                "latest_tweet_id": str(observed.get("latest_tweet_id", "")),
                "last_fetched_at": str(observed.get("last_fetched_at", "")),
                "past_candidate_count": detected,
                "detected_count": detected,
                "confirmed_count": int(observed.get("confirmed_count", 0) or 0),
                "rejected_count": int(observed.get("rejected_count", 0) or 0),
                "false_positive_count": int(
                    observed.get("false_positive_count", 0) or 0
                ),
                "observed_accuracy": observed.get("observed_accuracy"),
            })
        return output

    def save(self, accounts: list[dict[str, Any]]) -> None:
        normalized = [item for raw in accounts if (item := self.normalize(raw))]
        if self.config_path.exists():
            ensure_json_writable(self.config_path, list)
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.config_path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(normalized, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self.config_path)

    def upsert(self, account: dict[str, Any]) -> dict[str, Any]:
        normalized = self.normalize(account)
        if not normalized:
            raise ValueError("X監視アカウント設定が不正です。")
        accounts = self.load()
        key = self._key(normalized)
        replaced = False
        for index, current in enumerate(accounts):
            if self._key(current) == key:
                accounts[index] = normalized
                replaced = True
                break
        if not replaced:
            accounts.append(normalized)
        self.save(accounts)
        return normalized

    def remove(self, username: str, tcg: str) -> bool:
        accounts = self.load()
        key = (username.lstrip("@").casefold(), tcg.casefold())
        filtered = [item for item in accounts if self._key(item) != key]
        if len(filtered) == len(accounts):
            return False
        self.save(filtered)
        return True

    def set_enabled(self, username: str, tcg: str, enabled: bool) -> bool:
        return self._update(username, tcg, enabled=bool(enabled))

    def set_manual_trust(self, username: str, tcg: str, score: int) -> bool:
        return self._update(username, tcg, manual_trust_score=max(0, min(100, int(score))))

    def load_runtime_state(self) -> dict[str, Any]:
        result = inspect_json_file(self.state_path, dict)
        return dict(result.data or {}) if result.state != CORRUPT else {}

    def save_runtime_state(self, state: dict[str, Any]) -> None:
        if self.state_path.exists():
            ensure_json_writable(self.state_path, dict)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(self.state_path)

    def record_fetch(
        self,
        account: dict[str, Any],
        *,
        tweet_id: str = "",
        fetched_at: str = "",
        detected_delta: int = 0,
        confirmed_delta: int = 0,
        rejected_delta: int = 0,
        false_positive_delta: int = 0,
    ) -> None:
        state = self.load_runtime_state()
        key = "|".join(self._key(account))
        current = dict(state.get(key, {}))
        for field, delta in (
            ("detected_count", detected_delta),
            ("confirmed_count", confirmed_delta),
            ("rejected_count", rejected_delta),
            ("false_positive_count", false_positive_delta),
        ):
            current[field] = max(0, int(current.get(field, 0) or 0) + int(delta))
        if tweet_id:
            current["latest_tweet_id"] = tweet_id
            current["last_seen_tweet_id"] = tweet_id
        if fetched_at:
            current["last_fetched_at"] = fetched_at
            current["last_checked_at"] = fetched_at
        decided = current.get("confirmed_count", 0) + current.get("rejected_count", 0)
        current["observed_accuracy"] = (
            round(current.get("confirmed_count", 0) / decided, 4) if decided else None
        )
        state[key] = current
        self.save_runtime_state(state)

    @staticmethod
    def normalize(raw: Any) -> dict[str, Any] | None:
        if not isinstance(raw, dict):
            return None
        username = str(raw.get("username", "")).strip().lstrip("@")
        tcg = str(raw.get("tcg", "")).strip().casefold()
        if not re.fullmatch(r"[A-Za-z0-9_]{1,15}", username) or tcg not in {
            "pokemon", "onepiece", "union_arena", "dragon_ball_fusion_world"
        }:
            return None
        source_type = str(raw.get("source_type", "")).strip().upper()
        if not source_type:
            source_type = _LEGACY_SOURCE_TYPES.get(
                str(raw.get("category", "")).casefold(), GENERAL_INFORMATION
            )
        if source_type not in SOURCE_TYPES:
            return None
        manual = raw.get("manual_trust_score", raw.get("trust_score", 30))
        try:
            manual_score = max(0, min(100, int(manual)))
        except (TypeError, ValueError):
            return None
        return {
            "user_id": str(raw.get("user_id", "")).strip(),
            "username": username,
            "display_name": str(raw.get("display_name", "")).strip(),
            "tcg": tcg,
            "source_type": source_type,
            "store_name": str(raw.get("store_name", "")).strip(),
            "manual_trust_score": manual_score,
            "enabled": bool(raw.get("enabled", True)),
            "memo": str(raw.get("memo", "")).strip(),
        }

    def _source_path(self) -> Path:
        if self.config_path.exists():
            return self.config_path
        packaged = bundled_root() / "resources" / "trusted_x_accounts.json"
        source = bundled_root() / "app" / "resources" / "trusted_x_accounts.json"
        return packaged if packaged.exists() else source

    @staticmethod
    def _key(account: dict[str, Any]) -> tuple[str, str]:
        return (
            str(account.get("username", "")).casefold(),
            str(account.get("tcg", "")).casefold(),
        )

    def _update(self, username: str, tcg: str, **changes: Any) -> bool:
        accounts = self.load()
        key = (username.lstrip("@").casefold(), tcg.casefold())
        for account in accounts:
            if self._key(account) == key:
                account.update(changes)
                self.save(accounts)
                return True
        return False
