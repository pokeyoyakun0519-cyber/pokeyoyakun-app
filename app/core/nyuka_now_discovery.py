from __future__ import annotations

import hashlib
import json
import re
import unicodedata
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin, urlparse

from core.application_discovery import (
    CANDIDATE,
    CONFIRMED,
    deduplicate_applications,
    parse_discovery_post,
    resolve_candidate,
)
from core.application_filters import canonical_application_url


TIER_A_OFFICIAL = "TIER_A_OFFICIAL"
TIER_B_DISCOVERY = "TIER_B_DISCOVERY"
TIER_C_REFERENCE = "TIER_C_REFERENCE"

NYUKA_NOW_INDEX = "https://nyuka-now.com/archives/category/news"
DEFAULT_TTL_SECONDS = 30 * 60


@dataclass(frozen=True)
class DiscoverySourceDefinition:
    key: str
    name: str
    url: str
    trust_tier: str
    tcg_keys: tuple[str, ...]
    auto_enabled: bool
    adoption_status: str
    note: str = ""


DISCOVERY_SOURCES = (
    DiscoverySourceDefinition(
        "nyuka_now", "入荷Now", NYUKA_NOW_INDEX, TIER_B_DISCOVERY,
        ("pokemon", "onepiece", "dragon_ball_fusion_world"), True,
        "SAFE_PUBLIC_HTML",
        "一覧差分と新着記事だけを確認。単独ではconfirmedにしない。",
    ),
    DiscoverySourceDefinition(
        "wanpicagraph", "ワンピカグラフ",
        "https://wanpicagraph.com/op/lottery/", TIER_B_DISCOVERY,
        ("onepiece",), False, "AUDITED_NOT_ENABLED",
        "構造と更新性は良好だが、専用parserとrobots再確認前のため自動取得しない。",
    ),
    DiscoverySourceDefinition(
        "pokesoku", "ポケ速", "https://pokesoku.com/lottery-2026-08/",
        TIER_B_DISCOVERY, ("pokemon",), False, "AUDITED_NOT_ENABLED",
        "更新中の公式リンク付き一覧を確認。専用parser/robots確認前は自動取得しない。",
    ),
    DiscoverySourceDefinition(
        "tcg_calendar", "TCGカレンダー", "https://tcgcalendar.jp/",
        TIER_C_REFERENCE, ("pokemon", "onepiece", "dragon_ball_fusion_world"),
        False, "REFERENCE_ONLY", "継続更新性を追加評価するまで参考情報に限定。",
    ),
    DiscoverySourceDefinition(
        "toreca_signal", "トレカシグナル", "https://torecasignal.com/",
        TIER_B_DISCOVERY, ("pokemon", "onepiece"), False, "AUDITED_NOT_ENABLED",
        "更新中の構造化一覧を確認。専用parser/robots確認前は自動取得しない。",
    ),
)


