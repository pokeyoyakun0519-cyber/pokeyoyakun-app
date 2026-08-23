from __future__ import annotations

import ipaddress
import re
import unicodedata
from collections import Counter
from datetime import datetime, timedelta
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlsplit

from core.application_discovery import CANDIDATE, resolve_candidate
from core.application_filters import canonical_application_url
from core.application_status import JST
from core.nyuka_now_discovery import (
    OfficialVerificationQueue,
    TIER_B_DISCOVERY,
    merge_discovery_candidates,
    official_verification_from_document,
)
from core.restricted_application import restrict_discovery


SOURCE_NAME = "カード抽選まとめ"
SOURCE_DOMAIN = "cardchusen.com"
SOURCE_URLS = {
    "pokemon": "https://www.cardchusen.com/pokeka",
    "onepiece": "https://www.cardchusen.com/onepiece",
    "yugioh": "https://www.cardchusen.com/yugioh",
    "dragon_ball_fusion_world": "https://www.cardchusen.com/dragonball",
}
ADOPTION_STATUS = "TERMS_RESTRICTED"
DEFAULT_TTL_SECONDS = 12 * 60 * 60

_CARD_CLASS = re.compile(r"(?:lottery|application|entry|board)[-_]?(?:card|item|row)", re.I)
_FIELD_CLASSES = {
    "product_name": re.compile(r"product|item|pack|box", re.I),
    "store_name": re.compile(r"shop|store|retailer", re.I),
    "branch": re.compile(r"branch", re.I),
    "prefecture": re.compile(r"prefecture|area|region", re.I),
    "deadline": re.compile(r"deadline|end|closing", re.I),
    "application_start": re.compile(r"application-start|entry-start|opening", re.I),
    "application_type": re.compile(r"method|application-type|entry-type", re.I),
}
_VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
_KNOWN_CHAINS = (
    "BOOKOFF", "ブックオフ", "TSUTAYA", "バトロコ", "プレイズ",
    "ドラゴンスター", "カードボックス", "CARDBOX", "カードラボ",
    "ホビーステーション", "Fullcomp", "フルコンプ", "古本市場",
    "ふるいち", "北国書林", "萬屋", "ToyShop POTATO KING",
    "ゲームプラザ元気302", "ポケモンセンター", "GEO", "ゲオ",
)
_PREFECTURES = (
    "北海道", "青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県",
    "茨城県", "栃木県", "群馬県", "埼玉県", "千葉県", "東京都", "神奈川県",
    "新潟県", "富山県", "石川県", "福井県", "山梨県", "長野県", "岐阜県",
    "静岡県", "愛知県", "三重県", "滋賀県", "京都府", "大阪府", "兵庫県",
    "奈良県", "和歌山県", "鳥取県", "島根県", "岡山県", "広島県", "山口県",
    "徳島県", "香川県", "愛媛県", "高知県", "福岡県", "佐賀県", "長崎県",
    "熊本県", "大分県", "宮崎県", "鹿児島県", "沖縄県",
)
_X_HOSTS = {"x.com", "www.x.com", "twitter.com", "www.twitter.com"}


