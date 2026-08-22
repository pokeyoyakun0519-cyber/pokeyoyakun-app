from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin, urlsplit

from core.application_filters import canonical_application_url
from core.safe_discovery_fetcher import RequestBudget, SafeDiscoveryFetcher


JST = timezone(timedelta(hours=9))
DISCOVERY_URL_TEMPLATE = "https://pokesoku.com/lottery-{year:04d}-{month:02d}/"
OFFICIAL_HOSTS = {
    "livepocket.jp",
    "www.otakarasouko.com",
    "otakarasouko.com",
}
SELLERS = (
    ("イエローサブマリン", "yellow_submarine", "イエローサブマリン"),
    ("株式会社晴れる屋", "hareruya2", "晴れる屋2"),
    ("晴れる屋2", "hareruya2", "晴れる屋2"),
    ("ホビーステーション", "hobby_station", "ホビーステーション"),
)


class _PageParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.parts: list[str] = []
        self.links: list[dict[str, str]] = []
        self.meta: dict[str, str] = {}
        self._href = ""
        self._link_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        values = {str(key).casefold(): str(value or "") for key, value in attrs}
        if tag.casefold() == "meta":
            key = values.get("property") or values.get("name")
            if key and values.get("content"):
                self.meta[key.casefold()] = values["content"]
        elif tag.casefold() == "a":
            self._href = urljoin(self.base_url, values.get("href", ""))
            self._link_parts = [values.get("title", ""), values.get("aria-label", "")]

    def handle_data(self, data: str) -> None:
        value = re.sub(r"\s+", " ", data).strip()
        if value:
            self.parts.append(value)
            if self._href:
                self._link_parts.append(value)

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "a" and self._href:
            self.links.append({
                "url": canonical_application_url(self._href),
                "text": re.sub(r"\s+", " ", " ".join(self._link_parts)).strip(),
            })
            self._href = ""
            self._link_parts = []