_OFFICIAL_DESTINATION_DOMAINS = (
    "pokemoncenter-online.com", "pokemon-card.com", "pokemon.co.jp",
    "onepiece-cardgame.com", "bandainamco-am.co.jp", "p-bandai.jp",
    "livepocket.jp", "cardlabo.com", "hbst.net", "hobby-station.com",
    "amazon.co.jp", "books.rakuten.co.jp", "7net.omni7.jp",
)
_CHAIN_PATTERNS = (
    "カードラボ", "ホビーステーション", "バトロコ", "プレイズ",
    "お宝創庫", "カードボックス", "TSUTAYA", "ふるいち", "古本市場",
    "BOOKOFF", "Amazon", "楽天ブックス", "セブンネット",
    "ポケモンセンター", "プレミアムバンダイ", "麦わらストア",
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


class _IndexParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.current_url = ""
        self.parts: list[str] = []
        self.articles: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        href = dict(attrs).get("href") or ""
        url = canonical_application_url(urljoin(self.base_url, href))
        if re.fullmatch(r"https://nyuka-now\.com/archives/\d+/?", url):
            self.current_url = url.rstrip("/")
            self.parts = []

    def handle_data(self, data: str) -> None:
        if self.current_url and data.strip():
            self.parts.append(data.strip())

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or not self.current_url:
            return
        title = re.sub(r"\s+", " ", " ".join(self.parts)).strip()
        if title:
            self.articles.append({"url": self.current_url, "title": title})
        self.current_url = ""
        self.parts = []


class _ArticleParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.links: list[dict[str, str]] = []
        self.text_parts: list[str] = []
        self.content_links: list[dict[str, str]] = []
        self.content_text_parts: list[str] = []
        self.title = ""
        self.published_at = ""
        self._link_url = ""
        self._link_parts: list[str] = []
        self._in_title = False
        self._content_depth = 0
        self._content_root_tag = ""
        self._link_in_content = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {str(key).lower(): str(value or "") for key, value in attrs}
        lowered = tag.lower()
        classes = set(values.get("class", "").split())
        if lowered == "article" or (
            lowered in {"div", "section"}
            and classes & {"entry-content", "article-body", "post-content", "content"}
        ):
            if self._content_depth == 0:
                self._content_root_tag = lowered
            self._content_depth += 1
        elif self._content_depth:
            self._content_depth += 1
        if lowered == "meta":
            key = values.get("property") or values.get("name")
            if key in {"article:published_time", "date", "datepublished"}:
                self.published_at = values.get("content", "")
            if key in {"og:title", "twitter:title"} and not self.title:
                self.title = values.get("content", "")
        elif lowered == "time" and not self.published_at:
            self.published_at = values.get("datetime", "")
        elif lowered == "a":
            self._link_url = canonical_application_url(
                urljoin(self.base_url, values.get("href", ""))
            )
            self._link_parts = []
            self._link_in_content = self._content_depth > 0
        elif lowered == "h1":
            self._in_title = True

    def handle_data(self, data: str) -> None:
        value = data.strip()
        if not value:
            return
        self.text_parts.append(value)
        if self._content_depth:
            self.content_text_parts.append(value)
        if self._link_url:
            self._link_parts.append(value)
        if self._in_title and not self.title:
            self.title = value

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered == "a" and self._link_url:
            self.links.append({
                "url": self._link_url,
                "text": re.sub(r"\s+", " ", " ".join(self._link_parts)).strip(),
            })
            if self._link_in_content:
                self.content_links.append(dict(self.links[-1]))
            self._link_url = ""
            self._link_parts = []
            self._link_in_content = False
        elif lowered == "h1":
            self._in_title = False
        if self._content_depth:
            self._content_depth -= 1
            if self._content_depth == 0:
                self._content_root_tag = ""


class NyukaNowDiscovery:
    """Low-frequency discovery sensor for public 入荷Now articles.

    Discovery values are hints only.  They are intentionally stored as
    TIER_B evidence and cannot satisfy official confirmation.
    """

    def __init__(
        self,
        root: Path,
        *,
        opener: Callable[..., Any] | None = None,
        now: Callable[[], datetime] | None = None,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ) -> None:
        self.root = Path(root)
        self.opener = opener or urllib.request.urlopen
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.ttl_seconds = max(300, int(ttl_seconds))
        self.state_path = self.root / "data" / "discovery" / "nyuka_now_state.json"
        self._state = self._load_state()
        self.last_diagnostics = self._empty_diagnostics()
        self.last_diagnostics.update({
            "last_check": str(self._state.get("last_check", "")),
            "last_success": str(self._state.get("last_success", self._state.get("last_check", ""))),
            "error": str(self._state.get("error", "")),
        })

    @staticmethod
    def parse_index(html: str) -> list[dict[str, str]]:
        parser = _IndexParser(NYUKA_NOW_INDEX)
        parser.feed(str(html or ""))
        output: list[dict[str, str]] = []
        seen: set[str] = set()
        for article in parser.articles:
            if article["url"] not in seen:
                seen.add(article["url"])
                output.append(article)
        return output

    @staticmethod
    def parse_article(
        html: str, article_url: str, *, title_hint: str = ""
    ) -> dict[str, Any] | None:
        parser = _ArticleParser(article_url)
        parser.feed(str(html or ""))
        title = parser.title or title_hint
        if not parser.published_at:
            published = re.search(
                r'"datePublished"\s*:\s*"([^"]+)"|'
                r'<meta[^>]+(?:property|name)=["\']article:published_time["\'][^>]+content=["\']([^"\']+)',
                str(html or ""), re.I,
            )
            if published:
                parser.published_at = published.group(1) or published.group(2) or ""
        text_parts = parser.content_text_parts or parser.text_parts
        links = parser.content_links or parser.links
        text = "\n".join(text_parts)
        parsed = parse_discovery_post(f"{title}\n{text}")
        tcg = str(parsed.get("tcg_key", "other"))
        if tcg not in {"pokemon", "onepiece", "dragon_ball_fusion_world"}:
            return None
        destinations = []
        seen_destinations: set[str] = set()
        for link in links:
            url = str(link.get("url", ""))
            host = (urlparse(url).hostname or "").casefold()
            if host == "nyuka-now.com" or not any(
                host == domain or host.endswith("." + domain)
                for domain in _OFFICIAL_DESTINATION_DOMAINS
            ):
                continue
            if url not in seen_destinations:
                seen_destinations.add(url)
                destinations.append({"url": url, "label": link.get("text", "")})
        chain = next((name for name in _CHAIN_PATTERNS if name.casefold() in text.casefold()), "")
        prefecture = next((name for name in _PREFECTURES if name in text), "")
        mode_hint = "UNKNOWN"
        if re.search(r"Web応募.*店舗受取|オンライン応募.*店頭", text, re.I):
            mode_hint = "HYBRID"
        elif re.search(r"通販|オンライン|Amazon|楽天ブックス|セブンネット", text, re.I):
            mode_hint = "ONLINE"
        elif re.search(r"店頭抽選|店頭販売|(?:店舗|店頭)受取", text, re.I):
            mode_hint = "STORE"
        product_name = _product_from_title(title) or str(parsed.get("product_name", ""))
        source_url = canonical_application_url(article_url)
        candidate = {
            **parsed,
            "source_name": "入荷Now",
            "source_type": "DISCOVERY_SOURCE",
            "source_article_url": source_url,
            "source_url": source_url,
            "article_title": title.strip(),
            "article_published_at": parser.published_at,
            "product_name": product_name,
            "store_name": chain,
            "chain": chain,
            "branch": "",
            "prefecture": prefecture,
            "sales_mode": "UNKNOWN",
            "sales_mode_hint": mode_hint,
            "official_destination_candidates": destinations,
            "verification_status": CANDIDATE,
            "confirmed": False,
            "trust_tier": TIER_B_DISCOVERY,
            "evidence_sources": [source_url],
            "discovered_store_candidate": bool(chain and not destinations),
            "evidence": [{
                "source_type": "DISCOVERY_SOURCE",
                "source_url": source_url,
                "observed_at": datetime.now(timezone.utc).isoformat(),
                "trust": 60,
                "verification_status": CANDIDATE,
                "extracted_fields": {
                    "article_title": title.strip(),
                    "sales_mode_hint": mode_hint,
                    "official_destination_candidates": destinations,
                },
            }],
        }
        return resolve_candidate(candidate)

    def discover_from_documents(
        self,
        index_html: str,
        article_documents: dict[str, str],
    ) -> list[dict[str, Any]]:
        articles = self.parse_index(index_html)
        seen_urls = set(self._state.get("seen_article_urls", []))
        new_articles = [item for item in articles if item["url"] not in seen_urls]
        candidates = []
        for article in new_articles:
            html = article_documents.get(article["url"])
            if html is None:
                continue
            candidate = self.parse_article(html, article["url"], title_hint=article["title"])
            seen_urls.add(article["url"])
            if candidate:
                candidates.append(candidate)
        self._state["seen_article_urls"] = sorted(seen_urls)[-2000:]
        self._state["last_check"] = self.now().isoformat()
        self._save_state()
        unique = merge_discovery_candidates(candidates)
        self.last_diagnostics.update({
            "last_check": self._state["last_check"],
            "last_success": self._state["last_check"],
            "new_articles": len(new_articles),
            "candidates": len(unique),
            "duplicate_count": len(candidates) - len(unique),
            "cache_hit": 0,
            "request_count": 0,
            "error": "",
        })
        return unique

    def poll(self) -> list[dict[str, Any]]:
        last_check = _parse_datetime(self._state.get("last_check"))
        if last_check and self.now() - last_check < timedelta(seconds=self.ttl_seconds):
            self.last_diagnostics["cache_hit"] = 1
            self.last_diagnostics["last_check"] = last_check.isoformat()
            return []
        try:
            index = self._fetch(NYUKA_NOW_INDEX, conditional=True)
            if index["not_modified"]:
                self._state["last_check"] = self.now().isoformat()
                self._save_state()
                self.last_diagnostics.update({
                    "last_check": self._state["last_check"], "last_success": self._state["last_check"],
                    "cache_hit": 1, "request_count": 1,
                })
                return []
            articles = self.parse_index(index["text"])
            seen = set(self._state.get("seen_article_urls", []))
            new_articles = [item for item in articles if item["url"] not in seen]
            candidates = []
            request_count = 1
            for article in new_articles:
                response = self._fetch(article["url"])
                request_count += 1
                seen.add(article["url"])
                candidate = self.parse_article(
                    response["text"], article["url"], title_hint=article["title"]
                )
                if candidate:
                    candidates.append(candidate)
            self._state.update({
                "seen_article_urls": sorted(seen)[-2000:],
                "last_check": self.now().isoformat(),
                "last_success": self.now().isoformat(),
                "error": "",
                "etag": index.get("etag", ""),
                "last_modified": index.get("last_modified", ""),
            })
            self._save_state()
            unique = merge_discovery_candidates(candidates)
            self.last_diagnostics.update({
                "last_check": self._state["last_check"],
                "last_success": self._state["last_check"],
                "new_articles": len(new_articles), "candidates": len(unique),
                "duplicate_count": len(candidates) - len(unique),
                "cache_hit": 0, "request_count": request_count, "error": "",
            })
            return unique
        except (OSError, ValueError, urllib.error.URLError) as error:
            self._state.update({"last_check": self.now().isoformat(), "error": type(error).__name__})
            self._save_state()
            self.last_diagnostics.update({
                "last_check": self.now().isoformat(), "error": type(error).__name__,
            })
            return []

    def poll_and_store(self) -> list[dict[str, Any]]:
        discovered = self.poll()
        if not discovered:
            return []
        destination = self.root / "data" / "discovery" / "application_candidates.json"
        existing: list[dict[str, Any]] = []
        if destination.exists():
            try:
                loaded = json.loads(destination.read_text(encoding="utf-8"))
                if not isinstance(loaded, list):
                    raise ValueError("candidate store is not a list")
                existing = [item for item in loaded if isinstance(item, dict)]
            except (OSError, ValueError, TypeError):
                self.last_diagnostics["error"] = "candidate_store_corrupt"
                return []
        combined = merge_discovery_candidates([*existing, *discovered])
        self.last_diagnostics["duplicate_count"] += len(existing) + len(discovered) - len(combined)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(combined, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        temporary.replace(destination)
        return discovered

    def diagnostics(self) -> dict[str, Any]:
        return dict(self.last_diagnostics)

    def _fetch(self, url: str, *, conditional: bool = False) -> dict[str, Any]:
        headers = {"User-Agent": "PokeyoyaKun/1.25 WebDiscovery (+public HTML only)"}
        if conditional and self._state.get("etag"):
            headers["If-None-Match"] = str(self._state["etag"])
        if conditional and self._state.get("last_modified"):
            headers["If-Modified-Since"] = str(self._state["last_modified"])
        request = urllib.request.Request(url, headers=headers)
        try:
            response = self.opener(request, timeout=15)
            with response:
                body = response.read()
                response_headers = getattr(response, "headers", {})
                return {
                    "text": body.decode("utf-8", errors="replace"),
                    "etag": str(response_headers.get("ETag", "")),
                    "last_modified": str(response_headers.get("Last-Modified", "")),
                    "not_modified": False,
                }
        except urllib.error.HTTPError as error:
            if error.code == 304:
                return {"text": "", "etag": "", "last_modified": "", "not_modified": True}
            raise

    def _load_state(self) -> dict[str, Any]:
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError, TypeError):
            return {}

    def _save_state(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(self._state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        temporary.replace(self.state_path)

    @staticmethod
    def _empty_diagnostics() -> dict[str, Any]:
        return {
            "source_name": "入荷Now", "source_url": NYUKA_NOW_INDEX,
            "trust_tier": TIER_B_DISCOVERY, "last_check": "", "last_success": "",
            "new_articles": 0, "candidates": 0, "official_verified": 0,
            "verification_failed": 0, "duplicate_count": 0, "error": "",
            "cache_hit": 0, "request_count": 0,
        }


class OfficialVerificationQueue:
    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []
        self.official_verified = 0
        self.verification_failed = 0

    def enqueue(self, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        self.items = merge_discovery_candidates([*self.items, *candidates])
        for item in self.items:
            item["verification_priority"] = _verification_priority(item)
        order = {"HIGH": 0, "NORMAL": 1, "LOW": 2}
        self.items.sort(key=lambda value: order[value["verification_priority"]])
        return [dict(item) for item in self.items]

    def verify_next(
        self, verifier: Callable[[dict[str, Any]], dict[str, Any] | None]
    ) -> dict[str, Any] | None:
        if not self.items:
            return None
        candidate = self.items.pop(0)
        official = verifier(dict(candidate))
        if not official or not official.get("evidence"):
            candidate["verification_status"] = CANDIDATE
            candidate["confirmed"] = False
            candidate["verification_error"] = "official_verification_failed"
            self.verification_failed += 1
            return candidate
        merged = dict(candidate)
        for key, value in official.items():
            if key != "evidence" and value not in (None, "", []):
                merged[key] = value
        merged["evidence"] = [*candidate.get("evidence", []), *official.get("evidence", [])]
        resolved = resolve_candidate(merged)
        if resolved["verification_status"] == CONFIRMED:
            self.official_verified += 1
        else:
            self.verification_failed += 1
        return resolved

    def diagnostics(self) -> dict[str, int]:
        return {
            "queue_size": len(self.items),
            "official_verified": self.official_verified,
            "verification_failed": self.verification_failed,
        }


def official_verification_from_document(
    candidate: dict[str, Any], official_url: str, html: str
) -> dict[str, Any] | None:
    """Build TIER_A evidence only from a known official/retailer destination."""
    url = canonical_application_url(official_url)
    host = (urlparse(url).hostname or "").casefold()
    if not url or not any(
        host == domain or host.endswith("." + domain)
        for domain in _OFFICIAL_DESTINATION_DOMAINS
    ):
        return None
    parser = _ArticleParser(url)
    parser.feed(str(html or ""))
    text = "\n".join(parser.content_text_parts or parser.text_parts)
    parsed = parse_discovery_post(text, tcg_hint=str(candidate.get("tcg_key", "")))
    if parsed.get("application_type") not in {"LOTTERY", "RESERVATION", "RESTOCK"}:
        return None
    product = _normalized_text(candidate.get("product_name"))
    code = _normalized_text(candidate.get("product_code"))
    normalized_text = _normalized_text(text)
    if product and product not in normalized_text and (not code or code not in normalized_text):
        return None
    official_mode = "UNKNOWN"
    if re.search(r"Web応募.*(?:店頭|店舗)受取|オンライン応募.*(?:店頭|店舗)", text, re.I):
        official_mode = "HYBRID"
    elif re.search(r"通販|オンライン販売|配送", text, re.I):
        official_mode = "ONLINE"
    elif re.search(r"店頭抽選|店頭販売|(?:店頭|店舗)受取", text, re.I):
        official_mode = "STORE"
    fields = {
        key: value for key, value in parsed.items()
        if key in {
            "application_type", "application_start_at", "application_end_at",
            "result_announcement_at", "product_code",
        } and value not in (None, "")
    }
    return {
        **fields,
        "application_url": url,
        "sales_mode": official_mode,
        "trust_tier": TIER_A_OFFICIAL,
        "evidence": [{
            "source_type": (
                "OFFICIAL_MANUFACTURER"
                if host.endswith(("pokemon-card.com", "onepiece-cardgame.com", "bandainamco-am.co.jp"))
                else "OFFICIAL_STORE"
            ),
            "source_url": url,
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "trust": 100,
            "verification_status": CONFIRMED,
            "extracted_fields": fields,
        }],
    }


def merge_discovery_candidates(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for item in deduplicate_applications(items):
        key = _discovery_identity(item)
        existing = next((value for value in merged if _discovery_identity(value) == key), None)
        if existing is None:
            value = dict(item)
            value["evidence_sources"] = list(dict.fromkeys(value.get("evidence_sources", [])))
            merged.append(value)
            continue
        existing["evidence_sources"] = list(dict.fromkeys([
            *existing.get("evidence_sources", []), *item.get("evidence_sources", []),
        ]))
        existing["evidence"] = [*existing.get("evidence", []), *item.get("evidence", [])]
        existing.update(resolve_candidate(existing))
    return merged


def discovery_source_diagnostics(official_source_count: int = 0) -> dict[str, Any]:
    tiers = {TIER_A_OFFICIAL: max(0, official_source_count), TIER_B_DISCOVERY: 0, TIER_C_REFERENCE: 0}
    for source in DISCOVERY_SOURCES:
        tiers[source.trust_tier] += 1
    return {
        "sources": [source.__dict__.copy() for source in DISCOVERY_SOURCES],
        "by_trust_tier": tiers,
        "auto_enabled": [source.key for source in DISCOVERY_SOURCES if source.auto_enabled],
    }


def _discovery_identity(item: dict[str, Any]) -> str:
    destinations = item.get("official_destination_candidates", [])
    destination = ""
    if isinstance(destinations, list) and destinations:
        destination = str(destinations[0].get("url", "")) if isinstance(destinations[0], dict) else str(destinations[0])
    fields = (
        item.get("tcg_key"),
        item.get("product_name") or item.get("article_title") or item.get("source_article_url"),
        item.get("chain"),
        item.get("branch"), item.get("application_end_at"), destination,
    )
    normalized = "|".join(
        re.sub(r"[\s　「」『』・_\-/]", "", unicodedata.normalize("NFKC", str(value or ""))).casefold()
        for value in fields
    )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _verification_priority(item: dict[str, Any]) -> str:
    sources = len(set(item.get("evidence_sources", [])))
    if sources >= 2:
        return "HIGH"
    if not item.get("product_name") or not item.get("store_name"):
        return "LOW"
    end = _parse_datetime(item.get("application_end_at"))
    if end and end - datetime.now(timezone.utc) <= timedelta(hours=72):
        return "HIGH"
    if item.get("chain") in _CHAIN_PATTERNS:
        return "HIGH"
    return "NORMAL"


def _product_from_title(title: str) -> str:
    value = re.sub(r"^[〖【\[].*?[〗】\]]", "", title).strip()
    value = re.sub(r"(?:の)?(?:Amazon)?(?:販売予定|予約|抽選).*$", "", value).strip()
    return value[:200]


def _parse_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _normalized_text(value: Any) -> str:
    return re.sub(
        r"[\s　「」『』【】〖〗・_\-/]", "",
        unicodedata.normalize("NFKC", str(value or "")),
    ).casefold()
