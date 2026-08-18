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
from typing import Any, Callable, Iterable

from core.json_file_state import CORRUPT, inspect_json_file
from core.runtime_paths import app_root, bundled_root
from core.secure_https import build_https_opener

RECENT_SEARCH_URL = "https://api.x.com/2/tweets/search/recent"
USER_TIMELINE_URL = "https://api.x.com/2/users/{user_id}/tweets"
USER_LOOKUP_URL = "https://api.x.com/2/users/by/username/{username}"
COMMON_TERMS = ("抽選", "予約", "受付", "再販", "再入荷", "入荷", "販売", "先着", "応募",
                "WEB抽選", "店頭抽選", "予約受付", "販売開始", "入荷予定")
TCG_DEFINITIONS = {
    "pokemon": {"label": "Pokemon", "terms": ("ポケモンカード", "ポケカ")},
    "onepiece": {"label": "ONE PIECE", "terms": ("ONE PIECEカード", "ワンピースカード")},
    "union_arena": {"label": "UNION ARENA", "terms": ("UNION ARENA", "ユニオンアリーナ", "ユニアリ")},
    "dragon_ball_fusion_world": {"label": "Dragon Ball Super Card Game Fusion World",
                                 "terms": ("FUSION WORLD", "フュージョンワールド", "DBFW")},
}
QUERIES = {
    key: "(" + " OR ".join(f'\"{term}\"' for term in value["terms"])
    + ") (" + " OR ".join(COMMON_TERMS) + ") -is:retweet"
    for key, value in TCG_DEFINITIONS.items()
}
EXCLUSIONS = (re.compile(r"(?:大会|対戦会|イベント).{0,8}(?:開催|参加|募集|結果)"),
              re.compile(r"買取|価格表|デッキレシピ|プレゼント企画"))
OFFICIAL_TYPES = {"official_product_page", "official_store_page", "official_ec",
                  "official_application_page", "official_x", "premium_bandai"}
CONFIRMING_TYPES = {"official_store_page", "official_ec", "official_application_page",
                    "premium_bandai"}
REJECTING_STATUSES = {"rejected", "cancelled", "canceled", "ended", "not_available"}


