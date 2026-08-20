from __future__ import annotations

import json
import hashlib
import os
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from core.json_file_state import CORRUPT, inspect_json_file
from core.runtime_paths import app_root
from core.secure_https import build_https_opener
from core.product_categories import detect_product_category
from core.trusted_x_accounts import (
    GENERAL_INFORMATION,
    OFFICIAL_MANUFACTURER,
    OFFICIAL_SHOP_BRANCH,
    OFFICIAL_STORE,
    TRUSTED_INFORMATION,
    TrustedXAccountRegistry,
)
from core.application_discovery import (
    normalize_evidence,
    normalize_store_reference,
    parse_discovery_post,
    resolve_candidate,
)


RECENT_SEARCH_URL = "https://api.x.com/2/tweets/search/recent"
USER_LOOKUP_URL = "https://api.x.com/2/users/by/username/{username}"
USER_TIMELINE_URL = "https://api.x.com/2/users/{user_id}/tweets"
COMMON_TERMS = (
    "抽選", "予約", "受付", "再販", "再入荷", "入荷", "販売", "先着", "応募",
    "WEB抽選", "店頭抽選", "予約受付", "販売開始", "入荷予定", "受付開始",
    "締切変更", "販売中止",
)
TCG_DEFINITIONS = {
    "pokemon": {"label": "Pokemon", "terms": ("ポケモンカード", "ポケカ")},
    "onepiece": {"label": "ONE PIECE", "terms": ("ONE PIECEカード", "ワンピースカード")},
    "union_arena": {"label": "UNION ARENA", "terms": ("UNION ARENA", "ユニオンアリーナ", "ユニアリ")},
    "dragon_ball_fusion_world": {
        "label": "Dragon Ball Super Card Game Fusion World",
        "terms": ("FUSION WORLD", "フュージョンワールド", "DBSCG FW", "DBFW"),
    },
}
QUERIES = {
    "pokemon": '("ポケモンカード" OR ポケカ) (' + " OR ".join(COMMON_TERMS) + ') -is:retweet',
    "onepiece": '("ONE PIECEカード" OR "ワンピースカード") (' + " OR ".join(COMMON_TERMS) + ') -is:retweet',
    "union_arena": '("UNION ARENA" OR ユニオンアリーナ OR ユニアリ) (' + " OR ".join(COMMON_TERMS) + ') -is:retweet',
    "dragon_ball_fusion_world": '("ドラゴンボールスーパーカードゲーム フュージョンワールド" OR "DBSCG FUSION WORLD" OR "DBSCG FW") (' + " OR ".join(COMMON_TERMS) + ') -is:retweet',
}
OFFICIAL_EVIDENCE_TYPES = {
    "official_product_page", "official_store_page", "official_ec",
    "official_application_page", "official_x", "premium_bandai",
}
CONFIRMING_EVIDENCE_TYPES = {
    "official_store_page", "official_ec", "official_application_page",
    "premium_bandai",
}
REJECTING_STATUSES = {"rejected", "cancelled", "canceled", "ended", "not_available"}


