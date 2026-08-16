from __future__ import annotations

import json
import hashlib
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
from core.runtime_paths import app_root
from core.secure_https import build_https_opener
from core.trusted_x_accounts import (
    GENERAL_INFORMATION,
    OFFICIAL_MANUFACTURER,
    OFFICIAL_SHOP_BRANCH,
    OFFICIAL_STORE,
    TRUSTED_INFORMATION,
    TrustedXAccountRegistry,
)


RECENT_SEARCH_URL = "https://api.x.com/2/tweets/search/recent"
QUERIES = {
    "pokemon": '("ポケモンカード" OR ポケカ) (抽選 OR 予約 OR 再販 OR 受付) -is:retweet',
    "onepiece": '("ONE PIECEカード" OR "ワンピースカード") (抽選 OR 予約 OR 再販 OR 受付) -is:retweet',
    "union_arena": '("UNION ARENA" OR ユニオンアリーナ OR ユニアリ) (抽選 OR 予約 OR 再販 OR 再入荷 OR 受付) -is:retweet',
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
        self.accounts = TrustedXAccountRegistry(self.root)
        self.opener = opener or build_https_opener()
        self.now = now or (lambda: datetime.now(timezone.utc))

    def search(self, tcg: str, bearer_token: str | None = None) -> dict[str, Any]:
        if tcg not in QUERIES:
            raise ValueError("X検索対象TCGが未対応です。")
        return self._search_query(tcg, QUERIES[tcg], tcg, bearer_token)

    def search_trusted_accounts(
        self, tcg: str, bearer_token: str | None = None
    ) -> dict[str, Any]:
        if tcg not in QUERIES:
            raise ValueError("X検索対象TCGが未対応です。")
        accounts = [
            account for account in self.load_trusted_accounts()
            if account.get("enabled", True) and account.get("tcg") == tcg
        ]
        if not accounts:
            return {"status": "disabled", "candidates": [], "request_count": 0}
        results = []
        for offset in range(0, len(accounts), 10):
            batch = accounts[offset:offset + 10]
            usernames = [str(account["username"]) for account in batch]
            from_terms = " OR ".join(f"from:{username}" for username in usernames)
            query = (
                f"({from_terms}) (抽選 OR 予約 OR 受付 OR 応募 OR 再販 OR 再入荷 OR 入荷 OR 受注) "
                "-is:retweet"
            )
            signature = hashlib.sha256(
                ",".join(username.casefold() for username in usernames).encode("utf-8")
            ).hexdigest()[:12]
            result = self._search_query(
                tcg,
                query,
                f"trusted:{tcg}:{signature}",
                bearer_token,
                monitored_only=True,
                allowed_usernames={username.casefold() for username in usernames},
            )
            results.append(result)
            if result.get("status") == "rate_limited":
                break
        candidates = [
            item for result in results for item in result.get("candidates", [])
        ]
        statuses = [str(result.get("status", "")) for result in results]
        since_values = [str(result.get("since_id", "")) for result in results]
        return {
            "status": "ok" if statuses and all(value == "ok" for value in statuses) else (
                statuses[-1] if statuses else "disabled"
            ),
            "candidates": candidates,
            "request_count": sum(int(result.get("request_count", 0)) for result in results),
            "since_id": since_values[0] if len(since_values) == 1 else since_values,
            "rate_limit_remaining": (
                results[-1].get("rate_limit_remaining", "") if results else ""
            ),
        }

    def _search_query(
        self,
        tcg: str,
        query: str,
        state_key: str,
        bearer_token: str | None,
        *,
        monitored_only: bool = False,
        allowed_usernames: set[str] | None = None,
    ) -> dict[str, Any]:
        token = (bearer_token or os.environ.get("POKEYOYA_X_BEARER_TOKEN", "")).strip()
        if not token:
            return {"status": "disabled", "candidates": [], "request_count": 0}
        state = self._load_state()
        item_state = dict(state.get(state_key, {}))
        retry_at = float(item_state.get("retry_at", 0) or 0)
        if retry_at > time.time():
            return {
                "status": "backoff", "candidates": [], "request_count": 0,
                "retry_after": max(1, int(retry_at - time.time())),
            }
        params = {
            "query": query,
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
            state[state_key] = {**item_state, "retry_at": retry_at, "backoff_attempts": attempts}
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
            if item.get("enabled", True)
            and str(item.get("tcg", "")) == tcg
            and (
                allowed_usernames is None
                or str(item.get("username", "")).casefold() in allowed_usernames
            )
        }
        candidates = []
        for tweet in payload.get("data", []):
            if not isinstance(tweet, dict):
                continue
            user = users.get(str(tweet.get("author_id", "")), {})
            username = str(user.get("username", ""))
            trusted = accounts.get(username.casefold(), {})
            if monitored_only and not trusted:
                continue
            score = int(trusted.get("manual_trust_score", 30) or 30)
            text = str(tweet.get("text", ""))
            url = self._first_external_url(tweet)
            classification = self._classify_post(text)
            if classification == "IRRELEVANT":
                continue
            source_type = str(trusted.get("source_type", GENERAL_INFORMATION))
            official = source_type in {
                OFFICIAL_MANUFACTURER, OFFICIAL_STORE, OFFICIAL_SHOP_BRANCH,
            }
            explicit = classification in {"LOTTERY", "RESERVATION", "RESTOCK"}
            confirmed = bool(official and explicit and url)
            product_name = self._extract_product_name(text)
            date_fields = self._extract_date_fields(text, str(tweet.get("created_at", "")))
            source_url = f"https://x.com/{username}/status/{tweet.get('id', '')}"
            candidates.append({
                "id": str(tweet.get("id", "")),
                "tcg_key": tcg,
                "information_type": "RESTOCK" if classification == "RESTOCK" else (
                    "APPLICATION" if classification in {"LOTTERY", "RESERVATION"} else "NEWS"
                ),
                "application_type": classification,
                "text": text,
                "product_name": product_name,
                "username": username,
                "display_name": str(user.get("name", "")),
                "store_name": str(trusted.get("store_name", "")),
                "source_type": source_type,
                "manual_trust_score": score,
                "trust_score": score,
                "confirmed": confirmed,
                "verification_status": "confirmed" if confirmed else "candidate",
                "application_url": url,
                "source_url": source_url,
                "evidence": [{
                    "source_type": source_type,
                    "source_url": source_url,
                    "account_username": username,
                    "tweet_id": str(tweet.get("id", "")),
                    "observed_at": self.now().isoformat(),
                }],
                "created_at": str(tweet.get("created_at", "")),
                **date_fields,
            })
        candidates = self._corroborate_with_web(candidates)
        newest = str(payload.get("meta", {}).get("newest_id", "")).strip()
        if newest:
            state[state_key] = {"since_id": newest, "retry_at": 0, "backoff_attempts": 0}
            self._save_state(state)
        if monitored_only:
            self._record_account_observations(
                accounts, candidates, users, payload.get("data", [])
            )
        return {
            "status": "ok", "candidates": candidates, "request_count": 1,
            "since_id": newest or since_id,
            "rate_limit_remaining": headers.get("x-rate-limit-remaining", ""),
        }

    def load_trusted_accounts(self) -> list[dict[str, Any]]:
        return self.accounts.load()

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
            trusted_result = self.search_trusted_accounts(tcg, bearer_token)
            results[f"trusted:{tcg}"] = trusted_result
            for item in trusted_result.get("candidates", []):
                key = (tcg, str(item.get("id", "")))
                previous = by_id.get(key)
                if previous:
                    item = self.deduplicate([previous], [item])[0]
                by_id[key] = item
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
                source_url = str(item.get("source_url", ""))
                source_urls = existing.setdefault("source_urls", [])
                if source_url and source_url not in source_urls:
                    source_urls.append(source_url)
                evidence = existing.setdefault("evidence", [])
                for value in item.get("evidence", []):
                    if isinstance(value, dict) and value not in evidence:
                        evidence.append(dict(value))
                existing["confidence"] = max(
                    float(existing.get("confidence", 0) or 0),
                    float(item.get("confidence", 0) or 0),
                )
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

    @staticmethod
    def _classify_post(text: str) -> str:
        normalized = re.sub(r"\s+", " ", str(text)).casefold()
        if re.search(
            r"買取|デッキレシピ|カードリスト|大会(?:結果|情報)?|"
            r"イベント|キャンペーン|相場|プレゼント企画|個人売買|"
            r"譲ります|交換希望|サプライ|スリーブ|プレイマット|"
            r"フィギュア|グッズ",
            normalized,
        ):
            return "IRRELEVANT"
        if re.search(r"抽選販売|web抽選|店頭抽選|抽選受付|応募受付|購入権|当選", normalized):
            return "LOTTERY"
        if re.search(r"予約受付|予約開始|予約中|受注|店頭受付", normalized):
            return "RESERVATION"
        if re.search(r"再販|再入荷|入荷しました|入荷情報", normalized):
            return "RESTOCK"
        if re.search(r"販売開始|発売開始|販売中|在庫あり", normalized):
            return "SALE"
        if re.search(r"抽選|予約|受付開始|受付中|応募", normalized):
            return "LOTTERY" if re.search(r"抽選|応募", normalized) else "RESERVATION"
        return "NEWS"

    @staticmethod
    def _extract_product_name(text: str) -> str:
        value = str(text)
        code = re.search(
            r"\b(?:(?:OP|EB|ST|PRB)-?\d{2,3}|(?:UA|EX)\d{2}(?:BT|ST|DC))\b",
            value,
            re.IGNORECASE,
        )
        quoted = re.search(r"[「『](.{2,80}?)[」』]", value)
        if quoted:
            return quoted.group(1).strip()
        return code.group(0).upper() if code else ""

    @staticmethod
    def _extract_date_fields(text: str, created_at: str) -> dict[str, str]:
        try:
            base_year = datetime.fromisoformat(created_at.replace("Z", "+00:00")).year
        except ValueError:
            base_year = datetime.now(timezone.utc).year
        values: list[str] = []
        for match in re.finditer(
            r"(?:(20\d{2})年)?\s*(\d{1,2})月\s*(\d{1,2})日"
            r"(?:\s*(\d{1,2})[:時](\d{2})?分?)?",
            str(text),
        ):
            year, month, day, hour, minute = match.groups()
            try:
                parsed = datetime(
                    int(year or base_year), int(month), int(day),
                    int(hour or 0), int(minute or 0),
                    tzinfo=timezone(timedelta(hours=9)),
                )
            except ValueError:
                continue
            values.append(parsed.isoformat())
        result: dict[str, str] = {}
        if values:
            result["application_start_at"] = values[0]
        if len(values) >= 2:
            result["application_end_at"] = values[1]
        return result

    def _record_account_observations(
        self,
        accounts: dict[str, dict[str, Any]],
        candidates: list[dict[str, Any]],
        users: dict[str, dict[str, Any]],
        tweets: list[dict[str, Any]],
    ) -> None:
        runtime = self.accounts.load_runtime_state()
        fetched_at = self.now().isoformat()
        candidates_by_username: dict[str, list[dict[str, Any]]] = {}
        for item in candidates:
            candidates_by_username.setdefault(
                str(item.get("username", "")).casefold(), []
            ).append(item)
        user_ids = {
            str(user.get("username", "")).casefold(): str(user.get("id", ""))
            for user in users.values()
        }
        usernames_by_user_id = {
            str(user.get("id", "")): str(user.get("username", "")).casefold()
            for user in users.values()
        }
        latest_by_username: dict[str, str] = {}
        for tweet in tweets:
            username = usernames_by_user_id.get(str(tweet.get("author_id", "")), "")
            tweet_id = str(tweet.get("id", ""))
            current_id = latest_by_username.get(username, "")
            if tweet_id.isdigit() and (
                not current_id.isdigit() or int(tweet_id) > int(current_id)
            ):
                latest_by_username[username] = tweet_id
        for username, account in accounts.items():
            key = f"{username}|{account.get('tcg', '')}"
            current = dict(runtime.get(key, {}))
            observed = candidates_by_username.get(username, [])
            if latest_by_username.get(username):
                current["latest_tweet_id"] = latest_by_username[username]
            current["user_id"] = user_ids.get(username) or current.get("user_id", "")
            current["last_fetched_at"] = fetched_at
            current["detected_count"] = int(current.get("detected_count", 0) or 0) + len(observed)
            current["confirmed_count"] = int(current.get("confirmed_count", 0) or 0) + sum(
                bool(item.get("confirmed")) for item in observed
            )
            current.setdefault("rejected_count", 0)
            current.setdefault("false_positive_count", 0)
            decided = int(current["confirmed_count"]) + int(current["rejected_count"])
            current["observed_accuracy"] = (
                round(int(current["confirmed_count"]) / decided, 4) if decided else None
            )
            runtime[key] = current
        self.accounts.save_runtime_state(runtime)

    def _corroborate_with_web(
        self, candidates: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        result = inspect_json_file(self.root / "data" / "candidates.json", list)
        if result.state == CORRUPT:
            return candidates
        web_items: list[dict[str, Any]] = []
        for product in result.data or []:
            if not isinstance(product, dict):
                continue
            for hit in product.get("retail_hits", []):
                if not isinstance(hit, dict):
                    continue
                status = str(hit.get("status", ""))
                if hit.get("period_ended") or re.search(
                    r"終了済み|受付終了|応募終了", status
                ):
                    continue
                web_items.append({
                    "tcg_key": str(product.get("tcg_key", "")),
                    "product_name": str(product.get("name", "")),
                    "store_name": str(hit.get("seller") or hit.get("name") or ""),
                    "application_url": str(
                        hit.get("application_url") or hit.get("url") or ""
                    ),
                    "application_end_at": str(hit.get("application_end_at", "")),
                    "confirmed": str(
                        hit.get("verification_status", "confirmed")
                    ) != "candidate",
                    "evidence": [
                        dict(value) for value in hit.get("source_evidence", [])
                        if isinstance(value, dict)
                    ],
                })
        output: list[dict[str, Any]] = []
        for candidate in candidates:
            item = dict(candidate)
            match = next(
                (web for web in web_items if self._same_case(web, item)), None
            )
            if match:
                evidence = item.setdefault("evidence", [])
                for value in match.get("evidence", []):
                    if value not in evidence:
                        evidence.append(dict(value))
                item["corroboration_status"] = (
                    "confirmed" if match.get("confirmed") else "candidate"
                )
                if match.get("confirmed"):
                    item["confirmed"] = True
                    item["verification_status"] = "confirmed"
                    item["confidence"] = max(
                        float(item.get("confidence", 0) or 0), 0.95
                    )
            else:
                item["corroboration_status"] = "candidate"
            output.append(item)
        return output

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
