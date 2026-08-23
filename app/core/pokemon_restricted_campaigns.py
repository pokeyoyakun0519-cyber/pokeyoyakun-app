from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from html import unescape
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

from core.application_filters import canonical_application_url
from core.restricted_application import UNVERIFIED_RESTRICTED, restrict_discovery
from core.runtime_paths import bundled_root, is_frozen
from core.safe_discovery_fetcher import RequestBudget, SafeDiscoveryFetcher


JST = timezone(timedelta(hours=9))
RETENTION_DAYS = 14


def campaign_path() -> Path:
    if is_frozen():
        return bundled_root() / "resources" / "pokemon_restricted_campaigns.json"
    return Path(__file__).resolve().parents[1] / "resources" / "pokemon_restricted_campaigns.json"


class PokemonRestrictedCampaignMonitor:
    """Recheck time-bounded, concrete campaigns whose official page blocks automation.

    The bundled definitions are deliberately finite campaign observations, not
    evergreen store seeds.  They may become confirmed only after the fetched
    official page independently contains the required product/store terms.
    ROBOTS_BLOCKED results remain explicitly unverified and self-expire after
    the normal dashboard retention window.
    """

    def __init__(
        self,
        root: Path,
        *,
        fetcher: SafeDiscoveryFetcher | None = None,
        now: Callable[[], datetime] | None = None,
        definitions_path: Path | None = None,
    ) -> None:
        self.root = Path(root)
        self.now = now or (lambda: datetime.now(JST))
        self.definitions_path = definitions_path or campaign_path()
        self.fetcher = fetcher or SafeDiscoveryFetcher(
            self.root,
            budget=RequestBudget(global_max=14, per_domain_max=3),
            state_path=self.root / "data" / "pokemon_restricted_campaign_fetch_state.json",
        )
        self.diagnostics: dict[str, Any] = {}

    def scan(self, *, force: bool = False) -> list[dict[str, Any]]:
        current = self.now().astimezone(JST)
        campaigns = self._load_definitions()
        discoveries: list[dict[str, Any]] = []
        outcomes: list[dict[str, Any]] = []
        counts: Counter[str] = Counter()
        fetched: dict[str, dict[str, Any]] = {}
        for campaign in campaigns:
            window = self._window_status(campaign, current)
            if window in {"FUTURE", "STALE", "INVALID_PERIOD"}:
                counts[window] += 1
                outcomes.append({"id": campaign.get("id", ""), "status": window})
                continue
            official_url = canonical_application_url(campaign.get("official_url"))
            if not self._valid_official_url(official_url):
                counts["INVALID_OFFICIAL_URL"] += 1
                outcomes.append({"id": campaign.get("id", ""), "status": "INVALID_OFFICIAL_URL"})
                continue
            result = fetched.get(official_url)
            if result is None:
                result = self.fetcher.fetch(official_url, force=force)
                fetched[official_url] = result
            discovery = self._build_discovery(campaign, current, window)
            status = str(result.get("status") or "HTTP_ERROR")
            if result.get("ok") and not result.get("not_modified"):
                actual_url = canonical_application_url(result.get("url") or official_url)
                if (urlsplit(actual_url).hostname or "").casefold() != (
                    urlsplit(official_url).hostname or ""
                ).casefold():
                    status = "UNVERIFIED_REDIRECT"
                elif self._strictly_matches(campaign, str(result.get("html") or "")):
                    discovery = self._confirm(discovery, current)
                    status = "CONFIRMED"
                else:
                    status = "OFFICIAL_CONTENT_MISMATCH"
            elif status == "ROBOTS_BLOCKED":
                discovery = restrict_discovery(
                    discovery, official_url=official_url, reason=status,
                )
            if str(discovery.get("hit", {}).get("verification_status")) in {
                "confirmed", UNVERIFIED_RESTRICTED,
            }:
                discoveries.append(discovery)
                counts[str(discovery["hit"]["verification_status"])] += 1
            else:
                counts[status] += 1
            outcomes.append({"id": campaign.get("id", ""), "status": status})

        discoveries = self._deduplicate(discoveries)
        self.diagnostics = {
            "status": "OK" if discoveries else "NO_CURRENT_RESULTS",
            "candidate": len(campaigns),
            "current_or_recent": sum(
                self._window_status(item, current) in {"ACTIVE", "ENDED_WITHIN_14_DAYS"}
                for item in campaigns
            ),
            "confirmed": sum(
                item.get("hit", {}).get("verification_status") == "confirmed"
                for item in discoveries
            ),
            "restricted": sum(
                item.get("hit", {}).get("verification_status") == UNVERIFIED_RESTRICTED
                for item in discoveries
            ),
            "outcome_counts": dict(counts),
            "source_outcomes": outcomes,
            "monitorable_sources": sorted({
                (urlsplit(str(item.get("official_url") or "")).hostname or "").casefold()
                for item in campaigns
            }),
            "fetch": self.fetcher.diagnostics(),
        }
        return discoveries

    def _load_definitions(self) -> list[dict[str, Any]]:
        try:
            payload = json.loads(self.definitions_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return []
        if payload.get("schema_version") != 1:
            return []
        return [dict(item) for item in payload.get("campaigns", []) if isinstance(item, dict)]

    @staticmethod
    def _window_status(campaign: dict[str, Any], current: datetime) -> str:
        try:
            start = datetime.fromisoformat(str(campaign.get("application_start_at") or ""))
            end = datetime.fromisoformat(str(campaign.get("application_end_at") or ""))
            if start.tzinfo is None or end.tzinfo is None or end < start:
                return "INVALID_PERIOD"
        except (TypeError, ValueError):
            return "INVALID_PERIOD"
        if current < start.astimezone(JST):
            return "FUTURE"
        if current > end.astimezone(JST) + timedelta(days=RETENTION_DAYS):
            return "STALE"
        return "ACTIVE" if current <= end.astimezone(JST) else "ENDED_WITHIN_14_DAYS"

    @staticmethod
    def _valid_official_url(url: str) -> bool:
        try:
            parsed = urlsplit(url)
            return parsed.scheme.casefold() == "https" and bool(parsed.hostname)
        except ValueError:
            return False

    @staticmethod
    def _strictly_matches(campaign: dict[str, Any], html: str) -> bool:
        text = re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", html))).casefold()
        required = [str(term).strip().casefold() for term in campaign.get("required_terms", [])]
        return bool(required) and all(term in text for term in required)

    @staticmethod
    def _build_discovery(
        campaign: dict[str, Any], current: datetime, window: str,
    ) -> dict[str, Any]:
        official_url = canonical_application_url(campaign.get("official_url"))
        application_url = canonical_application_url(
            campaign.get("application_url") or official_url
        )
        observed_at = str(campaign.get("observed_at") or current.isoformat(timespec="seconds"))
        discovery_url = str(campaign.get("discovery_url") or "").strip()
        trust_tier = "TIER_B_DISCOVERY" if discovery_url else "TIER_A_OFFICIAL"
        start_at = str(campaign.get("application_start_at") or "")
        end_at = str(campaign.get("application_end_at") or "")
        evidence = [
            {
                "source_type": "TIME_BOUNDED_CAMPAIGN_OBSERVATION",
                "source_url": discovery_url or official_url,
                "observed_at": observed_at,
                "trust": 40 if discovery_url else 70,
                "verification_status": "candidate",
                "extracted_fields": {
                    "product_name": campaign.get("product_name"),
                    "store_name": campaign.get("store_name"),
                    "application_start_at": start_at,
                    "application_end_at": end_at,
                    "official_destination": official_url,
                },
            },
            {
                "source_type": "OFFICIAL_RECHECK_TARGET",
                "source_url": official_url,
                "observed_at": current.isoformat(timespec="seconds"),
                "trust": 0,
                "verification_status": "candidate",
                "extracted_fields": {},
            },
        ]
        status = "抽選受付中" if window == "ACTIVE" else "応募期間終了"
        hit = {
            "site_key": str(campaign.get("chain") or ""),
            "name": str(campaign.get("store_name") or ""),
            "branch": str(campaign.get("branch") or ""),
            "url": application_url,
            "application_url": application_url,
            "official_detail_url": official_url,
            "discovery_source_url": str(campaign.get("discovery_url") or ""),
            "status": status,
            "application_status": status,
            "application_type": "LOTTERY",
            "application_method": str(campaign.get("application_method") or "抽選"),
            "application_path_type": str(campaign.get("application_path_type") or "OFFICIAL_GUIDANCE"),
            "application_period": f"{start_at} ～ {end_at}",
            "application_start_at": start_at,
            "application_end_at": end_at,
            "sales_mode": str(campaign.get("sales_mode") or "UNKNOWN"),
            "prefecture": str(campaign.get("prefecture") or "地域不明"),
            "confidence": 0.72,
            "verification_status": "candidate",
            "confirmed": False,
            "retailer_verified": False,
            "official_store_verified": False,
            "source_type": str(campaign.get("source_type") or "OFFICIAL_PAGE"),
            "trust_tier": trust_tier,
            "source_evidence": evidence,
            "evidence": evidence,
            "tcg_key": "pokemon",
            "detected_at": observed_at,
            "last_verified_at": current.isoformat(timespec="seconds"),
        }
        record = {
            "source_id": f"phase3_{campaign.get('chain', '')}",
            "source_name": str(campaign.get("store_name") or ""),
            "article_url": official_url,
            "discovery_source_url": discovery_url,
            "product_name": str(campaign.get("product_name") or ""),
            "tcg_key": "pokemon",
            "application_evidence": True,
            "trust_tier": trust_tier,
            "evidence": evidence,
        }
        return {"record": record, "hit": hit}

    @staticmethod
    def _confirm(discovery: dict[str, Any], current: datetime) -> dict[str, Any]:
        hit = dict(discovery.get("hit") or {})
        record = dict(discovery.get("record") or {})
        hit.update({
            "verification_status": "confirmed",
            "confirmed": True,
            "retailer_verified": True,
            "official_store_verified": True,
            "confidence": 0.96,
            "last_verified_at": current.isoformat(timespec="seconds"),
        })
        record["verification_status"] = "confirmed"
        return {**discovery, "record": record, "hit": hit}

    @staticmethod
    def _deduplicate(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str, str]] = set()
        for item in items:
            hit = item.get("hit", {})
            key = (
                str(hit.get("site_key") or ""),
                str(hit.get("branch") or ""),
                str(item.get("record", {}).get("product_name") or ""),
                str(hit.get("application_end_at") or ""),
            )
            if key not in seen:
                seen.add(key)
                output.append(item)
        return output
