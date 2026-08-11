from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from core.json_file_state import CORRUPT, inspect_json_file
from core.runtime_paths import app_root, bundled_root
from core.secure_https import build_https_opener


RECENT_SEARCH_URL = "https://api.x.com/2/tweets/search/recent"
QUERIES = {
    "pokemon": '("ポケモンカード" OR ポケカ) (抽選 OR 予約 OR 再販 OR 受付) -is:retweet',
    "onepiece": '("ONE PIECEカード" OR "ワンピースカード") (抽選 OR 予約 OR 再販 OR 受付) -is:retweet',
}


class XRecentSearch:
    """Optional X API v2 collector. It never scrapes X web pages."""

    def __init__(
        self,
        root: Path | None = None,
        *,
        opener=None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.root = Path(root) if root is not None else app_root()
        self.state_path = self.root / "cache" / "x_recent_search_state.json"
        self.account_path = self.root / "config" / "trusted_x_accounts.json"
        self.opener = opener or build_https_opener()
        self.now = now or (lambda: datetime.now(timezone.utc))

    def search(self, tcg: str, bearer_token: str | None = None) -> dict[str, Any]:
        if tcg not in QUERIES:
            raise ValueError("X検索対象はpokemonまたはonepieceだけです。")
        token = (bearer_token or os.environ.get("POKEYOYA_X_BEARER_TOKEN", "")).strip()
        if not token:
            return {"status": "disabled", "candidates": [], "request_count": 0}
        state = self._load_state()
        item_state = dict(state.get(tcg, {}))
        retry_at = float(item_state.get("retry_at", 0) or 0)
        if retry_at > time.time():
            return {
                "status": "backoff", "candidates": [], "request_count": 0,
                "retry_after": max(1, int(retry_at - time.time())),
            }
        params = {
            "query": QUERIES[tcg],
            "max_results": "100",
            "tweet.fields": "created_at,author_id,entities",
            "expansions": "author_id",
            "user.fields": "username,name,verified",
        }
        since_id = str(item_state.get("since_id", "")).strip()
        if since_id:
            params["since_id"] = since_id
        else:
            params["start_time"] = (
                self.now() - timedelta(days=7)
            ).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        request = urllib.request.Request(
            RECENT_SEARCH_URL + "?" + urllib.parse.urlencode(params),
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
        try:
            with self.opener.open(request, timeout=20) as response:
                payload = json.loads(response.read(2_000_000).decode("utf-8"))
                headers = response.headers
        except urllib.error.HTTPError as error:
            if error.code != 429:
                raise
            attempts = min(6, int(item_state.get("backoff_attempts", 0)) + 1)
            reset = int(error.headers.get("x-rate-limit-reset", "0") or 0)
            delay = max(60, min(3600, (2 ** attempts) * 30))
            retry_at = max(time.time() + delay, float(reset))
            state[tcg] = {**item_state, "retry_at": retry_at, "backoff_attempts": attempts}
            self._save_state(state)
            return {
                "status": "rate_limited", "candidates": [], "request_count": 1,
                "retry_after": max(1, int(retry_at - time.time())),
            }
        users = {
            str(item.get("id", "")): item
            for item in payload.get("includes", {}).get("users", [])
            if isinstance(item, dict)
        }
        accounts = {
            str(item.get("username", "")).casefold(): item
            for item in self.load_trusted_accounts()
            if item.get("enabled", True) and str(item.get("tcg", "")) == tcg
        }
        candidates = []
        for tweet in payload.get("data", []):
            if not isinstance(tweet, dict):
                continue
            user = users.get(str(tweet.get("author_id", "")), {})
            username = str(user.get("username", ""))
            trusted = accounts.get(username.casefold(), {})
            score = int(trusted.get("trust_score", 30) or 30)
            text = str(tweet.get("text", ""))
            url = self._first_external_url(tweet)
            explicit = bool(re.search(r"抽選|予約|応募|受付", text))
            candidates.append({
                "id": str(tweet.get("id", "")),
                "tcg_key": tcg,
                "information_type": "RESTOCK" if re.search(r"再販|再入荷", text) else "APPLICATION",
                "text": text,
                "username": username,
                "display_name": str(user.get("name", "")),
                "store_name": str(trusted.get("store_name", "")),
                "trust_score": score,
                "confirmed": bool(score >= 85 and explicit and url),
                "application_url": url,
                "source_url": f"https://x.com/{username}/status/{tweet.get('id', '')}",
                "created_at": str(tweet.get("created_at", "")),
            })
        newest = str(payload.get("meta", {}).get("newest_id", "")).strip()
        if newest:
            state[tcg] = {"since_id": newest, "retry_at": 0, "backoff_attempts": 0}
            self._save_state(state)
        return {
            "status": "ok", "candidates": candidates, "request_count": 1,
            "since_id": newest or since_id,
            "rate_limit_remaining": headers.get("x-rate-limit-remaining", ""),
        }

    def load_trusted_accounts(self) -> list[dict[str, Any]]:
        if self.account_path.exists():
            path = self.account_path
        else:
            packaged = bundled_root() / "resources" / "trusted_x_accounts.json"
            source = bundled_root() / "app" / "resources" / "trusted_x_accounts.json"
            path = packaged if packaged.exists() else source
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        required = {"username", "display_name", "category", "store_name", "tcg", "trust_score", "enabled"}
        return [item for item in value if isinstance(item, dict) and required <= set(item)] if isinstance(value, list) else []

    def search_and_store(
        self, enabled_tcg_keys: set[str], bearer_token: str | None = None
    ) -> dict[str, Any]:
        path = self.root / "data" / "information_candidates.json"
        file_result = inspect_json_file(path, list)
        if file_result.state == CORRUPT:
            return {
                "status": "corrupt",
                "error": file_result.error,
                "results": {},
                "candidate_count": 0,
                "confirmed_count": 0,
            }
        existing = file_result.data or []
        by_id = {
            (str(item.get("tcg_key", "")), str(item.get("id", ""))): dict(item)
            for item in existing if isinstance(item, dict)
        }
        results = {}
        for tcg in sorted(set(enabled_tcg_keys) & set(QUERIES)):
            result = self.search(tcg, bearer_token)
            results[tcg] = result
            for item in result.get("candidates", []):
                by_id[(tcg, str(item.get("id", "")))] = item
        if any(result.get("candidates") for result in results.values()):
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".json.tmp")
            temporary.write_text(
                json.dumps(list(by_id.values()), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temporary.replace(path)
        return {
            "results": results,
            "candidate_count": len(by_id),
            "confirmed_count": sum(bool(item.get("confirmed")) for item in by_id.values()),
        }

    @staticmethod
    def deduplicate(web_items: list[dict], x_items: list[dict]) -> list[dict]:
        output = [dict(item) for item in web_items]
        for item in x_items:
            existing = next(
                (value for value in output if XRecentSearch._same_case(value, item)),
                None,
            )
            if existing is not None:
                existing.setdefault("source_urls", []).append(item.get("source_url", ""))
                continue
            output.append(dict(item))
        return output

    @staticmethod
    def _same_case(left: dict, right: dict) -> bool:
        left_url = XRecentSearch._normalized_url(left.get("application_url", ""))
        right_url = XRecentSearch._normalized_url(right.get("application_url", ""))
        if left_url and left_url == right_url:
            return str(left.get("tcg_key", "")).casefold() == str(
                right.get("tcg_key", "")
            ).casefold()
        return XRecentSearch._case_key(left) == XRecentSearch._case_key(right)

    @staticmethod
    def _normalized_url(value: Any) -> str:
        try:
            parsed = urllib.parse.urlsplit(str(value).strip())
        except ValueError:
            return ""
        if parsed.scheme.casefold() not in {"http", "https"} or not parsed.hostname:
            return ""
        query = urllib.parse.urlencode([
            (key, item)
            for key, item in urllib.parse.parse_qsl(
                parsed.query, keep_blank_values=True
            )
            if key.casefold() not in {
                "fbclid", "gclid", "ref_src", "ref_url", "twclid", "xclid",
            }
            and not key.casefold().startswith("utm_")
        ])
        return urllib.parse.urlunsplit((
            parsed.scheme.casefold(),
            parsed.netloc.casefold(),
            parsed.path.rstrip("/"),
            query,
            "",
        ))

    @staticmethod
    def _case_key(item: dict) -> tuple[str, ...]:
        norm = lambda value: re.sub(r"[\s　「」『』・_-]", "", str(value)).casefold()
        url = XRecentSearch._normalized_url(item.get("application_url", ""))
        return (
            norm(item.get("tcg_key", "")), norm(item.get("product_name", item.get("name", ""))),
            norm(item.get("store_name", "")), url, str(item.get("application_end_at", "")),
        )

    @staticmethod
    def _first_external_url(tweet: dict) -> str:
        for item in tweet.get("entities", {}).get("urls", []):
            if not isinstance(item, dict):
                continue
            url = str(item.get("expanded_url") or item.get("unwound_url") or "")
            if url.startswith("https://") and "x.com/" not in url and "twitter.com/" not in url:
                return url
        return ""

    def _load_state(self) -> dict[str, Any]:
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_state(self, state: dict[str, Any]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.state_path)
