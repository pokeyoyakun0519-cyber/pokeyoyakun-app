from __future__ import annotations

import hashlib
import ipaddress
import json
import socket
import time
import urllib.error
import urllib.request
import urllib.robotparser
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote, urlsplit, urlunsplit

from core.secure_https import build_https_opener


MAX_RESPONSE_BYTES = 3_000_000
MAX_ROBOTS_BYTES = 500_000
USER_AGENT = "PokeyoyaKun-AutonomousDiscovery/1.0 (+public official pages only)"


def _ascii_url(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme, parsed.netloc, quote(parsed.path, safe="/%:@"), quote(parsed.query, safe="=&%:@/?+"), ""))


class UnsafeDiscoveryUrl(ValueError):
    pass


class RequestBudget:
    def __init__(self, *, global_max: int = 40, per_domain_max: int = 5) -> None:
        self.global_max = max(1, int(global_max))
        self.per_domain_max = max(1, int(per_domain_max))
        self.total = 0
        self.by_domain: Counter[str] = Counter()

    def consume(self, host: str) -> bool:
        if self.total >= self.global_max or self.by_domain[host] >= self.per_domain_max:
            return False
        self.total += 1
        self.by_domain[host] += 1
        return True


class _ValidatedRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, validator: Callable[[str], None]) -> None:
        super().__init__()
        self.validator = validator

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.validator(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class SafeDiscoveryFetcher:
    """Bounded HTTPS fetcher with SSRF, redirect, robots and backoff guards."""

    def __init__(
        self,
        root: Path,
        *,
        resolver: Callable[..., list[Any]] | None = None,
        opener: Callable[..., Any] | None = None,
        budget: RequestBudget | None = None,
        now: Callable[[], datetime] | None = None,
        ttl_hours: int = 12,
        state_path: Path | None = None,
    ) -> None:
        self.root = Path(root)
        self.path = state_path or (
            self.root / "data" / "autonomous_fetch_state.json"
        )
        self.resolver = resolver or socket.getaddrinfo
        self._injected_opener = opener
        self.budget = budget or RequestBudget()
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.ttl = timedelta(hours=max(1, ttl_hours))
        self.state = self._load_state()
        self.robots_cache: dict[str, bool] = {}
        self.metrics = Counter()

    def validate_url(self, url: str) -> None:
        try:
            parsed = urlsplit(str(url or ""))
            port = parsed.port
        except ValueError as error:
            raise UnsafeDiscoveryUrl("invalid_url") from error
        host = (parsed.hostname or "").casefold()
        if parsed.scheme.casefold() != "https" or port not in (None, 443):
            raise UnsafeDiscoveryUrl("https_required")
        if parsed.username or parsed.password or not host:
            raise UnsafeDiscoveryUrl("credentials_or_host_invalid")
        if host == "localhost" or host.endswith((".localhost", ".local")):
            raise UnsafeDiscoveryUrl("local_host_rejected")
        try:
            literal = ipaddress.ip_address(host.strip("[]"))
        except ValueError:
            literal = None
        if literal is not None:
            self._validate_ip(literal)
            return
        try:
            answers = self.resolver(host, 443, type=socket.SOCK_STREAM)
        except OSError as error:
            raise UnsafeDiscoveryUrl("dns_resolution_failed") from error
        if not answers:
            raise UnsafeDiscoveryUrl("dns_resolution_empty")
        for answer in answers:
            address = answer[4][0]
            self._validate_ip(ipaddress.ip_address(address))

    def robots_allowed(self, url: str) -> bool:
        self.validate_url(url)
        parsed = urlsplit(url)
        origin = f"https://{parsed.hostname.casefold()}"
        if origin in self.robots_cache:
            return self.robots_cache[origin]
        robots_url = origin + "/robots.txt"
        if not self.budget.consume(parsed.hostname.casefold()):
            self.metrics["budget_exhausted"] += 1
            self.robots_cache[origin] = False
            return False
        try:
            result = self._request(robots_url, max_bytes=MAX_ROBOTS_BYTES, count_budget=False)
            if result["status"] == 404:
                allowed = True
            elif not result["ok"]:
                allowed = False
            else:
                parser = urllib.robotparser.RobotFileParser(robots_url)
                parser.parse(result["text"].splitlines())
                allowed = parser.can_fetch(USER_AGENT, url)
        except (OSError, ValueError, UnsafeDiscoveryUrl):
            allowed = False
        self.robots_cache[origin] = allowed
        if not allowed:
            self.metrics["blocked_robots"] += 1
        return allowed

    def fetch(self, url: str, *, require_robots: bool = True, force: bool = False) -> dict[str, Any]:
        try:
            self.validate_url(url)
        except UnsafeDiscoveryUrl as error:
            self.metrics["security_rejected"] += 1
            return {"ok": False, "status": "SECURITY_REJECTED", "error": str(error), "url": url, "html": ""}
        host = (urlsplit(url).hostname or "").casefold()
        key = hashlib.sha256(url.encode()).hexdigest()
        previous = dict(self.state.get(key, {}))
        current = self.now()
        retry_at = self._parse_time(previous.get("retry_at"))
        if retry_at and current < retry_at and not force:
            self.metrics["backoff_skipped"] += 1
            return {"ok": False, "status": "BACKOFF", "url": url, "html": ""}
        checked_at = self._parse_time(previous.get("checked_at"))
        if checked_at and current - checked_at < self.ttl and not force:
            self.metrics["ttl_skipped"] += 1
            return {"ok": True, "status": "CACHE_FRESH", "url": url, "html": "", "not_modified": True}
        if require_robots and not self.robots_allowed(url):
            return {"ok": False, "status": "ROBOTS_BLOCKED", "url": url, "html": ""}
        if not self.budget.consume(host):
            self.metrics["budget_exhausted"] += 1
            return {"ok": False, "status": "BUDGET_EXHAUSTED", "url": url, "html": ""}
        headers = {}
        if previous.get("etag"):
            headers["If-None-Match"] = str(previous["etag"])
        if previous.get("last_modified"):
            headers["If-Modified-Since"] = str(previous["last_modified"])
        response = self._request(url, max_bytes=MAX_RESPONSE_BYTES, headers=headers, count_budget=True)
        now_text = current.isoformat(timespec="seconds")
        if response.get("not_modified"):
            previous.update({"checked_at": now_text, "failure_count": 0, "retry_at": ""})
            self.state[key] = previous
            self._save_state()
            self.metrics["not_modified"] += 1
            return {"ok": True, "status": "NOT_MODIFIED", "url": url, "html": "", "not_modified": True}
        if not response["ok"]:
            failures = min(8, int(previous.get("failure_count", 0)) + 1)
            retry = current + timedelta(minutes=min(24 * 60, 15 * (2 ** (failures - 1))))
            previous.update({"checked_at": now_text, "failure_count": failures, "retry_at": retry.isoformat(timespec="seconds"), "status": response["status"]})
            self.state[key] = previous
            self._save_state()
            self.metrics["http_failures"] += 1
            return {"ok": False, "status": response["status"], "error": response.get("error", ""), "url": url, "html": ""}
        content_hash = hashlib.sha256(response["raw"]).hexdigest()
        self.state[key] = {
            "url": url, "checked_at": now_text, "parsed_at": "", "etag": response.get("etag", ""),
            "last_modified": response.get("last_modified", ""), "content_hash": content_hash,
            "failure_count": 0, "retry_at": "", "status": response["status"],
        }
        self._save_state()
        self.metrics["pages_checked"] += 1
        return {
            "ok": True, "status": response["status"], "url": response.get("final_url", url),
            "html": response["text"], "content_hash": content_hash,
            "etag": response.get("etag", ""), "last_modified": response.get("last_modified", ""),
        }

    def mark_parsed(self, url: str) -> None:
        key = hashlib.sha256(url.encode()).hexdigest()
        if key in self.state:
            self.state[key]["parsed_at"] = self.now().isoformat(timespec="seconds")
            self._save_state()

    def diagnostics(self) -> dict[str, Any]:
        return {
            **dict(self.metrics),
            "request_count": self.budget.total,
            "requests_by_domain": dict(self.budget.by_domain),
            "global_request_max": self.budget.global_max,
            "per_domain_request_max": self.budget.per_domain_max,
            "max_response_bytes": MAX_RESPONSE_BYTES,
        }

    def _request(self, url: str, *, max_bytes: int, headers: dict[str, str] | None = None, count_budget: bool) -> dict[str, Any]:
        self.validate_url(url)
        request = urllib.request.Request(
            _ascii_url(url),
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.5",
                "Accept-Language": "ja,en;q=0.5",
                **(headers or {}),
            },
        )
        opener = self._injected_opener
        if opener is None:
            director = build_https_opener(_ValidatedRedirectHandler(self.validate_url))
            opener = director.open
        try:
            with opener(request, timeout=20) as response:
                final_url = str(response.geturl())
                self.validate_url(final_url)
                raw = response.read(max_bytes + 1)
                if len(raw) > max_bytes:
                    return {"ok": False, "status": "RESPONSE_TOO_LARGE", "error": "response size limit"}
                charset = response.headers.get_content_charset()
                text = self._decode(raw, charset)
                return {
                    "ok": True, "status": int(getattr(response, "status", 200)), "raw": raw, "text": text,
                    "final_url": final_url, "etag": str(response.headers.get("ETag", "")),
                    "last_modified": str(response.headers.get("Last-Modified", "")),
                }
        except urllib.error.HTTPError as error:
            if error.code == 304:
                return {"ok": True, "status": 304, "not_modified": True}
            return {"ok": False, "status": int(error.code), "error": "HTTP error"}
        except UnsafeDiscoveryUrl as error:
            return {"ok": False, "status": "SECURITY_REJECTED", "error": str(error)}
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            return {"ok": False, "status": "HTTP_ERROR", "error": type(error).__name__}

    @staticmethod
    def _validate_ip(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> None:
        if not address.is_global or address.is_private or address.is_loopback or address.is_link_local or address.is_reserved or address.is_multicast or address.is_unspecified:
            raise UnsafeDiscoveryUrl("non_public_address_rejected")

    @staticmethod
    def _decode(raw: bytes, declared: str | None) -> str:
        for charset in (declared, "utf-8", "cp932", "shift_jis", "euc_jp"):
            if not charset:
                continue
            try:
                return raw.decode(charset)
            except (LookupError, UnicodeDecodeError):
                continue
        return raw.decode("utf-8", errors="replace")

    @staticmethod
    def _parse_time(value: object) -> datetime | None:
        try:
            parsed = datetime.fromisoformat(str(value or ""))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

    def _load_state(self) -> dict[str, Any]:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}

    def _save_state(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.state, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)
