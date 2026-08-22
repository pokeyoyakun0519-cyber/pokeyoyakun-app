from __future__ import annotations

import hashlib
import re
from collections import Counter, deque
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin, urlsplit

from core.autonomous_source_registry import (
    OfficialSourceCandidateStore,
    canonical_domain,
    canonical_host,
)
from core.generic_official_application_parser import (
    GenericOfficialApplicationParser,
    canonical_url,
)
from core.safe_discovery_fetcher import RequestBudget, SafeDiscoveryFetcher


OFFICIAL_STATES = {"KNOWN_ACTIVE", "VERIFIED_OFFICIAL", "MONITORABLE"}
MONITORABLE_STATES = {"KNOWN_ACTIVE", "MONITORABLE"}
OFFICIAL_LINK_TERMS = re.compile(
    r"公式(?:店舗|ショップ|ストア|販売店|取扱店|EC)|店舗(?:一覧|検索|情報)|取扱店|販売店|"
    r"OFFICIAL\s*(?:SHOP|STORE)|SHOP|STORE|ショップ|ストア|公認店|販売元|応募(?:ページ|フォーム)",
    re.I,
)
EXTERNAL_SOURCE_DENY_DOMAINS = {
    "x.com", "twitter.com", "facebook.com", "instagram.com", "line.me",
    "social-plugins.line.me", "youtube.com", "youtu.be", "tiktok.com",
    "google.com", "yahoo.co.jp", "bing.com", "amazon.co.jp",
    "forms.gle", "docs.google.com", "form.run", "formok.com",
}
FORM_TYPES = {"LOTTERY", "RESERVATION", "RESTOCK"}