class PokemonCoverageExpansionMonitor:
    """Tier-B discovery followed by strict official application verification.

    The discovery page supplies URLs only. A record is confirmed exclusively
    from the destination page, including its product, deadline and store or
    seller identity. X/SNS pages are never fetched.
    """

    def __init__(
        self,
        root: Path,
        *,
        fetcher: SafeDiscoveryFetcher | None = None,
        now: Callable[[], datetime] | None = None,
        official_limit: int = 12,
    ) -> None:
        self.root = Path(root)
        self.now = now or (lambda: datetime.now(JST))
        self.fetcher = fetcher or SafeDiscoveryFetcher(
            self.root,
            budget=RequestBudget(global_max=30, per_domain_max=8),
            state_path=(
                self.root / "data" / "pokemon_coverage_fetch_state.json"
            ),
        )
        self.official_limit = max(1, min(20, int(official_limit)))
        self.diagnostics: dict[str, Any] = {}

    def scan(self, *, force: bool = False) -> list[dict[str, Any]]:
        current = self.now().astimezone(JST)
        discovery_url = DISCOVERY_URL_TEMPLATE.format(
            year=current.year, month=current.month,
        )
        result = self.fetcher.fetch(discovery_url, force=force)
        if not result.get("ok") or result.get("not_modified"):
            self.diagnostics = {
                "source": discovery_url,
                "status": str(result.get("status", "HTTP_ERROR")),
                "candidate": 0,
                "official_verified": 0,
                "confirmed": 0,
                "rejection_reasons": {},
            }
            return []

        parser = _PageParser(discovery_url)
        parser.feed(str(result.get("html") or ""))
        official_urls: list[str] = []
        for link in parser.links:
            url = str(link.get("url") or "")
            host = (urlsplit(url).hostname or "").casefold()
            if host in OFFICIAL_HOSTS and url not in official_urls:
                official_urls.append(url)

        discoveries: list[dict[str, Any]] = []
        rejected: dict[str, int] = {}
        source_rejections: list[dict[str, str]] = []
        checked = 0
        for url in official_urls[: self.official_limit]:
            official = self.fetcher.fetch(url, force=force)
            checked += 1
            if not official.get("ok") or official.get("not_modified"):
                reason = str(official.get("status", "HTTP_ERROR"))
                rejected[reason] = rejected.get(reason, 0) + 1
                source_rejections.append({"url": url, "reason": reason})
                continue
            discovery, reason = self.verify_official_document(
                str(official.get("html") or ""),
                str(official.get("url") or url),
                discovery_url=discovery_url,
                observed_at=current,
            )
            if discovery:
                discoveries.append(discovery)
            else:
                rejected[reason] = rejected.get(reason, 0) + 1
                source_rejections.append({"url": url, "reason": reason})

        discoveries = self._deduplicate(discoveries)
        self.diagnostics = {
            "source": discovery_url,
            "status": "OK",
            "trust_tier": "TIER_B_DISCOVERY",
            "candidate": len(official_urls),
            "official_pages_checked": checked,
            "official_verified": len(discoveries),
            "confirmed": len(discoveries),
            "new_verified_domains": sorted({
                (urlsplit(item["record"]["article_url"]).hostname or "").casefold()
                for item in discoveries
            }),
            "new_monitorable_sources": ["pokesoku_pokemon_official_links"],
            "rejection_reasons": rejected,
            "source_rejections": source_rejections,
            "fetch": self.fetcher.diagnostics(),
        }
        return discoveries

    @classmethod
    def verify_official_document(
        cls,
        html: str,
        official_url: str,
        *,
        discovery_url: str,
        observed_at: datetime,
    ) -> tuple[dict[str, Any] | None, str]:
        host = (urlsplit(official_url).hostname or "").casefold()
        if host not in OFFICIAL_HOSTS:
            return None, "unverified_domain"
        parser = _PageParser(official_url)
        parser.feed(str(html or "")[:3_000_000])
        text = re.sub(r"\s+", " ", unescape(" ".join(parser.parts))).strip()
        title = str(parser.meta.get("og:title") or "").strip()
        combined = f"{title} {text}"
        if not re.search(r"ポケモンカード|ポケカ", combined, re.I):
            return None, "tcg_not_pokemon"
        if not re.search(r"抽選|応募|販売受付", combined):
            return None, "not_application"

        if host == "livepocket.jp":
            seller = next((item for item in SELLERS if item[0] in combined), None)
            if seller is None:
                return None, "seller_not_verified"
            chain, store_name = seller[1], seller[2]
            sales_mode = "ONLINE" if chain == "hareruya2" and "通販" in combined else "STORE"
            application_method = "Web抽選"
            source_type = "OFFICIAL_APPLICATION_PAGE"
        else:
            chain, store_name = "otakarasouko", "お宝創庫"
            sales_mode = "HYBRID"
            application_method = "公式アプリで応募・店舗受取"
            source_type = "OFFICIAL_STORE_PAGE"

        period = cls._application_period(combined, host=host)
        if period is None:
            return None, "deadline_unknown"
        start_at, end_at, period_text = period
        start = datetime.fromisoformat(start_at)
        end = datetime.fromisoformat(end_at)
        current = observed_at.astimezone(JST)
        if end < current - timedelta(days=14):
            return None, "outside_retention_window"
        product_name = cls._product_name(title, combined, chain)
        if not product_name:
            return None, "product_unknown"
        canonical = canonical_application_url(official_url)
        observed = observed_at.astimezone(JST).isoformat(timespec="seconds")
        official_evidence = {
            "source_type": source_type,
            "source_url": canonical,
            "observed_at": observed,
            "trust": 100,
            "verification_status": "confirmed",
            "extracted_fields": {
                "tcg_key": "pokemon",
                "product_name": product_name,
                "store_name": store_name,
                "application_start_at": start_at,
                "application_end_at": end_at,
                "application_url": canonical,
            },
        }
        discovery_evidence = {
            "source_type": "DISCOVERY_SOURCE",
            "source_url": discovery_url,
            "observed_at": observed,
            "trust": 40,
            "verification_status": "candidate",
            "extracted_fields": {"official_destination": canonical},
        }
        status = (
            "受付前" if current < start
            else "応募期間終了" if current > end
            else "抽選受付中"
        )
        hit = {
            "site_key": chain,
            "name": store_name,
            "branch": "通販" if sales_mode == "ONLINE" else "対象店舗",
            "url": canonical,
            "application_url": canonical,
            "status": status,
            "application_status": status,
            "application_type": "LOTTERY",
            "application_method": application_method,
            "application_period": period_text,
            "application_start_at": start_at,
            "application_end_at": end_at,
            "sales_mode": sales_mode,
            "confidence": 0.98,
            "verification_status": "confirmed",
            "confirmed": True,
            "retailer_verified": True,
            "official_store_verified": True,
            "source_type": source_type,
            "source_evidence": [official_evidence, discovery_evidence],
            "evidence": [official_evidence, discovery_evidence],
            "tcg_key": "pokemon",
        }
        record = {
            "source_id": f"phase1_{chain}",
            "source_name": store_name,
            "article_url": canonical,
            "product_name": product_name,
            "tcg_key": "pokemon",
            "application_evidence": True,
            "evidence": [official_evidence, discovery_evidence],
        }
        return {"record": record, "hit": hit}, ""

    @staticmethod
    def _application_period(text: str, *, host: str) -> tuple[str, str, str] | None:
        if host == "livepocket.jp":
            match = re.search(
                r"販売受付期間\s*"
                r"(20\d{2})年(\d{1,2})月(\d{1,2})日.{0,8}?(\d{1,2}):([0-5]\d)\s*[〜~～-]+\s*"
                r"(20\d{2})年(\d{1,2})月(\d{1,2})日.{0,8}?(\d{1,2}):([0-5]\d)",
                text,
            )
        else:
            match = re.search(
                r"(20\d{2})年(\d{1,2})月(\d{1,2})日.{0,12}?(?:ひる\s*)?(\d{1,2})(?::|時)([0-5]\d)?(?:分)?\s*[〜~～-]+\s*"
                r"(20\d{2})年(\d{1,2})月(\d{1,2})日.{0,12}?(\d{1,2})(?::|時)([0-5]\d)?(?:分)?",
                text,
            )
        if not match:
            return None
        values = [int(value) if value is not None else 0 for value in match.groups()]
        try:
            start = datetime(*values[:5], tzinfo=JST)
            end = datetime(*values[5:], tzinfo=JST)
        except ValueError:
            return None
        period_text = (
            f"{start:%Y/%m/%d %H:%M} ～ {end:%Y/%m/%d %H:%M}"
        )
        return start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds"), period_text

    @staticmethod
    def _product_name(title: str, text: str, chain: str) -> str:
        if chain == "otakarasouko":
            return "ポケモンカードゲーム 再販4商品"
        match = re.search(
            r"ポケモンカードゲーム(?:MEGA)?\s*(?:拡張パック)?[「『\"]?"
            r"([^」』\"\n]{3,80})",
            text,
            re.I,
        )
        if match:
            value = re.split(r"購入権|抽選|販売価格|BOX", match.group(1))[0].strip(" 　」』")
            if value:
                return f"ポケモンカードゲーム {value}"[:200]
        clean_title = re.sub(r"のチケット情報.*$|｜.*$", "", title).strip()
        if clean_title:
            return f"ポケモンカードゲーム {clean_title}"[:200]
        return ""

    @staticmethod
    def _deduplicate(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for item in items:
            key = (
                str(item.get("hit", {}).get("site_key", "")),
                str(item.get("hit", {}).get("application_url", "")),
            )
            if key not in seen:
                seen.add(key)
                output.append(item)
        return output