class XRecentSearch:
    """Optional X API v2 collector. It never scrapes X web pages."""

    def __init__(
        self,
        root: Path | None = None,
        *,
        opener=None,
        now: Callable[[], datetime] | None = None,
        jitter: Callable[[float, float], float] | None = None,
    ) -> None:
        self.root = Path(root) if root is not None else app_root()
        self.state_path = self.root / "cache" / "x_recent_search_state.json"
        self.account_path = self.root / "config" / "trusted_x_accounts.json"
        self.accounts = TrustedXAccountRegistry(self.root)
        self.opener = opener or build_https_opener()
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.jitter = jitter or random.uniform

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
                f"({from_terms}) ({' OR '.join(COMMON_TERMS)} OR 受注) "
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

    def poll_trusted_account_timelines(
        self, tcg: str, bearer_token: str | None = None
    ) -> dict[str, Any]:
        """user timelineをTTL付きで差分取得する。X Webにはアクセスしない。"""
        if tcg not in QUERIES:
            raise ValueError("X検索対象TCGが未対応です。")
        token = (bearer_token or os.environ.get("POKEYOYA_X_BEARER_TOKEN", "")).strip()
        if not token:
            return {
                "status": "disabled", "candidates": [], "request_count": 0,
                "cache_hits": 0, "cache_misses": 0,
                "notice": "X監視が無効のため抽選Discovery範囲が制限されています",
            }
        accounts = [
            account for account in self.accounts.load_with_observations()
            if account.get("enabled", True) and account.get("tcg") == tcg
        ]
        runtime = self.accounts.load_runtime_state()
        candidates: list[dict[str, Any]] = []
        request_count = 0
        cache_hits = 0
        cache_misses = 0
        statuses: list[str] = []
        last_headers: dict[str, Any] = {}
        for account in accounts:
            if request_count >= 4:
                statuses.append("budget_exhausted")
                break
            key = "|".join(self.accounts._key(account))
            observed = dict(runtime.get(key, {}))
            if not self._account_due(account, observed):
                cache_hits += 1
                continue
            cache_misses += 1
            result = self._poll_account_timeline(account, observed, token)
            statuses.append(str(result.get("status", "")))
            request_count += int(result.get("request_count", 0))
            candidates.extend(result.get("candidates", []))
            last_headers = result
            if result.get("status") == "rate_limited":
                break
        status = "ok"
        if statuses and any(value == "rate_limited" for value in statuses):
            status = "rate_limited"
        elif not statuses and accounts:
            status = "cached"
        elif not accounts:
            status = "disabled"
        return {
            "status": status,
            "candidates": candidates,
            "request_count": request_count,
            "cache_hits": cache_hits,
            "cache_misses": cache_misses,
            "rate_limit_remaining": last_headers.get("rate_limit_remaining", ""),
            "rate_limit_limit": last_headers.get("rate_limit_limit", ""),
            "rate_limit_reset": last_headers.get("rate_limit_reset", ""),
        }

    def search_trusted_timeline(
        self, account: dict[str, Any], bearer_token: str | None = None
    ) -> dict[str, Any]:
        """Fetch one trusted timeline while preserving legacy TTL/since_id state."""
        token = (bearer_token or os.environ.get("POKEYOYA_X_BEARER_TOKEN", "")).strip()
        if not token:
            return {"status": "disabled", "candidates": [], "request_count": 0}
        username = str(account.get("username", ""))
        tcg = str(account.get("tcg", ""))
        key = f"{username.casefold()}:{tcg}"
        state = self._load_state()
        timeline = dict(state.get("timeline", {}))
        current = dict(timeline.get(key, {}))
        last_request = float(current.get("last_request_at", 0) or 0)
        if last_request and time.time() - last_request < 300:
            return {"status": "ttl", "candidates": [], "request_count": 0}
        runtime_key = "|".join(self.accounts._key(account))
        observed = dict(self.accounts.load_runtime_state().get(runtime_key, {}))
        if not observed.get("user_id"):
            observed["user_id"] = str(
                state.get("user_ids", {}).get(username.casefold(), "")
            )
        result = self._poll_account_timeline(account, observed, token)
        if result.get("status") == "ok":
            state = self._load_state()
            timeline = dict(state.get("timeline", {}))
            timeline[key] = {
                "since_id": result.get("since_id", current.get("since_id", "")),
                "last_request_at": time.time(),
            }
            state["timeline"] = timeline
            saved = dict(self.accounts.load_runtime_state().get(runtime_key, {}))
            user_id = str(saved.get("user_id", ""))
            if user_id:
                user_ids = dict(state.get("user_ids", {}))
                user_ids[username.casefold()] = user_id
                state["user_ids"] = user_ids
            self._save_state(state)
        return result

    def _next_timeline_account(
        self, accounts: list[dict[str, Any]], tcg: str
    ) -> dict[str, Any] | None:
        eligible = [
            item for item in accounts
            if item.get("enabled", True) and item.get("tcg") == tcg
        ]
        if not eligible:
            return None
        state = self._load_state()
        rotation = dict(state.get("timeline_rotation", {}))
        index = int(rotation.get(tcg, 0) or 0) % len(eligible)
        rotation[tcg] = (index + 1) % len(eligible)
        state["timeline_rotation"] = rotation
        self._save_state(state)
        return eligible[index]

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
            return self._record_rate_limit(state, state_key, item_state, error.headers)
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
        candidates = self._build_candidates(
            tcg, payload.get("data", []), users, accounts,
            monitored_only=monitored_only,
        )
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
            "rate_limit_limit": headers.get("x-rate-limit-limit", ""),
            "rate_limit_reset": headers.get("x-rate-limit-reset", ""),
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
            timeline_result = self.poll_trusted_account_timelines(tcg, bearer_token)
            results[f"timeline:{tcg}"] = timeline_result
            for item in timeline_result.get("candidates", []):
                key = (tcg, str(item.get("id", "")))
                previous = by_id.get(key)
                if previous:
                    item = self.deduplicate([previous], [item])[0]
                by_id[key] = item
        verified = self._coalesce_updates(list(by_id.values()))
        if verified != existing:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".json.tmp")
            temporary.write_text(
                json.dumps(verified, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temporary.replace(path)
        promoted_count = self._promote_confirmed(verified)
        statuses = [str(value.get("status", "")) for value in results.values()]
        disabled = bool(statuses) and all(value == "disabled" for value in statuses)
        return {
            "status": "disabled" if disabled else "ok",
            "notice": (
                "X監視が無効のため抽選Discovery範囲が制限されています"
                if disabled else ""
            ),
            "results": results,
            "candidate_count": len(verified),
            "confirmed_count": sum(bool(item.get("confirmed")) for item in verified),
            "rejected_count": sum(
                item.get("verification_status") == "rejected" for item in verified
            ),
            "promoted_count": promoted_count,
            "request_count": sum(
                int(value.get("request_count", 0)) for value in results.values()
            ),
            "cache_hits": sum(int(value.get("cache_hits", 0)) for value in results.values()),
            "cache_misses": sum(int(value.get("cache_misses", 0)) for value in results.values()),
        }

    def _candidate(
        self, tweet: dict[str, Any], user: dict[str, Any], tcg: str
    ) -> dict[str, Any] | None:
        """Compatibility builder for one X post; it can never self-confirm."""
        if tcg not in TCG_DEFINITIONS:
            return None
        text = str(tweet.get("text", "")).strip()
        if not any(
            term.casefold() in text.casefold()
            for term in TCG_DEFINITIONS[tcg]["terms"]
        ) or not any(term in text for term in COMMON_TERMS):
            return None
        classification = self._classify_post(text)
        if classification == "IRRELEVANT":
            return None
        username = str(user.get("username", ""))
        trusted = next(
            (
                item for item in self.load_trusted_accounts()
                if item.get("enabled", True)
                and str(item.get("username", "")).casefold() == username.casefold()
                and item.get("tcg") == tcg
            ),
            {},
        )
        external_url = self._first_external_url(tweet)
        parsed = parse_discovery_post(
            text, tcg_hint=tcg, created_at=str(tweet.get("created_at", ""))
        )
        score = int(trusted.get("manual_trust_score", 30) or 30)
        post_id = str(tweet.get("id", ""))
        source_url = f"https://x.com/{username}/status/{post_id}"
        product_text = str(parsed.get("product_name") or text.splitlines()[0])[:300]
        return {
            "id": post_id,
            "source_type": (
                "official_x"
                if str(trusted.get("trust_level", "")).startswith("OFFICIAL_")
                else "trusted_store_x" if trusted else "x_api"
            ),
            "source_url": source_url,
            "x_post_id": post_id,
            "x_account": username,
            "detected_at": self.now().isoformat(),
            "tcg": TCG_DEFINITIONS[tcg]["label"],
            "tcg_key": tcg,
            "product_text": product_text,
            "product_name": product_text,
            "store_text": str(trusted.get("store_name", "")),
            "store_name": str(trusted.get("store_name", "")),
            "product_category": detect_product_category(text),
            "sales_method_hint": self.infer_sales_method(text, external_url),
            "deadline_hint": str(parsed.get("application_end_at", "")),
            "confidence": score,
            "evidence": [{"source_type": "x_api", "url": source_url, "text": text}],
            "verification_status": "pending",
            "confirmed": False,
            "information_type": (
                "RESTOCK" if classification == "RESTOCK" else "APPLICATION"
            ),
            "application_type": classification,
            "lifecycle_status": (
                "cancelled" if classification == "CANCELLED"
                else "changed" if "締切変更" in text else "active"
            ),
            "text": text,
            "username": username,
            "display_name": str(user.get("name", trusted.get("display_name", ""))),
            "trust_level": str(trusted.get("trust_level", "INFO_ACCOUNT")),
            "trust_score": score,
            "application_url": external_url,
            "created_at": str(tweet.get("created_at", "")),
            "prefecture": "UNKNOWN",
        }

    def verify_candidate(
        self,
        candidate: dict[str, Any],
        official_evidence: Iterable[dict[str, Any]],
    ) -> dict[str, Any]:
        """Verify against non-X official evidence; X evidence alone is insufficient."""
        result = dict(candidate)
        result.update({"confirmed": False, "verification_status": "pending"})
        if (
            result.get("lifecycle_status") == "cancelled"
            and result.get("trust_level") != "INFO_ACCOUNT"
        ):
            result["verification_status"] = "rejected"
            return result
        for evidence in official_evidence:
            if not isinstance(evidence, dict) or not self._official_match(result, evidence):
                continue
            kind = str(evidence.get("source_type", ""))
            url = str(
                evidence.get("url") or evidence.get("application_url")
                or evidence.get("official_url") or ""
            )
            if kind not in OFFICIAL_EVIDENCE_TYPES or not self._normalized_url(url):
                continue
            saved = result.setdefault("evidence", [])
            record = {"source_type": kind, "url": url}
            if record not in saved:
                saved.append(record)
            if str(evidence.get("status", "")).casefold() in REJECTING_STATUSES:
                result["verification_status"] = "rejected"
                return result
            if kind not in CONFIRMING_EVIDENCE_TYPES:
                continue
            result.update({"verification_status": "confirmed", "confirmed": True})
            result["confidence"] = min(100, int(result.get("confidence", 0) or 0) + 15)
            if not result.get("application_url"):
                result["application_url"] = url
            if str(evidence.get("prefecture", "")).strip():
                result["prefecture"] = str(evidence["prefecture"]).strip()
            return result
        return result

    @classmethod
    def _coalesce_updates(cls, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        cases: dict[tuple[str, ...], dict[str, Any]] = {}
        for raw in sorted(
            items,
            key=lambda item: str(item.get("detected_at", item.get("created_at", ""))),
        ):
            item = dict(raw)
            application_url = cls._normalized_url(item.get("application_url", ""))
            if application_url:
                key = (str(item.get("tcg_key", "")), application_url)
            else:
                key = (
                    str(item.get("tcg_key", "")),
                    str(item.get("x_account", item.get("username", ""))).casefold(),
                    cls._normalized_case_text(
                        item.get("product_text", item.get("product_name", ""))
                    ),
                    cls._normalized_case_text(
                        item.get("store_text", item.get("store_name", ""))
                    ),
                )
            previous = cases.get(key)
            if previous is not None:
                item["evidence"] = cls._merge_evidence(
                    previous.get("evidence", []), item.get("evidence", [])
                )
                item["x_post_ids"] = list(dict.fromkeys([
                    *previous.get(
                        "x_post_ids",
                        [previous.get("x_post_id", previous.get("id", ""))],
                    ),
                    item.get("x_post_id", item.get("id", "")),
                ]))
                item["updated_existing_application"] = True
            cases[key] = item
        return list(cases.values())

    @staticmethod
    def _normalized_case_text(value: Any) -> str:
        return re.sub(r"[^0-9a-zA-Zぁ-んァ-ヶ一-龠]", "", str(value)).casefold()

    @staticmethod
    def _merge_evidence(left: Any, right: Any) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for item in [
            *(left if isinstance(left, list) else []),
            *(right if isinstance(right, list) else []),
        ]:
            if not isinstance(item, dict):
                continue
            key = (
                str(item.get("source_type", "")),
                str(item.get("url", item.get("source_url", ""))),
            )
            if key in seen:
                continue
            seen.add(key)
            output.append(dict(item))
        return output

    def _promote_confirmed(self, items: list[dict[str, Any]]) -> int:
        discovered = []
        for item in items:
            if item.get("verification_status") != "confirmed" or not item.get("confirmed"):
                continue
            application_url = str(item.get("application_url", "")).strip()
            product_text = str(
                item.get("product_text", item.get("product_name", ""))
            ).strip()
            if not self._normalized_url(application_url) or not product_text:
                continue
            product_id = "x-" + hashlib.sha256(
                f'{item.get("tcg_key", "")}|{product_text}'.encode("utf-8")
            ).hexdigest()[:20]
            site_key = "x-app-" + hashlib.sha256(
                application_url.encode("utf-8")
            ).hexdigest()[:16]
            discovered.append({
                "id": product_id,
                "name": product_text,
                "tcg_key": item.get("tcg_key", "other"),
                "tcg": item.get("tcg", "その他"),
                "product_category": item.get("product_category", "CARD"),
                "verification_status": "confirmed",
                "confirmed": True,
                "detected_at": item.get("detected_at", item.get("created_at", "")),
                "source_type": item.get("source_type", "x_api"),
                "source_url": item.get("source_url", ""),
                "sites": [{
                    "id": site_key,
                    "site_key": site_key,
                    "name": item.get("store_text") or item.get("store_name") or "公式販売ページ",
                    "url": application_url,
                    "application_url": application_url,
                    "application_status": item.get("information_type", "APPLICATION"),
                    "application_end_at": item.get(
                        "deadline_hint", item.get("application_end_at", "")
                    ),
                    "sales_mode": item.get("sales_method_hint", "UNKNOWN"),
                    "prefecture": item.get("prefecture", "UNKNOWN"),
                    "verification_status": "confirmed",
                    "confirmed": True,
                    "confidence": item.get("confidence", 0),
                    "evidence": item.get("evidence", []),
                    "source_type": item.get("source_type", "x_api"),
                    "source_account": item.get("x_account", item.get("username", "")),
                    "source_url": item.get("source_url", ""),
                    "x_post_id": item.get("x_post_id", item.get("id", "")),
                    "detected_at": item.get("detected_at", item.get("created_at", "")),
                }],
            })
        if not discovered:
            return 0
        from core.product_store import ProductStore

        _products, added = ProductStore(self.root).merge_discovered_products(discovered)
        return int(added)

    @staticmethod
    def infer_sales_method(text: str, url: str = "") -> str:
        online = bool(re.search(r"WEB|Web|web|オンライン|通販|EC", text)) or bool(url)
        store = bool(re.search(r"店頭|店舗|レジ|整理券", text))
        return (
            "HYBRID" if online and store else "ONLINE" if online
            else "STORE" if store else "UNKNOWN"
        )

    @staticmethod
    def _official_match(candidate: dict[str, Any], evidence: dict[str, Any]) -> bool:
        if str(candidate.get("tcg_key", "")).casefold() != str(
            evidence.get("tcg_key", "")
        ).casefold():
            return False
        candidate_url = XRecentSearch._normalized_url(candidate.get("application_url", ""))
        evidence_url = XRecentSearch._normalized_url(
            evidence.get("url") or evidence.get("application_url")
            or evidence.get("official_url") or ""
        )
        if candidate_url and candidate_url == evidence_url:
            return True
        norm = XRecentSearch._normalized_case_text
        product = norm(candidate.get("product_text", candidate.get("product_name", "")))
        official_product = norm(
            evidence.get("product_text", evidence.get("product_name", evidence.get("name", "")))
        )
        store = norm(candidate.get("store_text", candidate.get("store_name", "")))
        official_store = norm(
            evidence.get("store_text", evidence.get("store_name", ""))
        )
        return bool(
            product and official_product
            and (product in official_product or official_product in product)
            and (
                not store or not official_store
                or store in official_store or official_store in store
            )
        )

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
        if re.search(r"販売中止|受付中止|予約中止|抽選中止", normalized):
            return "CANCELLED"
        if re.search(
            r"買取|デッキレシピ|カードリスト|大会(?:結果|情報)?|"
            r"対戦会|相場|キャンペーン|プレゼント企画|"
            r"個人売買|譲ります|交換希望|"
            r"フィギュア",
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
            r"\b(?:(?:OP|EB|ST|PRB)-?\d{2,3}|(?:UA|EX)\d{2}(?:BT|ST|DC)|"
            r"(?:FB|FS|SB|ST)\d{2})\b",
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
                current["last_seen_tweet_id"] = latest_by_username[username]
            current["user_id"] = user_ids.get(username) or current.get("user_id", "")
            current["last_fetched_at"] = fetched_at
            current["last_checked_at"] = fetched_at
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

    def _build_candidates(
        self,
        tcg: str,
        tweets: list[dict[str, Any]],
        users: dict[str, dict[str, Any]],
        accounts: dict[str, dict[str, Any]],
        *,
        monitored_only: bool,
    ) -> list[dict[str, Any]]:
        candidates = []
        for tweet in tweets:
            if not isinstance(tweet, dict):
                continue
            user = users.get(str(tweet.get("author_id", "")), {})
            username = str(user.get("username", ""))
            trusted = accounts.get(username.casefold(), {})
            if monitored_only and not trusted:
                continue
            score = int(trusted.get("manual_trust_score", 30) or 30)
            text = str(tweet.get("text", ""))
            parsed = parse_discovery_post(
                text, tcg_hint=tcg, created_at=str(tweet.get("created_at", ""))
            )
            classification = str(parsed.get("application_type", "NEWS"))
            product_category = detect_product_category(text)
            if classification == "IRRELEVANT" and product_category != "CARD":
                classification = self._classify_post(
                    text.replace("キャンペーン", "")
                )
            if classification == "IRRELEVANT":
                continue
            account_source_type = str(
                trusted.get("source_type", GENERAL_INFORMATION)
            )
            source_url = f"https://x.com/{username}/status/{tweet.get('id', '')}"
            application_url = self._first_external_url(tweet) or str(
                parsed.get("application_url", "")
            )
            trusted_store_name = str(trusted.get("store_name", "")).strip()
            if trusted_store_name:
                store = normalize_store_reference(trusted_store_name, application_url)
            else:
                store = {
                    key: parsed[key] for key in (
                        "store_id", "canonical_store_id", "store_name", "branch",
                        "store_match_confidence", "store_ambiguous",
                    ) if key in parsed
                }
                if not store:
                    store = normalize_store_reference("", application_url)
            extracted_fields = {
                key: parsed.get(key, "") for key in (
                    "tcg_key", "product_name", "product_code", "application_start_at",
                    "application_end_at", "result_announcement_at", "purchase_period",
                    "application_url", "store_name", "branch",
                )
            }
            evidence = normalize_evidence({
                "source_type": "X_API",
                "source_url": source_url,
                "observed_at": self.now().isoformat(),
                "trust": score,
                "extracted_fields": extracted_fields,
                "verification_status": "observed",
            })
            item = {
                "id": str(tweet.get("id", "")),
                "x_post_id": str(tweet.get("id", "")),
                "x_account": username,
                "tcg_key": tcg,
                "tcg": TCG_DEFINITIONS[tcg]["label"],
                "information_type": "RESTOCK" if classification == "RESTOCK" else (
                    "APPLICATION" if classification in {"LOTTERY", "RESERVATION"} else "NEWS"
                ),
                "application_type": classification,
                "text": text,
                "product_name": parsed.get("product_name", ""),
                "product_text": parsed.get("product_name", "") or text.splitlines()[0][:300],
                "product_code": parsed.get("product_code", ""),
                "product_category": product_category,
                "username": username,
                "display_name": str(user.get("name", trusted.get("display_name", ""))),
                "store_text": str(store.get("store_name", "")),
                "source_type": (
                    "official_x"
                    if str(trusted.get("trust_level", "")).startswith("OFFICIAL_")
                    else "trusted_store_x" if trusted else "x_api"
                ),
                "account_source_type": account_source_type,
                "manual_trust_score": score,
                "trust_score": score,
                "trust_level": str(trusted.get("trust_level", "INFO_ACCOUNT")),
                "application_url": application_url,
                "source_url": source_url,
                "evidence": [evidence],
                "created_at": str(tweet.get("created_at", "")),
                "detected_at": self.now().isoformat(),
                "deadline_hint": str(parsed.get("application_end_at", "")),
                "sales_method_hint": self.infer_sales_method(text, application_url),
                "lifecycle_status": (
                    "cancelled" if classification == "CANCELLED"
                    else "changed" if "締切変更" in text else "active"
                ),
                "prefecture": "UNKNOWN",
                **store,
                **{
                    key: value for key, value in parsed.items()
                    if key.endswith("_at") or key == "purchase_period"
                },
            }
            resolved = resolve_candidate(item)
            if classification == "CANCELLED" and trusted:
                resolved.update({"verification_status": "rejected", "confirmed": False})
            else:
                resolved.update({"verification_status": "candidate", "confirmed": False})
            candidates.append(resolved)
        return candidates

    def _poll_account_timeline(
        self, account: dict[str, Any], observed: dict[str, Any], token: str
    ) -> dict[str, Any]:
        username = str(account.get("username", ""))
        state = self._load_state()
        state_key = f"timeline:{username.casefold()}:{account.get('tcg', '')}"
        backoff = dict(state.get(state_key, {}))
        retry_at = float(backoff.get("retry_at", 0) or 0)
        if retry_at > time.time():
            return {
                "status": "backoff", "candidates": [], "request_count": 0,
                "retry_after": max(1, int(retry_at - time.time())),
            }
        user_id = str(account.get("user_id") or observed.get("user_id") or "")
        requests = 0
        headers: Any = {}
        try:
            if not user_id:
                lookup = urllib.request.Request(
                    USER_LOOKUP_URL.format(username=urllib.parse.quote(username))
                    + "?user.fields=username,name,verified",
                    headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                )
                with self.opener.open(lookup, timeout=20) as response:
                    payload = json.loads(response.read(1_000_000).decode("utf-8"))
                    headers = response.headers
                requests += 1
                user = payload.get("data", {}) if isinstance(payload, dict) else {}
                if not isinstance(user, dict):
                    user = {}
                user_id = str(user.get("id", ""))
                if not user_id:
                    return {"status": "user_not_found", "candidates": [], "request_count": requests}
            params = {
                "max_results": "20",
                "exclude": "retweets,replies",
                "tweet.fields": "created_at,author_id,entities",
                "expansions": "author_id",
                "user.fields": "username,name,verified",
            }
            since_id = str(
                observed.get("last_seen_tweet_id", observed.get("latest_tweet_id", ""))
            ).strip()
            if since_id:
                params["since_id"] = since_id
            request = urllib.request.Request(
                USER_TIMELINE_URL.format(user_id=urllib.parse.quote(user_id))
                + "?" + urllib.parse.urlencode(params),
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            )
            with self.opener.open(request, timeout=20) as response:
                payload = json.loads(response.read(2_000_000).decode("utf-8"))
                headers = response.headers
            requests += 1
        except urllib.error.HTTPError as error:
            if error.code != 429:
                raise
            limited = self._record_rate_limit(
                state, state_key, dict(state.get(state_key, {})), error.headers
            )
            limited["request_count"] = requests + 1
            return limited
        users = {
            str(item.get("id", "")): item
            for item in payload.get("includes", {}).get("users", [])
            if isinstance(item, dict)
        }
        if user_id not in users:
            users[user_id] = {
                "id": user_id, "username": username,
                "name": str(account.get("display_name", "")),
            }
        account_map = {username.casefold(): account}
        candidates = self._build_candidates(
            str(account.get("tcg", "")), payload.get("data", []), users,
            account_map, monitored_only=True,
        )
        candidates = self._corroborate_with_web(candidates)
        newest = str(payload.get("meta", {}).get("newest_id", ""))
        self.accounts.record_fetch(
            account,
            tweet_id=newest or str(observed.get("last_seen_tweet_id", "")),
            fetched_at=self.now().isoformat(),
            detected_delta=len(candidates),
            confirmed_delta=sum(bool(item.get("confirmed")) for item in candidates),
        )
        runtime = self.accounts.load_runtime_state()
        runtime_key = "|".join(self.accounts._key(account))
        current = dict(runtime.get(runtime_key, {}))
        current["user_id"] = user_id
        runtime[runtime_key] = current
        self.accounts.save_runtime_state(runtime)
        return {
            "status": "ok", "candidates": candidates, "request_count": requests,
            "since_id": newest or str(observed.get("last_seen_tweet_id", "")),
            "rate_limit_remaining": headers.get("x-rate-limit-remaining", ""),
            "rate_limit_limit": headers.get("x-rate-limit-limit", ""),
            "rate_limit_reset": headers.get("x-rate-limit-reset", ""),
        }

    def _account_due(self, account: dict[str, Any], observed: dict[str, Any]) -> bool:
        value = str(observed.get("last_checked_at", observed.get("last_fetched_at", "")))
        if not value:
            return True
        try:
            checked = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if checked.tzinfo is None:
                checked = checked.replace(tzinfo=timezone.utc)
        except ValueError:
            return True
        ttl = {
            OFFICIAL_MANUFACTURER: 3600,
            OFFICIAL_STORE: 1800,
            OFFICIAL_SHOP_BRANCH: 900,
            TRUSTED_INFORMATION: 600,
            GENERAL_INFORMATION: 1800,
        }.get(str(account.get("source_type", "")), 1800)
        return (self.now() - checked.astimezone(timezone.utc)).total_seconds() >= ttl

    def _record_rate_limit(
        self, state: dict[str, Any], key: str, item_state: dict[str, Any], headers: Any
    ) -> dict[str, Any]:
        attempts = min(6, int(item_state.get("backoff_attempts", 0)) + 1)
        reset = int(headers.get("x-rate-limit-reset", "0") or 0)
        retry_after = int(headers.get("Retry-After", "0") or 0)
        delay = max(60, min(3600, (2 ** attempts) * 30))
        delay += int(self.jitter(0, min(30, delay * 0.1)))
        retry_at = max(time.time() + delay, time.time() + retry_after, float(reset))
        state[key] = {**item_state, "retry_at": retry_at, "backoff_attempts": attempts}
        self._save_state(state)
        return {
            "status": "rate_limited", "candidates": [], "request_count": 1,
            "rate_limit_429": 1,
            "retry_after": max(1, int(retry_at - time.time())),
            "rate_limit_remaining": headers.get("x-rate-limit-remaining", ""),
            "rate_limit_limit": headers.get("x-rate-limit-limit", ""),
            "rate_limit_reset": headers.get("x-rate-limit-reset", ""),
        }

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
                source_url = str(
                    hit.get("source_url") or hit.get("application_url")
                    or hit.get("url") or ""
                )
                source_evidence = [
                    dict(value) for value in hit.get("source_evidence", [])
                    if isinstance(value, dict)
                ]
                if not source_evidence and source_url:
                    source_evidence = [{
                        "source_type": str(hit.get("source_type", OFFICIAL_STORE)),
                        "source_url": source_url,
                        "observed_at": str(hit.get("checked_at", self.now().isoformat())),
                        "trust": int(hit.get("trust_score", 95) or 95),
                        "verification_status": str(
                            hit.get("verification_status", "confirmed")
                        ),
                    }]
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
                    "evidence": source_evidence,
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
            resolved = resolve_candidate(item)
            if not match or not match.get("confirmed"):
                resolved.update({"verification_status": "pending", "confirmed": False})
            output.append(resolved)
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