class AutonomousApplicationSourceDiscovery:
    """Bounded seed-to-official discovery with a mandatory verification stage."""

    def __init__(
        self,
        root: Path,
        *,
        registry: OfficialSourceCandidateStore | None = None,
        fetcher: SafeDiscoveryFetcher | None = None,
        parser: GenericOfficialApplicationParser | None = None,
        dedicated_parsers: dict[str, Callable[[str, str], dict[str, Any]]] | None = None,
        max_depth: int = 2,
        max_urls_per_source: int = 5,
        global_request_max: int = 40,
        per_domain_request_max: int = 5,
    ) -> None:
        self.root = Path(root)
        self.registry = registry or OfficialSourceCandidateStore(self.root)
        self.fetcher = fetcher or SafeDiscoveryFetcher(
            self.root,
            budget=RequestBudget(global_max=global_request_max, per_domain_max=per_domain_request_max),
        )
        self.parser = parser or GenericOfficialApplicationParser()
        self.dedicated_parsers = dedicated_parsers or {}
        self.max_depth = max(0, min(3, int(max_depth)))
        self.max_urls_per_source = max(1, min(20, int(max_urls_per_source)))
        self.metrics = Counter()
        self.rejections = Counter()
        self.source_results: list[dict[str, Any]] = []

    def run(self, enabled_tcg: set[str] | None = None) -> dict[str, Any]:
        enabled = set(enabled_tcg or {
            "pokemon", "onepiece", "dragon_ball_fusion_world", "yugioh",
            "gundam", "union_arena", "duelmasters", "weiss",
        })
        discoveries: list[dict[str, Any]] = []
        candidate_sources: list[dict[str, Any]] = []
        checked_hosts: set[str] = set()
        for source in self.registry.sources(enabled_tcg=enabled):
            if not source.get("enabled") or source.get("source_state") not in MONITORABLE_STATES:
                continue
            self.metrics["seeds_scanned"] += 1
            found = self._scan_source(source, enabled, checked_hosts, candidate_sources)
            discoveries.extend(found)
        discoveries = self._deduplicate(discoveries)
        self.metrics["confirmed_applications"] = sum(
            item.get("hit", {}).get("verification_status") == "confirmed"
            for item in discoveries
        )
        self.metrics["new_application_pages"] = len(discoveries)
        diagnostics = {
            **dict(self.metrics),
            "candidates_rejected": sum(self.rejections.values()),
            "rejection_reasons": dict(self.rejections),
            "source_registry": self.registry.diagnostics(),
            "fetch": self.fetcher.diagnostics(),
            "sources": self.source_results,
        }
        return {
            "discoveries": discoveries,
            "source_candidates": candidate_sources,
            "diagnostics": diagnostics,
        }

    def _scan_source(
        self,
        source: dict[str, Any],
        enabled: set[str],
        checked_hosts: set[str],
        candidate_sources: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        source_id = str(source.get("id", ""))
        base_url = canonical_url(source.get("base_url"))
        if not base_url:
            self.rejections["unsafe_seed_url"] += 1
            return []
        hints = sorted(set(source.get("supported_tcg", [])) & enabled)
        initial_urls = [base_url]
        for path in source.get("discovery_paths", []):
            candidate_url = canonical_url(urljoin(base_url, str(path)))
            if candidate_url and candidate_url not in initial_urls:
                initial_urls.append(candidate_url)
        queue = deque(
            (url, 0) for url in initial_urls[: self.max_urls_per_source]
        )
        queued = set(initial_urls[: self.max_urls_per_source])
        checked = 0
        applications = []
        source_fetch_ok = False
        parser_success = False
        while queue and checked < self.max_urls_per_source:
            url, depth = queue.popleft()
            result = self.fetcher.fetch(url)
            checked += 1
            self.metrics["pages_checked"] += int(bool(result.get("ok") and not result.get("not_modified")))
            if not result.get("ok"):
                self._record_failure(source, url, result)
                continue
            if result.get("not_modified"):
                continue
            source_fetch_ok = True
            html = str(result.get("html") or "")
            try:
                analysis = self._parse(source, html, str(result.get("url") or url), hints)
                parser_success = True
            except Exception as error:
                self.metrics["parser_failures"] += 1
                self.source_results.append({
                    "source_id": source_id, "url": url, "status": "PARSER_OUTDATED",
                    "error": type(error).__name__,
                })
                continue
            self.fetcher.mark_parsed(url)
            if analysis.get("is_application"):
                application = self._application_discovery(source, analysis)
                applications.append(application)
                article_url = str(
                    analysis.get("canonical_url")
                    or analysis.get("source_url")
                    or url
                )
                self.registry.learn_pattern(
                    source_id, self._article_pattern(article_url)
                )
                self.metrics["candidates_found"] += 1
                if application["hit"]["verification_status"] == "confirmed":
                    self.metrics["candidates_verified"] += 1
            elif analysis.get("negative_match"):
                self.rejections["false_positive_context"] += 1
            if depth >= self.max_depth:
                continue
            links = sorted(
                analysis.get("discovery_links", []),
                key=lambda item: (
                    0 if re.search(r"rss|atom|feed|sitemap", str(item.get("url", "")), re.I) else 1,
                    str(item.get("url", "")),
                ),
            )
            for link in links:
                link_url = canonical_url(link.get("url"))
                if not link_url or link_url in queued:
                    continue
                if link.get("same_domain"):
                    queue.append((link_url, depth + 1))
                    queued.add(link_url)
                    continue
                candidate = self._discover_external_source(source, link, hints)
                if candidate:
                    candidate_sources.append(candidate)
                    promoted = self._verify_external_source(candidate, enabled, checked_hosts)
                    if promoted:
                        applications.extend(promoted)
        health = self.registry.observe_parser(
            source_id, fetch_ok=source_fetch_ok, application_count=len(applications)
        )
        self.source_results.append({
            "source_id": source_id,
            "name": str(source.get("name", "")),
            "checked_urls": checked,
            "applications": len(applications),
            "status": health if parser_success or source_fetch_ok else "HTTP_ERROR",
        })
        return applications

    def _parse(self, source: dict[str, Any], html: str, url: str, hints: list[str]) -> dict[str, Any]:
        parser = self.dedicated_parsers.get(str(source.get("id", "")))
        if parser is not None:
            value = parser(html, url)
            if isinstance(value, dict):
                value.setdefault("parser_strategy", "dedicated")
                return value
        return self.parser.parse(html, url, tcg_hint=hints)

    def _application_discovery(self, source: dict[str, Any], analysis: dict[str, Any]) -> dict[str, Any]:
        official = (
            source.get("trust_tier") == "TIER_A_OFFICIAL"
            and source.get("source_state") in OFFICIAL_STATES
        )
        confirmed = bool(
            official
            and float(analysis.get("application_relevance", 0)) >= 0.7
            and float(analysis.get("tcg_confidence", 0)) >= 0.7
            and analysis.get("application_type") in FORM_TYPES
        )
        tcg = str(analysis.get("tcg_key") or "other")
        period = dict(analysis.get("period") or {})
        article_url = str(analysis.get("canonical_url") or analysis.get("source_url") or "")
        application_url = str(analysis.get("application_url") or article_url)
        evidence = [{
            "source_type": "OFFICIAL_STORE" if source.get("seed_type") != "MANUFACTURER" else "OFFICIAL_MANUFACTURER",
            "source_url": article_url,
            "trust": 100 if official else 40,
            "verification_status": "confirmed" if confirmed else "candidate",
            "extracted_fields": {
                "tcg_key": tcg,
                "product_name": str(analysis.get("product_name", "")),
                "application_url": application_url,
                **{key: value for key, value in period.items() if value},
            },
        }]
        for form in analysis.get("external_forms", []):
            evidence.append({
                "source_type": "OFFICIAL_LINKED_FORM",
                "source_url": str(form.get("url", "")),
                "trust": 80,
                "verification_status": "secondary",
                "extracted_fields": {},
            })
        hit = {
            "site_key": str(source.get("id") or canonical_host(article_url)),
            "name": str(source.get("name") or canonical_host(article_url)),
            "url": application_url,
            "application_url": application_url,
            "status": "公式応募情報" if confirmed else "公式応募ページ候補",
            "confidence": float(analysis.get("application_relevance", 0)),
            "verification_status": "confirmed" if confirmed else "candidate",
            "confirmed": confirmed,
            "retailer_verified": confirmed,
            "official_store_verified": confirmed,
            "source_type": evidence[0]["source_type"],
            "source_evidence": evidence,
            "evidence": evidence,
            "tcg_key": tcg,
            "product_code": str(analysis.get("product_code", "")),
            "application_type": str(analysis.get("application_type", "")),
            "sales_mode": self._sales_mode(analysis),
            **{key: value for key, value in period.items() if value},
        }
        record = {
            "source_id": f"autonomous_{source.get('id', canonical_host(article_url))}",
            "source_name": str(source.get("name") or "公式情報ソース"),
            "article_url": article_url,
            "product_name": str(analysis.get("product_name") or analysis.get("title") or "")[:240],
            "product_code": str(analysis.get("product_code", "")),
            "tcg_key": tcg,
            "application_evidence": True,
            "evidence": evidence,
        }
        return {"record": record, "hit": hit}

    def _discover_external_source(self, parent: dict[str, Any], link: dict[str, Any], hints: list[str]) -> dict[str, Any] | None:
        # An outbound URL on an official page is not automatically an official
        # application source.  Require explicit anchor context; matching the URL
        # itself admitted social-share links whose query string contained "store".
        link_text = re.sub(r"\s+", " ", str(link.get("text", ""))).strip()
        if parent.get("trust_tier") != "TIER_A_OFFICIAL" or not OFFICIAL_LINK_TERMS.search(link_text):
            return None
        url = canonical_url(link.get("url"))
        host = canonical_host(url)
        registrable = canonical_domain(host)
        if not host or any(
            registrable == blocked or registrable.endswith(f".{blocked}")
            for blocked in EXTERNAL_SOURCE_DENY_DOMAINS
        ):
            self.rejections["non_source_external_domain"] += 1
            return None
        known = next((item for item in self.registry.records if canonical_host(item.get("base_url")) == host or host in {canonical_domain(value) for value in item.get("official_domains", [])}), None)
        if known:
            return dict(known)
        self.metrics["official_candidates"] += 1
        return self.registry.discover(
            name=str(link_text or host)[:200],
            url=url,
            source_url=str(parent.get("base_url", "")),
            provenance="verified_official_link",
            trust_tier="TIER_A_OFFICIAL",
            supported_tcg=hints,
            seed_type="RETAILER",
        )

    def _verify_external_source(
        self,
        candidate: dict[str, Any],
        enabled: set[str],
        checked_hosts: set[str],
    ) -> list[dict[str, Any]]:
        if candidate.get("source_state") not in {"DISCOVERED_CANDIDATE", "TEMPORARILY_FAILED"}:
            return []
        url = canonical_url(candidate.get("base_url"))
        host = canonical_host(url)
        if not url or host in checked_hosts:
            return []
        checked_hosts.add(host)
        self.registry.begin_verification(str(candidate["id"]))
        result = self.fetcher.fetch(url, force=True)
        if not result.get("ok"):
            updated = self.registry.complete_verification(str(candidate["id"]), {
                "official_provenance": True,
                "https": bool(url),
                "robots_allowed": result.get("status") != "ROBOTS_BLOCKED",
                "fetch_success": False,
                "parser_success": False,
                "redirect_safe": result.get("status") != "SECURITY_REJECTED",
                "tcg_confidence": 0,
                "application_relevance": 0,
            })
            if updated.get("source_state") == "BLOCKED_ROBOTS":
                self.metrics["blocked_robots"] += 1
            return []
        analysis = self.parser.parse(
            str(result.get("html") or ""), str(result.get("url") or url),
            tcg_hint=sorted(set(candidate.get("supported_tcg", [])) & enabled),
        )
        updated = self.registry.complete_verification(str(candidate["id"]), {
            "official_provenance": any(
                item.get("provenance") == "verified_official_link"
                for item in candidate.get("official_evidence", [])
            ),
            "https": True,
            "robots_allowed": True,
            "fetch_success": True,
            "parser_success": True,
            "redirect_safe": True,
            "tcg_confidence": float(analysis.get("tcg_confidence", 0)),
            "application_relevance": float(analysis.get("application_relevance", 0)),
        })
        if updated.get("source_state") != "MONITORABLE":
            return []
        self.metrics["new_sources_learned"] += 1
        if analysis.get("canonical_url"):
            self.registry.learn_pattern(str(candidate["id"]), self._article_pattern(str(analysis["canonical_url"])))
        return [self._application_discovery(updated, analysis)] if analysis.get("is_application") else []

    def _record_failure(self, source: dict[str, Any], url: str, result: dict[str, Any]) -> None:
        status = str(result.get("status", "HTTP_ERROR"))
        if status == "ROBOTS_BLOCKED":
            self.metrics["blocked_robots"] += 1
        elif status == "RESPONSE_TOO_LARGE":
            self.rejections["oversized_response"] += 1
        elif status == "SECURITY_REJECTED":
            self.rejections["ssrf_or_url_safety"] += 1
        self.source_results.append({
            "source_id": str(source.get("id", "")), "url": url,
            "status": status, "error": str(result.get("error", ""))[:200],
        })

    @staticmethod
    def _sales_mode(analysis: dict[str, Any]) -> str:
        text = str(analysis.get("text_excerpt", ""))
        online = bool(re.search(r"オンライン|WEB|通販", text, re.I))
        store = bool(re.search(r"店頭|店舗|受取", text))
        if online and store:
            return "HYBRID"
        if online:
            return "ONLINE"
        if store:
            return "STORE"
        return "UNKNOWN"

    @staticmethod
    def _article_pattern(url: str) -> str:
        path = urlsplit(url).path
        return re.sub(r"/\d+(?=/|$)", "/{id}", path)[:200]

    @staticmethod
    def _deduplicate(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        by_key: dict[tuple[str, str, str, str], dict[str, Any]] = {}
        for item in items:
            record = item.get("record", {})
            hit = item.get("hit", {})
            key = (
                str(record.get("tcg_key", "")),
                re.sub(r"[^a-z0-9ぁ-んァ-ヶ一-龠]", "", str(record.get("product_name", "")).casefold()),
                canonical_url(hit.get("application_url")),
                str(hit.get("application_end_at", "")),
            )
            existing = by_key.get(key)
            if existing is None:
                by_key[key] = item
                output.append(item)
                continue
            evidence = list(existing.get("hit", {}).get("evidence", []))
            known = {(value.get("source_type"), value.get("source_url")) for value in evidence}
            for value in hit.get("evidence", []):
                if (value.get("source_type"), value.get("source_url")) not in known:
                    evidence.append(value)
            existing["hit"]["evidence"] = evidence
            existing["hit"]["source_evidence"] = evidence
        return output


def discovery_event(discovery_result: dict[str, Any]) -> dict[str, Any] | None:
    count = int(discovery_result.get("diagnostics", {}).get("new_sources_learned", 0))
    if not count:
        return None
    return {
        "event_type": "NEW_OFFICIAL_SOURCE",
        "title": "新しい公式情報ソースを検出しました",
        "count": count,
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "user_notification": False,
    }
