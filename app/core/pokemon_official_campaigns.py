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
RETENTION_DAYS = 14
OFFICIAL_SOURCES = (
    {
        "id": "pokemon_card_store_30th",
        "url": "https://shop.pokemon.co.jp/ja/shop/common/news/202608/000451.html",
        "host": "shop.pokemon.co.jp",
        "parser": "pokemon_card_store",
    },
    {
        "id": "kids_republic_30th",
        "url": "https://www.kidsrepublic.jp/campaign/campaign_detail/20260916_pokemoncardgame",
        "host": "www.kidsrepublic.jp",
        "parser": "kids_republic",
    },
    {
        "id": "furuichi_shinnyuzen_open",
        "url": "https://furu1.net/news/news_campaign/news_opensale_shin",
        "host": "furu1.net",
        "parser": "furuichi",
    },
)


class _OfficialPageParser(HTMLParser):
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
        elif tag.casefold() == "img" and values.get("alt"):
            self.parts.append(re.sub(r"\s+", " ", values["alt"]).strip())
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


class PokemonOfficialCampaignMonitor:
    """Bounded monitoring of official Pokemon application announcements.

    Every emitted row is reconstructed from a fetched official page.  A source
    definition only supplies the bounded URL and expected official host; it is
    never sufficient evidence by itself.
    """

    def __init__(
        self,
        root: Path,
        *,
        fetcher: SafeDiscoveryFetcher | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.root = Path(root)
        self.now = now or (lambda: datetime.now(JST))
        self.fetcher = fetcher or SafeDiscoveryFetcher(
            self.root,
            budget=RequestBudget(global_max=8, per_domain_max=2),
            state_path=self.root / "data" / "pokemon_official_campaign_fetch_state.json",
        )
        self.diagnostics: dict[str, Any] = {}

    def scan(self, *, force: bool = False) -> list[dict[str, Any]]:
        current = self.now().astimezone(JST)
        discoveries: list[dict[str, Any]] = []
        outcomes: list[dict[str, Any]] = []
        for source in OFFICIAL_SOURCES:
            result = self.fetcher.fetch(str(source["url"]), force=force)
            outcome = {
                "source_id": source["id"],
                "url": source["url"],
                "status": str(result.get("status") or "HTTP_ERROR"),
                "discovered": 0,
            }
            if result.get("ok") and not result.get("not_modified"):
                actual_url = str(result.get("url") or source["url"])
                host = (urlsplit(actual_url).hostname or "").casefold()
                if host != source["host"]:
                    outcome["status"] = "UNVERIFIED_REDIRECT"
                else:
                    parsed, reason = self.parse_official_document(
                        str(result.get("html") or ""), actual_url,
                        parser=str(source["parser"]), observed_at=current,
                    )
                    discoveries.extend(parsed)
                    outcome["discovered"] = len(parsed)
                    outcome["status"] = "OK" if parsed else reason
            outcomes.append(outcome)

        discoveries = self._deduplicate(discoveries)
        self.diagnostics = {
            "status": "OK" if any(row["status"] == "OK" for row in outcomes) else "NO_CURRENT_RESULTS",
            "trust_tier": "TIER_A_OFFICIAL",
            "candidate": len(discoveries),
            "official_pages_checked": len(outcomes),
            "official_verified": len(discoveries),
            "confirmed": len(discoveries),
            "source_outcomes": outcomes,
            "verified_domains": sorted({
                (urlsplit(item["record"]["article_url"]).hostname or "").casefold()
                for item in discoveries
            }),
            "monitorable_sources": [str(item["id"]) for item in OFFICIAL_SOURCES],
            "fetch": self.fetcher.diagnostics(),
        }
        return discoveries

    @classmethod
    def parse_official_document(
        cls,
        html: str,
        official_url: str,
        *,
        parser: str,
        observed_at: datetime,
    ) -> tuple[list[dict[str, Any]], str]:
        page = _OfficialPageParser(official_url)
        page.feed(str(html or "")[:3_000_000])
        text = re.sub(r"\s+", " ", unescape(" ".join(page.parts))).strip()
        if not re.search(r"ポケモンカード|ポケモンカードゲーム", text, re.I):
            return [], "TCG_NOT_POKEMON"
        if not re.search(r"抽選|応募", text):
            return [], "APPLICATION_EVIDENCE_MISSING"
        method = getattr(cls, f"_parse_{parser}", None)
        if method is None:
            return [], "PARSER_MISSING"
        rows = method(text, page.links, official_url, observed_at.astimezone(JST))
        return (rows, "") if rows else ([], "NO_CURRENT_OR_RECENT_APPLICATION")

    @classmethod
    def _parse_pokemon_card_store(
        cls, text: str, links: list[dict[str, str]], url: str, current: datetime,
    ) -> list[dict[str, Any]]:
        period = cls._month_day_period(
            text, current.year,
            r"お申し込み受付期間[：:]?.{0,20}?",
        )
        product = cls._match_product(text, r"対象商品.{0,20}?・?\s*(ポケモンカードゲーム.{3,100}?)(?:商品の詳細|※)")
        if not period or not product or not cls._within_dashboard_window(period, current):
            return []
        application_links = [
            link["url"] for link in links
            if (urlsplit(link["url"]).hostname or "").casefold() == "miniapp.line.me"
        ]
        branches = re.findall(
            r"店舗名[：:]\s*(ポケモンカードストア\s+in\s+[^住]{2,80}?)\s+"
            r"住所[：:]\s*((?:北海道|東京都|京都府|大阪府|.{2,3}県).{5,140}?)\s+"
            r"(?:<)?応募URL(?:>)?",
            text,
        )
        if len(branches) != len(application_links) or not branches:
            return []
        output = []
        for (branch, address), application_url in zip(branches, application_links):
            prefecture = cls._explicit_prefecture(address)
            if not prefecture:
                continue
            output.append(cls._build_discovery(
                chain="pokemon_card_store", store_name="ポケモンカードストア",
                branch=branch, address=address, prefecture=prefecture,
                product=product, official_url=url, application_url=application_url,
                period=period, current=current, sales_mode="STORE",
                path_type="DIRECT_APPLICATION", application_method="LINEミニアプリで応募・店舗購入",
                source_id="pokemon_card_store_official",
                source_type="OFFICIAL_STORE_PAGE",
            ))
        return output

    @classmethod
    def _parse_kids_republic(
        cls, text: str, links: list[dict[str, str]], url: str, current: datetime,
    ) -> list[dict[str, Any]]:
        del links
        period = cls._month_day_period(text, current.year, r"応募受付期間.{0,12}?")
        product = cls._match_product(
            text, r"対象商品.{0,40}?(ポケモンカードゲーム\s*MEGA.{0,80}?30th\s+CELEBRATION)",
        )
        if (
            not period or not product
            or not cls._within_dashboard_window(period, current)
            or "キッズリパブリックアプリ" not in text
        ):
            return []
        if "本州・四国のイオン・イオンスタイル・スーパーセンター" not in text:
            return []
        return [cls._build_discovery(
            chain="aeon_toy", store_name="イオン玩具売場",
            branch="対象店舗（本州・四国）", address="", prefecture="全国",
            product=product, official_url=url, application_url=url,
            period=period, current=current, sales_mode="HYBRID",
            path_type="APP_REQUIRED", application_method="キッズリパブリックアプリで応募・店舗受取",
            source_id="kids_republic_official",
            source_type="OFFICIAL_STORE_PAGE",
        )]

    @classmethod
    def _parse_furuichi(
        cls, text: str, links: list[dict[str, str]], url: str, current: datetime,
    ) -> list[dict[str, Any]]:
        del links
        if "ふるいちトップブックス新入善店" not in text:
            return []
        block_match = re.search(
            r"第1弾・LivePocket抽選販売(?P<body>.+?)第2弾・LivePocket抽選販売",
            text,
        )
        if not block_match:
            return []
        body = block_match.group("body")
        dates = re.search(
            r"抽選受付日時\s*(20\d{2})[./年](\d{1,2})[./月](\d{1,2}).{0,20}?[～~]\s*"
            r"(\d{1,2})[./月](\d{1,2})",
            body,
        )
        if not dates:
            return []
        year, smonth, sday, emonth, eday = map(int, dates.groups())
        try:
            start = datetime(year, smonth, sday, 0, 0, tzinfo=JST)
            end = datetime(year, emonth, eday, 23, 59, 59, tzinfo=JST)
        except ValueError:
            return []
        period = (start, end)
        if not cls._within_dashboard_window(period, current):
            return []
        product_values = re.findall(r"(ポケモンカードゲーム.{4,100}?)(?=ポケモンカードゲーム|抽選受付日時)", body)
        product = " / ".join(re.sub(r"\s+", " ", value).strip() for value in product_values[:3])[:240]
        if not product:
            return []
        return [cls._build_discovery(
            chain="furuichi", store_name="ふるいち",
            branch="ふるいちトップブックス新入善店", address="", prefecture="富山県",
            product=product, official_url=url, application_url=url,
            period=period, current=current, sales_mode="STORE",
            path_type="STORE_ONLY", application_method="店頭のLivePocket QRから応募",
            source_id="furuichi_official",
            source_type="OFFICIAL_STORE_PAGE",
        )]

    @classmethod
    def _build_discovery(
        cls, *, chain: str, store_name: str, branch: str, address: str,
        prefecture: str, product: str, official_url: str, application_url: str,
        period: tuple[datetime, datetime], current: datetime, sales_mode: str,
        path_type: str, application_method: str, source_id: str, source_type: str,
    ) -> dict[str, Any]:
        start, end = period
        canonical = canonical_application_url(official_url)
        application = canonical_application_url(application_url)
        observed = current.isoformat(timespec="seconds")
        status = "受付前" if current < start else "応募期間終了" if current > end else "抽選受付中"
        evidence = {
            "source_type": source_type,
            "source_url": canonical,
            "observed_at": observed,
            "trust": 100,
            "verification_status": "confirmed",
            "extracted_fields": {
                "tcg_key": "pokemon", "product_name": product,
                "store_name": store_name, "branch": branch,
                "application_start_at": start.isoformat(timespec="seconds"),
                "application_end_at": end.isoformat(timespec="seconds"),
                "application_url": application,
            },
        }
        hit = {
            "site_key": chain, "name": store_name, "branch": branch,
            "store_branch": branch, "address": address, "prefecture": prefecture,
            "url": application, "application_url": application,
            "official_detail_url": canonical, "status": status,
            "application_status": status, "application_type": "LOTTERY",
            "application_method": application_method,
            "application_path_type": path_type,
            "application_period": f"{start:%Y/%m/%d %H:%M} ～ {end:%Y/%m/%d %H:%M}",
            "application_start_at": start.isoformat(timespec="seconds"),
            "application_end_at": end.isoformat(timespec="seconds"),
            "sales_mode": sales_mode, "confidence": 0.99,
            "verification_status": "confirmed", "confirmed": True,
            "retailer_verified": True, "official_store_verified": True,
            "source_type": source_type, "source_evidence": [evidence],
            "evidence": [evidence], "tcg_key": "pokemon",
            "detected_at": observed, "last_verified_at": observed,
        }
        record = {
            "source_id": source_id, "source_name": store_name,
            "article_url": canonical, "product_name": product,
            "tcg_key": "pokemon", "application_evidence": True,
            "status": "終了済み" if current > end else "受付中",
            "evidence": [evidence],
        }
        return {"record": record, "hit": hit}

    @staticmethod
    def _month_day_period(
        text: str, year: int, prefix: str,
    ) -> tuple[datetime, datetime] | None:
        match = re.search(
            prefix
            + r"(\d{1,2})月(\d{1,2})日.{0,10}?(\d{1,2})(?:時|:)([0-5]\d)?(?:分)?\s*[～~〜-]+\s*"
            r"(\d{1,2})月(\d{1,2})日.{0,10}?(\d{1,2})(?:時|:)([0-5]\d)?(?:分)?",
            text,
        )
        if not match:
            return None
        values = [int(value) if value is not None else 0 for value in match.groups()]
        try:
            return (
                datetime(year, values[0], values[1], values[2], values[3], tzinfo=JST),
                datetime(year, values[4], values[5], values[6], values[7], tzinfo=JST),
            )
        except ValueError:
            return None

    @staticmethod
    def _match_product(text: str, pattern: str) -> str:
        match = re.search(pattern, text, re.I)
        return re.sub(r"\s+", " ", match.group(1)).strip(" ・")[:240] if match else ""

    @staticmethod
    def _within_dashboard_window(
        period: tuple[datetime, datetime], current: datetime,
    ) -> bool:
        start, end = period
        return start <= current and end >= current - timedelta(days=RETENTION_DAYS)

    @staticmethod
    def _explicit_prefecture(address: str) -> str:
        match = re.match(r"(北海道|東京都|京都府|大阪府|.{2,3}県)", address.strip())
        return match.group(1) if match else ""

    @staticmethod
    def _deduplicate(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str]] = set()
        for item in items:
            hit = item.get("hit", {})
            key = (
                str(hit.get("site_key") or ""), str(hit.get("branch") or ""),
                str(hit.get("application_end_at") or ""),
            )
            if key not in seen:
                seen.add(key)
                output.append(item)
        return output