class XRecentSearch:
    """X API v2 discovery collector. X web pages are never scraped here."""

    def __init__(self, root: Path | None = None, *, opener=None,
                 now: Callable[[], datetime] | None = None) -> None:
        self.root = Path(root) if root is not None else app_root()
        self.state_path = self.root / "cache" / "x_recent_search_state.json"
        self.account_path = self.root / "config" / "trusted_x_accounts.json"
        self.opener = opener or build_https_opener()
        self.now = now or (lambda: datetime.now(timezone.utc))

    def search(self, tcg: str, bearer_token: str | None = None) -> dict[str, Any]:
        if tcg not in QUERIES:
            raise ValueError("未対応のTCGです。")
        token = self._token(bearer_token)
        if not token:
            return self._empty("disabled")
        state = self._load_state()
        item_state = dict(state.get("recent", {}).get(tcg, {}))
        if self._in_backoff(item_state):
            return {**self._empty("backoff"),
                    "retry_after": max(1, int(float(item_state["retry_at"]) - time.time()))}
        params = {"query": QUERIES[tcg], "max_results": "100",
                  "tweet.fields": "created_at,author_id,entities", "expansions": "author_id",
                  "user.fields": "username,name,verified"}
        since_id = str(item_state.get("since_id", "")).strip()
        if since_id:
            params["since_id"] = since_id
        else:
            params["start_time"] = (self.now() - timedelta(days=7)).replace(
                microsecond=0).isoformat().replace("+00:00", "Z")
        return self._request(RECENT_SEARCH_URL, params, token, tcg, state, "recent",
                             item_state, since_id)

    def search_trusted_timeline(self, account: dict[str, Any],
                                bearer_token: str | None = None) -> dict[str, Any]:
        """Read a configured official account timeline through X API v2 only."""
        token = self._token(bearer_token)
        if not token:
            return self._empty("disabled")
        user_id, tcg = str(account.get("user_id", "")).strip(), str(account.get("tcg", ""))
        username = str(account.get("username", "")).strip()
        if tcg not in QUERIES or not username:
            return self._empty("not_configured")
        lookup_requests = 0
        if not user_id:
            user_id, lookup = self._resolve_user_id(username, token)
            lookup_requests = int(lookup.get("request_count", 0))
            if not user_id:
                return lookup
        state = self._load_state()
        key = f"{username.casefold()}:{tcg}"
        item_state = dict(state.get("timeline", {}).get(key, {}))
        if self._in_backoff(item_state):
            return {**self._empty("backoff"),
                    "retry_after": max(1, int(float(item_state["retry_at"]) - time.time()))}
        if time.time() - float(item_state.get("last_request_at", 0) or 0) < 900:
            return self._empty("ttl")
        params = {"max_results": "100", "exclude": "retweets,replies",
                  "tweet.fields": "created_at,author_id,entities"}
        since_id = str(item_state.get("since_id", "")).strip()
        if since_id:
            params["since_id"] = since_id
        fixed_user = {"id": user_id, "username": username,
                      "name": account.get("display_name", "")}
        result = self._request(USER_TIMELINE_URL.format(user_id=urllib.parse.quote(user_id)),
                               params, token, tcg, state, "timeline", item_state, since_id,
                               fixed_user=fixed_user, state_key=key)
        result["request_count"] = int(result.get("request_count", 0)) + lookup_requests
        return result

    def _resolve_user_id(self, username: str, token: str) -> tuple[str, dict[str, Any]]:
        state = self._load_state()
        cached = str(state.get("user_ids", {}).get(username.casefold(), "")).strip()
        if cached:
            return cached, self._empty("cached")
        lookup_state = dict(state.get("timeline_lookup", {}).get(username.casefold(), {}))
        if self._in_backoff(lookup_state):
            return "", {**self._empty("backoff"),
                        "retry_after": max(1, int(float(lookup_state["retry_at"]) - time.time()))}
        request = urllib.request.Request(
            USER_LOOKUP_URL.format(username=urllib.parse.quote(username)),
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
        try:
            with self.opener.open(request, timeout=20) as response:
                payload = json.loads(response.read(500_000).decode("utf-8"))
        except urllib.error.HTTPError as error:
            if error.code == 429:
                retry_at = self._set_backoff(state, "timeline_lookup", username.casefold(),
                                             lookup_state, error.headers)
                return "", {**self._empty("rate_limited"), "request_count": 1,
                            "rate_limit_429": 1,
                            "retry_after": max(1, int(retry_at - time.time()))}
            return "", {**self._empty("error"), "request_count": 1,
                        "exception_count": 1, "http_status": error.code}
        except (OSError, ValueError, json.JSONDecodeError):
            return "", {**self._empty("error"), "request_count": 1, "exception_count": 1}
        data = payload.get("data", {}) if isinstance(payload, dict) else {}
        user_id = str(data.get("id", "")).strip() if isinstance(data, dict) else ""
        if not user_id:
            return "", {**self._empty("error"), "request_count": 1, "exception_count": 1}
        user_ids = dict(state.get("user_ids", {}))
        user_ids[username.casefold()] = user_id
        state["user_ids"] = user_ids
        self._save_state(state)
        return user_id, {**self._empty("ok"), "request_count": 1}

    def _request(self, url: str, params: dict[str, str], token: str, tcg: str,
                 state: dict[str, Any], section_name: str, item_state: dict[str, Any],
                 since_id: str, *, fixed_user: dict[str, Any] | None = None,
                 state_key: str | None = None) -> dict[str, Any]:
        request = urllib.request.Request(url + "?" + urllib.parse.urlencode(params),
                                         headers={"Authorization": f"Bearer {token}",
                                                  "Accept": "application/json"})
        try:
            with self.opener.open(request, timeout=20) as response:
                payload = json.loads(response.read(2_000_000).decode("utf-8"))
                headers = response.headers
        except urllib.error.HTTPError as error:
            if error.code == 429:
                retry_at = self._set_backoff(state, section_name, state_key or tcg,
                                             item_state, error.headers)
                return {**self._empty("rate_limited"), "request_count": 1,
                        "rate_limit_429": 1,
                        "retry_after": max(1, int(retry_at - time.time()))}
            return {**self._empty("error"), "request_count": 1,
                    "exception_count": 1, "http_status": error.code}
        except (OSError, ValueError, json.JSONDecodeError):
            return {**self._empty("error"), "request_count": 1, "exception_count": 1}
        users = {str(item.get("id", "")): item
                 for item in payload.get("includes", {}).get("users", []) if isinstance(item, dict)}
        if fixed_user:
            users[str(fixed_user["id"])] = fixed_user
        candidates = []
        for tweet in payload.get("data", []):
            if isinstance(tweet, dict):
                candidate = self._candidate(tweet, users.get(str(tweet.get("author_id", "")),
                                                             fixed_user or {}), tcg)
                if candidate:
                    candidates.append(candidate)
        newest = str(payload.get("meta", {}).get("newest_id", "")).strip()
        if not newest:
            ids = [str(item.get("id", "")) for item in payload.get("data", []) if isinstance(item, dict)]
            newest = max(ids, key=lambda value: int(value)) if ids else ""
        section = dict(state.get(section_name, {}))
        section[state_key or tcg] = {"since_id": newest or since_id, "retry_at": 0,
                                     "backoff_attempts": 0, "last_request_at": time.time()}
        state[section_name] = section
        self._save_state(state)
        return {"status": "ok", "candidates": candidates, "request_count": 1,
                "retrieved_count": len(payload.get("data", [])), "candidate_count": len(candidates),
                "confirmed_count": 0, "rejected_count": 0, "rate_limit_429": 0,
                "exception_count": 0, "since_id": newest or since_id,
                "rate_limit_remaining": headers.get("x-rate-limit-remaining", "")}

    def _candidate(self, tweet: dict[str, Any], user: dict[str, Any],
                   tcg: str) -> dict[str, Any] | None:
        text = str(tweet.get("text", "")).strip()
        if not any(term.casefold() in text.casefold() for term in TCG_DEFINITIONS[tcg]["terms"]):
            return None
        if not any(term in text for term in COMMON_TERMS) or any(p.search(text) for p in EXCLUSIONS):
            return None
        username = str(user.get("username", ""))
        trusted = self._trusted_account(username, tcg)
        external_url, deadline = self._external_url(tweet), self._deadline(text)
        confidence = int(trusted.get("trust_score", 30) or 30) + (5 if deadline else 0)
        product_text = self._product_text(text, tcg)
        if not product_text or (not trusted.get("store_name") and not re.search(r"店|店舗|オンライン|通販", text)):
            confidence -= 10
        post_id = str(tweet.get("id", ""))
        source_url = f"https://x.com/{username}/status/{post_id}"
        return {
            "id": post_id, "source_type": "x_api", "source_url": source_url,
            "x_post_id": post_id, "x_account": username, "detected_at": self.now().isoformat(),
            "tcg": TCG_DEFINITIONS[tcg]["label"], "tcg_key": tcg,
            "product_text": product_text, "store_text": str(trusted.get("store_name", "")),
            "sales_method_hint": self.infer_sales_method(text, external_url),
            "deadline_hint": deadline, "confidence": max(0, min(100, confidence)),
            "evidence": [{"source_type": "x_api", "url": source_url, "text": text}],
            "verification_status": "pending", "confirmed": False,
            "information_type": "RESTOCK" if re.search(r"再販|再入荷|入荷", text) else "APPLICATION",
            "text": text, "username": username, "display_name": str(user.get("name", "")),
            "store_name": str(trusted.get("store_name", "")),
            "trust_score": int(trusted.get("trust_score", 30) or 30),
            "application_url": external_url, "created_at": str(tweet.get("created_at", "")),
            # Free-form X locations are deliberately ignored.
            "prefecture": str(trusted.get("prefecture", "")) or "UNKNOWN",
        }

    def verify_candidate(self, candidate: dict[str, Any],
                         official_evidence: Iterable[dict[str, Any]]) -> dict[str, Any]:
        result = dict(candidate)
        result.update({"confirmed": False, "verification_status": "pending"})
        for evidence in official_evidence:
            if not isinstance(evidence, dict) or not self._official_match(result, evidence):
                continue
            kind = str(evidence.get("source_type", ""))
            url = str(evidence.get("url") or evidence.get("application_url")
                      or evidence.get("official_url") or "")
            if kind not in OFFICIAL_TYPES or not self._normalized_url(url):
                continue
            record = {"source_type": kind, "url": url,
                      "text": str(evidence.get("text") or evidence.get("product_text") or "")}
            saved_evidence = result.setdefault("evidence", [])
            if not any(item.get("source_type") == kind
                       and self._normalized_url(item.get("url", "")) == self._normalized_url(url)
                       for item in saved_evidence if isinstance(item, dict)):
                saved_evidence.append(record)
            if str(evidence.get("status", "")).casefold() in REJECTING_STATUSES:
                result["verification_status"] = "rejected"
                return result
            # Product pages and official X corroborate identity, but not current sale availability.
            if kind not in CONFIRMING_TYPES:
                continue
            result.update({"verification_status": "confirmed", "confirmed": True,
                           "confidence": min(100, int(result.get("confidence", 0)) + 15)})
            if str(evidence.get("prefecture", "")).strip():
                result["prefecture"] = str(evidence["prefecture"]).strip()
            return result
        return result

    def search_and_store(self, enabled_tcg_keys: set[str],
                         bearer_token: str | None = None) -> dict[str, Any]:
        path = self.root / "data" / "information_candidates.json"
        file_result = inspect_json_file(path, list)
        if file_result.state == CORRUPT:
            return {"status": "corrupt", "error": file_result.error, "results": {},
                    "candidate_count": 0, "confirmed_count": 0, "rejected_count": 0}
        by_id = {(str(item.get("tcg_key", "")), str(item.get("x_post_id") or item.get("id", ""))): dict(item)
                 for item in (file_result.data or []) if isinstance(item, dict)}
        results: dict[str, Any] = {}
        metrics = {key: 0 for key in ("request_count", "retrieved_count",
                                      "rate_limit_429", "exception_count")}
        accounts = self.load_trusted_accounts()
        enabled = set(enabled_tcg_keys)
        # These two newer games currently live under the app's extensible "other" scope.
        if "other" in enabled:
            enabled.update({"union_arena", "dragon_ball_fusion_world"})
        for tcg in sorted(enabled & set(QUERIES)):
            result = self.search(tcg, bearer_token)
            results[tcg] = result
            self._add_metrics(metrics, result)
            for item in result.get("candidates", []):
                by_id[(tcg, str(item.get("x_post_id", "")))] = item
            account = self._next_timeline_account(accounts, tcg)
            if account:
                timeline = self.search_trusted_timeline(account, bearer_token)
                results[f"timeline:{account['username']}:{tcg}"] = timeline
                self._add_metrics(metrics, timeline)
                for item in timeline.get("candidates", []):
                    by_id[(tcg, str(item.get("x_post_id", "")))] = item
        evidence = self._load_official_evidence()
        verified = [self.verify_candidate(item, evidence) for item in by_id.values()]
        if verified != (file_result.data or []):
            self._atomic_write(path, verified)
        metrics.update({"results": results, "candidate_count": len(verified),
                        "confirmed_count": sum(i.get("verification_status") == "confirmed" for i in verified),
                        "rejected_count": sum(i.get("verification_status") == "rejected" for i in verified)})
        return metrics

    def _load_official_evidence(self) -> list[dict[str, Any]]:
        result = inspect_json_file(self.root / "data" / "products.json", list)
        if result.state == CORRUPT:
            return []
        evidence = []
        for product in result.data or []:
            if not isinstance(product, dict):
                continue
            base = {"tcg_key": product.get("tcg_key"), "product_text": product.get("name", "")}
            if product.get("official_url"):
                evidence.append({**base, "source_type": "official_product_page",
                                 "url": product["official_url"]})
            for site in product.get("sites", []):
                if isinstance(site, dict) and (site.get("application_url") or site.get("url")):
                    evidence.append({**base, "source_type": "official_application_page",
                                     "url": site.get("application_url") or site.get("url"),
                                     "store_text": site.get("name", ""),
                                     "prefecture": site.get("prefecture", "")})
        return evidence

    def _next_timeline_account(self, accounts: list[dict[str, Any]],
                               tcg: str) -> dict[str, Any] | None:
        eligible = [item for item in accounts
                    if item.get("enabled", True) and item.get("tcg") == tcg]
        if not eligible:
            return None
        state = self._load_state()
        rotation = dict(state.get("timeline_rotation", {}))
        index = int(rotation.get(tcg, 0) or 0) % len(eligible)
        rotation[tcg] = (index + 1) % len(eligible)
        state["timeline_rotation"] = rotation
        self._save_state(state)
        return eligible[index]

    @staticmethod
    def infer_sales_method(text: str, url: str = "") -> str:
        online = bool(re.search(r"WEB|Web|web|オンライン|通販|EC", text)) or bool(url)
        store = bool(re.search(r"店頭|店舗|レジ|整理券", text))
        return "HYBRID" if online and store else "ONLINE" if online else "STORE" if store else "UNKNOWN"

    @staticmethod
    def deduplicate(web_items: list[dict], x_items: list[dict]) -> list[dict]:
        output = [dict(item) for item in web_items]
        for item in x_items:
            existing = next((value for value in output if XRecentSearch._same_case(value, item)), None)
            if existing is None:
                output.append(dict(item))
            else:
                existing.setdefault("source_urls", []).append(item.get("source_url", ""))
        return output

    @staticmethod
    def _same_case(left: dict, right: dict) -> bool:
        left_url, right_url = (XRecentSearch._normalized_url(left.get("application_url", "")),
                               XRecentSearch._normalized_url(right.get("application_url", "")))
        if left_url and left_url == right_url:
            return str(left.get("tcg_key", "")).casefold() == str(right.get("tcg_key", "")).casefold()
        return XRecentSearch._case_key(left) == XRecentSearch._case_key(right)

    @staticmethod
    def _case_key(item: dict) -> tuple[str, ...]:
        norm = lambda value: re.sub(r"[\s　「」『』・_-]", "", str(value)).casefold()
        return (norm(item.get("tcg_key", "")),
                norm(item.get("product_text", item.get("product_name", item.get("name", "")))),
                norm(item.get("store_text", item.get("store_name", ""))),
                XRecentSearch._normalized_url(item.get("application_url", "")),
                str(item.get("deadline_hint", item.get("application_end_at", ""))))

    @staticmethod
    def _normalized_url(value: Any) -> str:
        try:
            parsed = urllib.parse.urlsplit(str(value).strip())
        except ValueError:
            return ""
        if parsed.scheme.casefold() != "https" or not parsed.hostname:
            return ""
        query = urllib.parse.urlencode([(key, item)
                                        for key, item in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
                                        if key.casefold() not in {"fbclid", "gclid", "ref_src", "ref_url", "twclid", "xclid"}
                                        and not key.casefold().startswith("utm_")])
        return urllib.parse.urlunsplit(("https", parsed.netloc.casefold(),
                                       parsed.path.rstrip("/"), query, ""))

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

    def _trusted_account(self, username: str, tcg: str) -> dict[str, Any]:
        return next((item for item in self.load_trusted_accounts()
                     if item.get("enabled", True)
                     and str(item.get("username", "")).casefold() == username.casefold()
                     and item.get("tcg") == tcg), {})

    @staticmethod
    def _product_text(text: str, tcg: str) -> str:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return (lines[0] if lines else text)[:300] if any(
            term.casefold() in text.casefold() for term in TCG_DEFINITIONS[tcg]["terms"]) else ""

    @staticmethod
    def _deadline(text: str) -> str:
        match = re.search(r"(?:締切|受付|応募).{0,12}?((?:20\d{2}[年/.-])?\d{1,2}[月/.-]\d{1,2}日?(?:\s*\d{1,2}[:時]\d{0,2})?)", text)
        return match.group(1) if match else ""

    @staticmethod
    def _external_url(tweet: dict) -> str:
        for item in tweet.get("entities", {}).get("urls", []):
            if not isinstance(item, dict):
                continue
            url = str(item.get("expanded_url") or item.get("unwound_url") or "")
            parsed = urllib.parse.urlsplit(url)
            if parsed.scheme == "https" and parsed.hostname and parsed.hostname.casefold() not in {
                    "x.com", "www.x.com", "twitter.com", "www.twitter.com"}:
                return url
        return ""

    @staticmethod
    def _official_match(candidate: dict[str, Any], evidence: dict[str, Any]) -> bool:
        if str(candidate.get("tcg_key", "")).casefold() != str(evidence.get("tcg_key", "")).casefold():
            return False
        candidate_url = XRecentSearch._normalized_url(candidate.get("application_url", ""))
        evidence_url = XRecentSearch._normalized_url(evidence.get("url") or evidence.get("application_url")
                                                     or evidence.get("official_url") or "")
        if candidate_url and candidate_url == evidence_url:
            return True
        norm = lambda value: re.sub(r"[^0-9a-zA-Zぁ-んァ-ヶ一-龠]", "", str(value)).casefold()
        product, official_product = norm(candidate.get("product_text", "")), norm(
            evidence.get("product_text", evidence.get("name", "")))
        store, official_store = norm(candidate.get("store_text", "")), norm(
            evidence.get("store_text", evidence.get("store_name", "")))
        return bool(product and official_product
                    and (product in official_product or official_product in product)
                    and (not store or not official_store or store in official_store or official_store in store))

    @staticmethod
    def _token(value: str | None) -> str:
        return (value or os.environ.get("POKEYOYA_X_BEARER_TOKEN", "")).strip()

    @staticmethod
    def _empty(status: str) -> dict[str, Any]:
        return {"status": status, "candidates": [], "request_count": 0, "retrieved_count": 0,
                "candidate_count": 0, "confirmed_count": 0, "rejected_count": 0,
                "rate_limit_429": 0, "exception_count": 0}

    @staticmethod
    def _in_backoff(item: dict[str, Any]) -> bool:
        return float(item.get("retry_at", 0) or 0) > time.time()

    def _set_backoff(self, state: dict[str, Any], section_name: str, key: str,
                     item: dict[str, Any], headers: Any) -> float:
        attempts = min(6, int(item.get("backoff_attempts", 0)) + 1)
        reset = int(headers.get("x-rate-limit-reset", "0") or 0)
        retry_at = max(time.time() + max(60, min(3600, (2 ** attempts) * 30)), float(reset))
        section = dict(state.get(section_name, {}))
        section[key] = {**item, "retry_at": retry_at, "backoff_attempts": attempts,
                        "last_request_at": time.time()}
        state[section_name] = section
        self._save_state(state)
        return retry_at

    @staticmethod
    def _add_metrics(total: dict[str, int], result: dict[str, Any]) -> None:
        for key in total:
            total[key] += int(result.get(key, 0) or 0)

    @staticmethod
    def _atomic_write(path: Path, value: list[dict[str, Any]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)

    def _load_state(self) -> dict[str, Any]:
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                return {}
            legacy = {key: item for key, item in value.items()
                      if key in QUERIES and isinstance(item, dict)}
            return {"recent": legacy} if legacy and "recent" not in value else value
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_state(self, state: dict[str, Any]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.state_path)