class _ListingParser(HTMLParser):
    """Extract semantic application cards without page-level navigation text."""

    def __init__(self, source_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.source_url = source_url
        self.cards: list[dict[str, Any]] = []
        self.current: dict[str, Any] | None = None
        self.depth = 0
        self.class_stack: list[set[str]] = []
        self.link_url = ""
        self.link_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {str(key).casefold(): str(value or "") for key, value in attrs}
        classes = set(values.get("class", "").split())
        is_card = bool(_CARD_CLASS.search(" ".join(classes))) or bool(
            values.get("data-product") and values.get("data-store")
        )
        if self.current is None and is_card:
            self.current = {
                "attributes": values,
                "text": [],
                "fields": {name: [] for name in _FIELD_CLASSES},
                "links": [],
            }
            self.depth = 1
            self.class_stack = [classes]
        elif self.current is not None and tag.casefold() not in _VOID_TAGS:
            self.depth += 1
            self.class_stack.append(classes)

        if self.current is not None and tag.casefold() == "a":
            self.link_url = canonical_application_url(
                urljoin(self.source_url, values.get("href", ""))
            )
            self.link_parts = []

    def handle_data(self, data: str) -> None:
        if self.current is None:
            return
        text = re.sub(r"\s+", " ", data).strip()
        if not text:
            return
        self.current["text"].append(text)
        active_classes = " ".join(self.class_stack[-1] if self.class_stack else set())
        for name, pattern in _FIELD_CLASSES.items():
            if pattern.search(active_classes):
                self.current["fields"][name].append(text)
        if self.link_url:
            self.link_parts.append(text)

    def handle_endtag(self, tag: str) -> None:
        if self.current is None:
            return
        if tag.casefold() == "a" and self.link_url:
            self.current["links"].append({
                "url": self.link_url,
                "label": re.sub(r"\s+", " ", " ".join(self.link_parts)).strip(),
            })
            self.link_url = ""
            self.link_parts = []
        if tag.casefold() not in _VOID_TAGS:
            self.depth -= 1
            if self.class_stack:
                self.class_stack.pop()
        if self.depth == 0:
            self.cards.append(self.current)
            self.current = None


class CardchusenDiscovery:
    """Pure TIER_B parser; live polling is disabled by the source's terms."""

    def __init__(self, *, now=None) -> None:
        self.now = now or (lambda: datetime.now(JST))
        self.last_diagnostics = self._empty_diagnostics()

    def poll(self) -> list[dict[str, Any]]:
        self.last_diagnostics["prevented_fetch_count"] += 1
        self.last_diagnostics["last_check"] = self.now().isoformat(timespec="seconds")
        return []

    def parse_listing(self, html: str, source_url: str) -> list[dict[str, Any]]:
        tcg_hint = next((key for key, url in SOURCE_URLS.items() if _same_path(url, source_url)), "")
        if not tcg_hint:
            return []
        parser = _ListingParser(source_url)
        parser.feed(str(html or ""))
        candidates: list[dict[str, Any]] = []
        rejected = Counter()
        for raw in parser.cards[:500]:
            candidate, reason = self._candidate(raw, source_url, tcg_hint)
            if candidate is None:
                rejected[reason or "parse_error"] += 1
            else:
                candidates.append(candidate)
        unique = merge_discovery_candidates(candidates)
        self.last_diagnostics.update({
            "last_check": self.now().isoformat(timespec="seconds"),
            "listings_parsed": len(parser.cards),
            "current_candidates": len(unique),
            "duplicate_count": len(candidates) - len(unique),
            "rejected_count": sum(rejected.values()),
            "rejected_by_reason": dict(rejected),
            "by_tcg": dict(Counter(str(item.get("tcg_key")) for item in unique)),
            "unique_chains": len({str(item.get("chain")) for item in unique if item.get("chain")}),
            "unique_branches": len({
                (str(item.get("chain")), str(item.get("branch") or item.get("store_name")))
                for item in unique if item.get("store_name")
            }),
        })
        return unique

    def audit_documents(self, documents: dict[str, str]) -> list[dict[str, Any]]:
        parsed = []
        totals = Counter()
        rejects = Counter()
        for url, html in documents.items():
            parsed.extend(self.parse_listing(html, url))
            diagnostics = self.diagnostics()
            totals["listings_parsed"] += int(diagnostics.get("listings_parsed", 0))
            totals["rejected_count"] += int(diagnostics.get("rejected_count", 0))
            rejects.update(diagnostics.get("rejected_by_reason", {}))
        unique = merge_discovery_candidates(parsed)
        self.last_diagnostics.update({
            "listings_parsed": totals["listings_parsed"],
            "current_candidates": len(unique),
            "duplicate_count": len(parsed) - len(unique),
            "rejected_count": totals["rejected_count"],
            "rejected_by_reason": dict(rejects),
            "by_tcg": dict(Counter(str(item.get("tcg_key")) for item in unique)),
            "unique_chains": len({str(item.get("chain")) for item in unique if item.get("chain")}),
            "unique_branches": len({
                (str(item.get("chain")), str(item.get("branch") or item.get("store_name")))
                for item in unique if item.get("store_name")
            }),
        })
        return unique

    def promote(
        self,
        candidate: dict[str, Any],
        *,
        official_url: str,
        official_html: str = "",
        failure_status: str = "",
    ) -> dict[str, Any]:
        """Promote only with official evidence or an explicit restricted outcome."""
        if _is_x_url(official_url):
            return {**candidate, "verification_error": "X_API_REQUIRED"}
        if official_html:
            official = official_verification_from_document(
                candidate, official_url, official_html,
            )
            queue = OfficialVerificationQueue()
            queue.enqueue([candidate])
            return queue.verify_next(lambda _item: official) or dict(candidate)
        if failure_status:
            discovery = {
                "record": {
                    "product_name": candidate.get("product_name", ""),
                    "trust_tier": TIER_B_DISCOVERY,
                    "discovery_source_url": candidate.get("source_article_url", ""),
                },
                "hit": {
                    **candidate,
                    "name": candidate.get("store_name", ""),
                    "source_url": candidate.get("source_article_url", ""),
                },
            }
            restricted = restrict_discovery(
                discovery, official_url=official_url, reason=failure_status,
            )
            return restricted["hit"]
        return dict(candidate)

    def diagnostics(self) -> dict[str, Any]:
        return dict(self.last_diagnostics)

    def _candidate(
        self, raw: dict[str, Any], source_url: str, tcg_key: str,
    ) -> tuple[dict[str, Any] | None, str]:
        attrs = raw.get("attributes", {})
        fields = raw.get("fields", {})
        text = " ".join(raw.get("text", []))
        product = _first(
            attrs.get("data-product"), " ".join(fields.get("product_name", [])),
            _labeled(text, r"商品(?:名)?"),
        )
        store = _first(
            attrs.get("data-store"), " ".join(fields.get("store_name", [])),
            _labeled(text, r"(?:店舗|店名)"),
        )
        if not product:
            return None, "product_unknown"
        if not store:
            return None, "store_unknown"

        current = self.now().astimezone(JST)
        deadline_text = _first(
            attrs.get("data-deadline"), " ".join(fields.get("deadline", [])), text,
        )
        end_at, time_confirmed = _parse_card_time(deadline_text, current, end=True)
        if "受付終了" in text and not end_at:
            return None, "ended_without_deadline"
        if end_at and current > end_at + timedelta(days=14):
            return None, "stale"
        start_text = _first(
            attrs.get("data-application-start"),
            " ".join(fields.get("application_start", [])),
        )
        start_at, _ = _parse_card_time(start_text, current, end=False)
        if start_at and start_at > current:
            return None, "future"

        links = []
        x_links = []
        for link in raw.get("links", []):
            url = str(link.get("url") or "")
            if not _safe_candidate_url(url) or _is_source_url(url):
                continue
            value = {
                "url": url,
                "label": str(link.get("label") or ""),
                "candidate_type": "X_API_ONLY" if _is_x_url(url) else _destination_type(url),
            }
            if _is_x_url(url):
                x_links.append(value)
            else:
                links.append(value)

        chain = next(
            (name for name in _KNOWN_CHAINS if name.casefold() in store.casefold()), ""
        )
        branch = _first(attrs.get("data-branch"), " ".join(fields.get("branch", [])))
        prefecture = _first(
            attrs.get("data-prefecture"), " ".join(fields.get("prefecture", [])),
        )
        if prefecture not in _PREFECTURES:
            prefecture = ""
        method = _first(
            attrs.get("data-application-type"),
            " ".join(fields.get("application_type", [])), text,
        )
        application_type = (
            "LOTTERY" if "抽選" in method
            else "RESERVATION" if "予約" in method
            else "RESTOCK" if re.search(r"再販|再入荷", method)
            else ""
        )
        if not application_type:
            return None, "application_type_unknown"
        sales_hint = (
            "HYBRID" if re.search(r"オンライン.*(?:店頭|店舗)受取|Web.*(?:店頭|店舗)", method, re.I)
            else "ONLINE" if re.search(r"オンライン|Web|通販|アプリ", method, re.I)
            else "STORE" if re.search(r"店頭|店舗", method)
            else "UNKNOWN"
        )
        observed = current.isoformat(timespec="seconds")
        source = canonical_application_url(source_url)
        candidate = {
            "tcg_key": tcg_key,
            "product_name": product[:300],
            "store_name": store[:200],
            "chain": chain,
            "branch": branch,
            "prefecture": prefecture or "UNKNOWN",
            "application_type": application_type,
            "application_start_at": start_at.isoformat(timespec="seconds") if start_at else "",
            "application_end_at": end_at.isoformat(timespec="seconds") if end_at else "",
            "application_end_time_confirmed": time_confirmed,
            "application_url": links[0]["url"] if links else "",
            "application_url_candidates": links,
            "x_url_candidates": x_links,
            "official_destination_candidates": [*links, *x_links],
            "application_method": method[:300],
            "sales_mode": "UNKNOWN",
            "sales_mode_hint": sales_hint,
            "source_name": SOURCE_NAME,
            "source_type": "DISCOVERY_SOURCE",
            "source_article_url": source,
            "source_url": source,
            "discovery_source_url": source,
            "discovered_at": observed,
            "last_seen_at": observed,
            "trust_tier": TIER_B_DISCOVERY,
            "verification_status": CANDIDATE,
            "confirmed": False,
            "store_registry_status": "known" if chain else "quarantine",
            "discovered_store_candidate": not bool(chain),
            "evidence_sources": [source],
            "evidence": [{
                "source_type": "DISCOVERY_SOURCE",
                "source_url": source,
                "observed_at": observed,
                "trust": 60,
                "verification_status": CANDIDATE,
                "extracted_fields": {
                    "tcg_key": tcg_key,
                    "product_name": product[:300],
                    "store_name": store[:200],
                    "branch": branch,
                    "prefecture": prefecture,
                    "application_end_at": end_at.isoformat(timespec="seconds") if end_at else "",
                    "application_url_candidates": [*links, *x_links],
                },
            }],
        }
        return resolve_candidate(candidate, now=current), ""

    @staticmethod
    def _empty_diagnostics() -> dict[str, Any]:
        return {
            "source_name": SOURCE_NAME,
            "source_url": "https://www.cardchusen.com/",
            "trust_tier": TIER_B_DISCOVERY,
            "adoption_status": ADOPTION_STATUS,
            "auto_enabled": False,
            "policy_reason": "robots.txt references Terms Article 5 automated collection prohibition",
            "ttl_seconds": DEFAULT_TTL_SECONDS,
            "last_check": "",
            "listings_parsed": 0,
            "current_candidates": 0,
            "duplicate_count": 0,
            "rejected_count": 0,
            "rejected_by_reason": {},
            "by_tcg": {},
            "unique_chains": 0,
            "unique_branches": 0,
            "confirmed": 0,
            "restricted": 0,
            "prevented_fetch_count": 0,
        }


def _first(*values: Any) -> str:
    return next(
        (re.sub(r"\s+", " ", str(value)).strip() for value in values if str(value or "").strip()),
        "",
    )


def _labeled(text: str, label: str) -> str:
    match = re.search(rf"{label}\s*[:：]\s*([^|｜\n]{{2,200}}?)(?=\s+(?:店舗|店名|締切|応募|方式)\s*[:：]|$)", text)
    return match.group(1).strip() if match else ""


def _parse_card_time(text: str, now: datetime, *, end: bool) -> tuple[datetime | None, bool]:
    value = unicodedata.normalize("NFKC", str(text or ""))
    relative = re.search(r"(?:本日|今日|明日)(?:\s*(\d{1,2})[:時](\d{2})?)?", value)
    if relative:
        day = now.date() + timedelta(days=1 if "明日" in relative.group(0) else 0)
        hour = int(relative.group(1)) if relative.group(1) else (23 if end else 0)
        minute = int(relative.group(2)) if relative.group(2) else (59 if end else 0)
        second = 59 if end and not relative.group(1) else 0
        return datetime(
            day.year, day.month, day.day, hour, minute, second, tzinfo=JST,
        ), bool(relative.group(1))
    match = re.search(
        r"(?:(20\d{2})\s*[年/-]\s*)?(\d{1,2})\s*[月/-]\s*(\d{1,2})日?"
        r"(?:\s*\([^)]*\))?(?:\s*(\d{1,2})[:時](\d{2})?)?",
        value,
    )
    if not match:
        return None, False
    explicit_year = bool(match.group(1))
    year = int(match.group(1) or now.year)
    hour = int(match.group(4)) if match.group(4) else (23 if end else 0)
    minute = int(match.group(5)) if match.group(5) else (59 if end else 0)
    second = 59 if end and not match.group(4) else 0
    try:
        parsed = datetime(year, int(match.group(2)), int(match.group(3)), hour, minute, second, tzinfo=JST)
    except ValueError:
        return None, False
    if not explicit_year and not (now - timedelta(days=14) <= parsed <= now + timedelta(days=180)):
        return None, False
    return parsed, bool(match.group(4))


def _safe_candidate_url(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").casefold()
        if parsed.scheme.casefold() != "https" or parsed.port not in (None, 443):
            return False
        if parsed.username or parsed.password or not host:
            return False
        if host == "localhost" or host.endswith((".localhost", ".local")):
            return False
        try:
            address = ipaddress.ip_address(host.strip("[]"))
        except ValueError:
            return True
        return address.is_global and not address.is_private
    except ValueError:
        return False


def _destination_type(url: str) -> str:
    host = (urlsplit(url).hostname or "").casefold()
    if host in {
        "livepocket.jp", "t.livepocket.jp", "shoplottery.e-starbox.com",
        "docs.google.com", "select-type.com",
    } or host.endswith(".membercard.jp"):
        return "APPLICATION_PROVIDER"
    if host.endswith(("thebase.in", "base.shop")):
        return "OFFICIAL_EC_CANDIDATE"
    return "OFFICIAL_OR_STORE_CANDIDATE"


def _is_x_url(url: str) -> bool:
    return (urlsplit(str(url or "")).hostname or "").casefold() in _X_HOSTS


def _is_source_url(url: str) -> bool:
    host = (urlsplit(str(url or "")).hostname or "").casefold().removeprefix("www.")
    return host == SOURCE_DOMAIN


def _same_path(left: str, right: str) -> bool:
    try:
        a, b = urlsplit(left), urlsplit(right)
        return (
            (a.hostname or "").casefold().removeprefix("www.") ==
            (b.hostname or "").casefold().removeprefix("www.")
            and a.path.rstrip("/") == b.path.rstrip("/")
        )
    except ValueError:
        return False
