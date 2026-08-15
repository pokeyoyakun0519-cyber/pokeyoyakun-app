from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timedelta, timezone
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable

from core.application_site import normalize_application_site
from core.log_manager import LogManager
from core.runtime_paths import app_root
from core.secure_https import build_https_opener
from core.tcg_categories import display_name, normalize_key


FetchResult = tuple[int, str, str]
FetchCallable = Callable[[str, float], FetchResult]
JST = timezone(timedelta(hours=9))


TCG_PATTERNS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "yugioh",
        "rush",
        (
            "遊戯王ラッシュデュエル",
            "遊戯王rd",
            "rush duel",
        ),
    ),
    (
        "yugioh",
        "ocg",
        (
            "遊戯王ocg",
            "遊☆戯☆王ocg",
            "遊戯王オフィシャルカードゲーム",
        ),
    ),
    (
        "pokemon",
        "",
        ("ポケモンカードゲーム", "ポケモンカード", "ポケカ"),
    ),
    (
        "onepiece",
        "",
        (
            "one pieceカードゲーム",
            "one piece card game",
            "ワンピースカードゲーム",
        ),
    ),
    (
        "gundam",
        "",
        ("ガンダムカードゲーム", "gundam card game"),
    ),
    (
        "duelmasters",
        "",
        ("デュエル・マスターズ", "デュエルマスターズ", "デュエマ"),
    ),
    (
        "weiss",
        "",
        ("ヴァイスシュヴァルツ", "weiss schwarz", "wsr ", "ws "),
    ),
    (
        "mtg",
        "",
        (
            "magic: the gathering",
            "magic：the gathering",
            "マジック：ザ・ギャザリング",
            "マジック:ザ・ギャザリング",
            "mtg ",
        ),
    ),
)


STORE_SLUGS = {
    "namba": "なんば店",
    "ikebukuro": "池袋店",
    "otaro": "オタロード本店",
    "osaka-nihonbashi": "大阪日本橋店",
    "tennouji": "天王寺店",
    "chibatyuuou": "千葉中央店",
    "okayamanishi": "岡山西口店",
    "utsunomiya": "宇都宮店",
    "kumamoto": "熊本店",
    "hamamatsu": "浜松店",
    "toyohashi": "豊橋店",
    "takasaki": "高崎店",
    "niigata": "新潟店",
    "fukuokatenjin": "福岡天神店",
    "hakata-marui": "博多マルイ店",
    "kagoshima": "鹿児島店",
    "kokura": "小倉店",
    "sendai": "仙台店",
    "shizuoka": "静岡店",
    "gifu": "岐阜店",
}


class _PageParser(HTMLParser):
    """本文、見出し、リンク、画像数を取得する。画像自体は保存しない。"""

    def __init__(self, base_url: str, *, article_only: bool = False):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self._article_only = article_only
        self.title = ""
        self.og_title = ""
        self.headings: list[str] = []
        self.links: list[dict[str, str]] = []
        self.text_parts: list[str] = []
        self.image_count = 0
        self._in_article = not article_only
        self._in_title = False
        self._heading_tag = ""
        self._heading_parts: list[str] = []
        self._link_url = ""
        self._link_parts: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        lowered = tag.casefold()
        values = {key.casefold(): value or "" for key, value in attrs}
        if lowered == "article":
            self._in_article = True
        if lowered == "title":
            self._in_title = True
        if lowered == "meta":
            key = (
                values.get("property")
                or values.get("name")
                or ""
            ).casefold()
            if key == "og:title":
                self.og_title = values.get("content", "").strip()
        if lowered in {"h1", "h2", "h3", "h4"}:
            self._heading_tag = lowered
            self._heading_parts = []
        if lowered == "a" and self._in_article:
            self._link_url = urllib.parse.urljoin(
                self.base_url,
                values.get("href", "").strip(),
            )
            self._link_parts = []
        if lowered == "img" and self._in_article:
            self.image_count += 1
            alt = values.get("alt", "").strip()
            if alt:
                self.text_parts.append(alt)
                if self._link_url:
                    self._link_parts.append(alt)
        if self._in_article and lowered in {
            "p", "div", "li", "section", "article", "main",
            "h1", "h2", "h3", "h4", "tr", "td", "th", "br",
        }:
            self.text_parts.append("\n")

    def handle_data(self, data: str) -> None:
        clean = re.sub(r"\s+", " ", data).strip()
        if not clean:
            return
        if self._in_title:
            self.title += clean
        if self._heading_tag:
            self._heading_parts.append(clean)
        if self._link_url:
            self._link_parts.append(clean)
        if self._in_article:
            self.text_parts.append(clean)

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.casefold()
        if lowered == "title":
            self._in_title = False
        if lowered == self._heading_tag:
            heading = " ".join(self._heading_parts).strip()
            if heading:
                self.headings.append(heading)
            self._heading_tag = ""
            self._heading_parts = []
        if lowered == "a" and self._link_url:
            self.links.append({
                "url": self._link_url,
                "text": " ".join(self._link_parts).strip(),
            })
            self._link_url = ""
            self._link_parts = []
        if self._in_article and lowered in {
            "p", "div", "li", "section", "article", "main",
            "h1", "h2", "h3", "h4", "tr", "td", "th",
        }:
            self.text_parts.append("\n")
        if lowered == "article":
            self._in_article = not self._article_only

    def result(self) -> dict[str, Any]:
        lines: list[str] = []
        for raw in re.split(r"[\r\n]+", " ".join(self.text_parts)):
            clean = re.sub(r"\s+", " ", raw).strip()
            if clean and (not lines or lines[-1] != clean):
                lines.append(clean)
        title = self.og_title or self.title
        title = re.sub(
            r"\s*/\s*[^/]*?店舗ブログ(?:\s*-\s*カードラボ)?\s*$",
            "",
            title,
        )
        title = re.sub(r"\s*[-–|/]\s*カードラボ.*$", "", title).strip()
        return {
            "title": title,
            "headings": self.headings,
            "text": "\n".join(lines),
            "links": self.links,
            "image_count": self.image_count,
        }


class _CalendarParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.page_year = datetime.now(JST).year
        self.current_heading = ""
        self.rows: list[tuple[str, list[str]]] = []
        self._heading = False
        self._heading_parts: list[str] = []
        self._row = False
        self._cell = False
        self._cell_parts: list[str] = []
        self._cells: list[str] = []
        self._title = False
        self._title_parts: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        lowered = tag.casefold()
        if lowered == "title":
            self._title = True
        elif lowered in {"h2", "h3", "h4"}:
            self._heading = True
            self._heading_parts = []
        elif lowered == "tr":
            self._row = True
            self._cells = []
        elif lowered in {"td", "th"} and self._row:
            self._cell = True
            self._cell_parts = []

    def handle_data(self, data: str) -> None:
        clean = re.sub(r"\s+", " ", data).strip()
        if not clean:
            return
        if self._title:
            self._title_parts.append(clean)
        if self._heading:
            self._heading_parts.append(clean)
        if self._cell:
            self._cell_parts.append(clean)

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.casefold()
        if lowered == "title":
            self._title = False
            title = " ".join(self._title_parts)
            match = re.search(r"(20\d{2})", title)
            if match:
                self.page_year = int(match.group(1))
        elif lowered in {"h2", "h3", "h4"} and self._heading:
            self._heading = False
            heading = " ".join(self._heading_parts).strip()
            if re.search(r"\d{1,2}月\d{1,2}日", heading):
                self.current_heading = heading
        elif lowered in {"td", "th"} and self._cell:
            self._cell = False
            self._cells.append(" ".join(self._cell_parts).strip())
        elif lowered == "tr" and self._row:
            self._row = False
            if self.current_heading and len(self._cells) >= 3:
                self.rows.append((self.current_heading, list(self._cells)))


class _CardLaboRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req,
        fp,
        code,
        msg,
        headers,
        newurl,
    ):
        parsed = urllib.parse.urlparse(str(newurl or ""))
        if (
            parsed.scheme != "https"
            or (parsed.hostname or "").casefold() != "www.c-labo.jp"
            or parsed.port not in {None, 443}
        ):
            raise urllib.error.HTTPError(
                str(newurl),
                int(code),
                "カードラボ以外へのリダイレクトを拒否しました。",
                headers,
                fp,
            )
        return super().redirect_request(
            req,
            fp,
            code,
            msg,
            headers,
            newurl,
        )


class CardLaboParser:
    BASE_URL = "https://www.c-labo.jp/"
    RSS_URL = "https://www.c-labo.jp/blog/feed/"
    BLOG_URL = "https://www.c-labo.jp/blog/"
    BLOG_PAGE_2_URL = "https://www.c-labo.jp/blog/page/2/"
    CALENDAR_URL = "https://www.c-labo.jp/special/2028/"
    ALLOWED_HOST = "www.c-labo.jp"
    USER_AGENT = (
        "PokeyoyaKun/1.25.0 "
        "(Windows; +https://pokeyoyakun.com)"
    )
    EXTERNAL_APPLICATION_HOSTS = {
        "x.com",
        "twitter.com",
        "livepocket.jp",
        "t.livepocket.jp",
    }
    APPLICATION_TYPES = {"lottery", "reservation", "resale"}

    def __init__(
        self,
        *,
        fetcher: FetchCallable | None = None,
        log_manager: LogManager | None = None,
        state_path: Path | None = None,
        timeout_seconds: float = 15.0,
        max_retries: int = 1,
        request_interval_seconds: float = 0.5,
        max_article_requests: int = 30,
        now_provider: Callable[[], datetime] | None = None,
    ):
        self.fetcher = fetcher or self._default_fetch
        self.log_manager = log_manager or LogManager()
        self.state_path = (
            Path(state_path)
            if state_path is not None
            else app_root() / "config" / "card_labo_state.json"
        )
        self.timeout_seconds = min(15.0, max(10.0, float(timeout_seconds)))
        self.max_retries = max(0, min(1, int(max_retries)))
        minimum_interval = 0.0 if fetcher is not None else 0.5
        self.request_interval_seconds = min(
            1.0,
            max(minimum_interval, float(request_interval_seconds)),
        )
        self.max_article_requests = max(1, min(30, int(max_article_requests)))
        self.now_provider = now_provider or (
            lambda: datetime.now(timezone.utc)
        )
        self._cache: dict[str, FetchResult] = {}
        self._failed_urls: set[str] = set()
        self._requested_hosts: Counter[str] = Counter()
        self._last_request_at = 0.0
        self._scanned = False
        self._records: list[dict[str, Any]] = []
        self.last_diagnostics: dict[str, Any] = {}

    def search_candidate(
        self,
        candidate: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], str]:
        self.scan()
        candidate_tcg = normalize_key(
            candidate.get("tcg_key"),
            candidate.get("tcg") or candidate.get("category"),
        )[0]
        candidate_variant = str(candidate.get("tcg_variant", "")).casefold()
        matched: list[dict[str, Any]] = []
        for record in self._records:
            if record.get("tcg_key") != candidate_tcg:
                continue
            record_variant = str(record.get("tcg_variant", "")).casefold()
            if (
                candidate_tcg == "yugioh"
                and candidate_variant
                and record_variant
                and candidate_variant != record_variant
            ):
                continue
            if self._matches_candidate(candidate, record):
                matched.append(record)
        hits = [self._build_hit(record) for record in matched]
        hits = [hit for hit in hits if hit]
        product_count = sum(
            1 for record in matched
            if record.get("article_type") in {
                "product_info", "regular_sale"
            }
        )
        application_count = sum(
            1 for record in matched
            if record.get("article_type") in self.APPLICATION_TYPES
            and record.get("application_evidence")
        )
        self.last_diagnostics["product_saved_count"] = product_count
        self.last_diagnostics["application_saved_count"] = application_count
        self._log(f"カードラボ商品保存件数: {product_count}件")
        self._log(f"カードラボ応募案件保存件数: {application_count}件")
        return (
            hits,
            f"カードラボ: 商品{product_count}件 / 応募{application_count}件",
        )

    def scan(self, *, force: bool = False) -> list[dict[str, Any]]:
        if self._scanned and not force:
            return [dict(record) for record in self._records]
        started = time.monotonic()
        self._failed_urls.clear()
        self._requested_hosts.clear()
        diagnostics: dict[str, Any] = {
            "rss_detected_count": 0,
            "blog_supplement_count": 0,
            "parsed_url_count": 0,
            "article_type_counts": {},
            "tcg_counts": {},
            "store_counts": {},
            "product_record_count": 0,
            "application_record_count": 0,
            "ended_count": 0,
            "needs_review_count": 0,
            "image_only_excluded_count": 0,
            "excluded_count": 0,
            "excluded_reasons": {},
            "http_failure_count": 0,
            "external_host_request_count": 0,
            "requested_hosts": {},
            "elapsed_seconds": 0.0,
        }
        excluded: Counter[str] = Counter()
        state = self._load_state()
        checked_ids = {
            str(value)
            for value in state.get("checked_article_ids", [])
            if str(value)
        }
        cached_article_records = [
            dict(record)
            for record in state.get("article_records", [])
            if isinstance(record, dict)
            and str(record.get("article_id", ""))
            and self._is_article_url(
                self._canonical_url(record.get("article_url", ""))
            )
            and str(record.get("article_type", "")) not in {
                "", "excluded", "event", "general_news"
            }
        ]

        rss_entries: list[dict[str, str]] = []
        rss_response = self._request(self.RSS_URL)
        if rss_response:
            rss_entries = self.parse_rss(rss_response[1])[:10]
        else:
            excluded["RSS取得失敗"] += 1
        diagnostics["rss_detected_count"] = len(rss_entries)
        self._log(f"カードラボRSS取得件数: {len(rss_entries)}件")

        page_one_entries: list[dict[str, str]] = []
        blog_response = self._request(self.BLOG_URL)
        if blog_response:
            page_one_entries = self.parse_blog_listing(
                blog_response[1],
                blog_response[2],
            )
        else:
            excluded["ブログ一覧取得失敗"] += 1

        combined: list[dict[str, str]] = []
        seen_ids: set[str] = set()
        rss_ids = {
            self._article_id(entry.get("url", ""))
            for entry in rss_entries
        }
        for entry in [*rss_entries, *page_one_entries]:
            article_id = self._article_id(entry.get("url", ""))
            if not article_id or article_id in seen_ids:
                continue
            seen_ids.add(article_id)
            combined.append({**entry, "article_id": article_id})
        diagnostics["blog_supplement_count"] = sum(
            1
            for entry in page_one_entries
            if self._article_id(entry.get("url", "")) not in rss_ids
        )
        self._log(
            "カードラボブログ一覧補完件数: "
            f"{diagnostics['blog_supplement_count']}件"
        )

        reached_known = any(
            str(entry.get("article_id", "")) in checked_ids
            for entry in combined
        )
        if checked_ids and combined and not reached_known:
            page_two_response = self._request(self.BLOG_PAGE_2_URL)
            if page_two_response:
                for entry in self.parse_blog_listing(
                    page_two_response[1],
                    page_two_response[2],
                ):
                    article_id = self._article_id(entry.get("url", ""))
                    if not article_id or article_id in seen_ids:
                        continue
                    seen_ids.add(article_id)
                    combined.append({**entry, "article_id": article_id})
                    if article_id in checked_ids:
                        break

        article_records: list[dict[str, Any]] = []
        successfully_checked: set[str] = set()
        for entry in combined:
            article_id = str(entry.get("article_id", ""))
            if article_id in checked_ids and not force:
                break
            if len(successfully_checked) >= self.max_article_requests:
                break
            url = self._canonical_url(entry.get("url", ""))
            if not self._is_article_url(url):
                excluded["記事URL不正"] += 1
                continue
            response = self._request(url)
            if response is None:
                excluded["記事HTTP取得失敗"] += 1
                continue
            record = self.parse_article_html(
                response[1],
                response[2],
                published_at=str(entry.get("published_at", "")),
                now=self.now_provider(),
            )
            diagnostics["parsed_url_count"] += 1
            successfully_checked.add(article_id)
            article_type = str(record.get("article_type", "excluded"))
            if article_type == "excluded":
                reason = str(record.get("exclusion_reason", "対象外"))
                excluded[reason] += 1
                continue
            if article_type == "needs_review":
                if record.get("image_only"):
                    diagnostics["image_only_excluded_count"] += 1
                article_records.append(record)
                continue
            article_records.append(record)

        calendar_records = self._calendar_records(state, excluded)
        # Checked article IDs are an HTTP optimisation, not a data store.  Keep
        # the normalized records as well so the next scan can reuse the result
        # instead of making previously found applications disappear.
        records = self._deduplicate([
            *article_records,
            *cached_article_records,
            *calendar_records,
        ])
        checked_ids.update(successfully_checked)
        self._save_state({
            "last_checked_at": self._now_iso(),
            "checked_article_ids": sorted(checked_ids)[-1000:],
            "calendar_checked_date": self._today_jst(),
            "calendar_records": calendar_records,
            "article_records": [
                record
                for record in records
                if str(record.get("article_id", ""))
                and not str(record.get("article_id", "")).startswith("calendar-")
            ][:500],
        })

        type_counts = Counter(
            str(record.get("article_type", "unknown"))
            for record in records
        )
        tcg_counts = Counter(
            str(record.get("tcg_key", "unknown"))
            for record in records
            if record.get("tcg_key") != "unknown"
        )
        store_counts = Counter(
            str(record.get("store_name", ""))
            for record in records
            if record.get("store_name")
            and record.get("article_type") in self.APPLICATION_TYPES
        )
        application_count = sum(
            1
            for record in records
            if record.get("article_type") in self.APPLICATION_TYPES
            and record.get("application_evidence")
        )
        diagnostics.update({
            "article_type_counts": dict(type_counts),
            "tcg_counts": dict(tcg_counts),
            "store_counts": dict(store_counts),
            "product_record_count": type_counts["product_info"],
            "application_record_count": application_count,
            "ended_count": sum(
                1 for record in records
                if record.get("status") == "終了済み"
            ),
            "needs_review_count": type_counts["needs_review"],
            "excluded_count": sum(excluded.values()),
            "excluded_reasons": dict(excluded),
            "http_failure_count": len(self._failed_urls),
            "external_host_request_count": sum(
                count
                for host, count in self._requested_hosts.items()
                if host != self.ALLOWED_HOST
            ),
            "requested_hosts": dict(self._requested_hosts),
            "elapsed_seconds": round(time.monotonic() - started, 3),
        })
        self.last_diagnostics = diagnostics
        self._records = records
        self._scanned = True
        self._log_summary(diagnostics)
        return [dict(record) for record in records]

    def _calendar_records(
        self,
        state: dict[str, Any],
        excluded: Counter[str],
    ) -> list[dict[str, Any]]:
        if (
            state.get("calendar_checked_date") == self._today_jst()
            and isinstance(state.get("calendar_records"), list)
        ):
            return [
                dict(item)
                for item in state["calendar_records"]
                if isinstance(item, dict)
            ]
        response = self._request(self.CALENDAR_URL)
        if response is None:
            excluded["発売日カレンダー取得失敗"] += 1
            return []
        return self.parse_calendar_html(response[1], response[2])

    @classmethod
    def parse_rss(cls, xml_text: str) -> list[dict[str, str]]:
        if not str(xml_text).strip():
            return []
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return []
        output: list[dict[str, str]] = []
        seen: set[str] = set()
        for item in root.iter():
            if item.tag.rsplit("}", 1)[-1].casefold() != "item":
                continue
            values: dict[str, str] = {}
            for child in list(item):
                key = child.tag.rsplit("}", 1)[-1].casefold()
                if key in {"link", "title", "pubdate"}:
                    values[key] = (child.text or "").strip()
            url = cls._canonical_url(values.get("link", ""))
            article_id = cls._article_id(url)
            if not article_id or article_id in seen:
                continue
            seen.add(article_id)
            output.append({
                "url": url,
                "title": values.get("title", ""),
                "published_at": values.get("pubdate", ""),
            })
        return output[:10]

    @classmethod
    def parse_blog_listing(
        cls,
        html: str,
        base_url: str = BLOG_URL,
    ) -> list[dict[str, str]]:
        parser = _PageParser(base_url)
        try:
            parser.feed(str(html))
        except (ValueError, TypeError):
            return []
        output: list[dict[str, str]] = []
        seen: set[str] = set()
        for link in parser.result().get("links", []):
            url = cls._canonical_url(link.get("url", ""))
            article_id = cls._article_id(url)
            if not article_id or article_id in seen:
                continue
            seen.add(article_id)
            output.append({
                "url": url,
                "title": str(link.get("text", "")),
                "published_at": "",
            })
        return output

    @classmethod
    def parse_calendar_html(
        cls,
        html: str,
        calendar_url: str = CALENDAR_URL,
    ) -> list[dict[str, Any]]:
        parser = _CalendarParser()
        try:
            parser.feed(str(html))
        except (ValueError, TypeError):
            return []
        output: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str]] = set()
        base_month = datetime.now(JST).month
        for heading, cells in parser.rows:
            if cells[0] in {
                "カテゴリ", "カテゴリー", "発売日",
            } or cells[1] == "商品名":
                continue
            cell_date = re.search(
                r"(\d{1,2})月(\d{1,2})日",
                cells[0],
            )
            date_match = re.search(
                r"(\d{1,2})月(\d{1,2})日",
                cells[0] if cell_date else heading,
            )
            if not date_match:
                continue
            month = int(date_match.group(1))
            day = int(date_match.group(2))
            year = parser.page_year + (
                1 if month < max(1, base_month - 3) else 0
            )
            category_text = "" if cell_date else cells[0]
            tcg_key, variant = cls.detect_tcg(category_text)
            if tcg_key == "unknown":
                tcg_key, variant = cls.detect_tcg(cells[1])
            if tcg_key == "unknown":
                continue
            name = cells[1].strip()
            if not name:
                continue
            try:
                release_date = datetime(year, month, day).date().isoformat()
            except ValueError:
                continue
            price = cls._price(cells[2])
            key = (tcg_key, cls._match_text(name), release_date)
            if key in seen:
                continue
            seen.add(key)
            output.append({
                "article_id": f"calendar-{tcg_key}-{release_date}-{len(output)}",
                "article_type": "product_info",
                "article_url": cls._canonical_url(calendar_url),
                "title": name,
                "product_name": name,
                "tcg_key": tcg_key,
                "tcg": cls._tcg_display(tcg_key, variant),
                "tcg_variant": variant,
                "release_date": release_date,
                "price": price,
                "status": "商品情報",
                "application_evidence": False,
                "source": "release_calendar",
                "store_name": "",
                "application_url": "",
                "application_period": "",
                "conditions": [],
            })
        return output

    @classmethod
    def parse_article_html(
        cls,
        html: str,
        article_url: str,
        *,
        published_at: str = "",
        now: datetime | None = None,
    ) -> dict[str, Any]:
        parser = _PageParser(article_url, article_only=True)
        try:
            parser.feed(str(html))
        except (ValueError, TypeError):
            return cls._excluded(article_url, "HTML解析失敗")
        page = parser.result()
        title = str(page.get("title", "")).strip()
        headings = [
            str(value).strip()
            for value in page.get("headings", [])
            if str(value).strip()
        ]
        text = str(page.get("text", "")).strip()
        if not title or not text:
            return cls._excluded(article_url, "タイトルまたは本文欠損")

        title_tcg_key, title_variant = cls.detect_tcg(title)
        tcg_key, variant = title_tcg_key, title_variant
        if tcg_key == "unknown":
            tcg_key, variant = cls.detect_tcg(text)
        article_type = cls.classify_article(title, text, tcg_key)
        if article_type == "excluded":
            return cls._excluded(article_url, "対象外記事")

        store = cls._detect_store(article_url, [title, *headings], text)
        if store["mismatch"]:
            return {
                "article_id": cls._article_id(article_url),
                "article_type": "needs_review",
                "article_url": cls._canonical_url(article_url),
                "title": title,
                "tcg_key": tcg_key,
                "tcg": cls._tcg_display(tcg_key, variant),
                "tcg_variant": variant,
                "store_name": "",
                "status": "要確認",
                "needs_review_reason": "店舗表記不一致",
                "image_only": False,
                "application_evidence": False,
            }

        product_name = cls._product_name(title, text)
        release_date = cls._release_date(f"{title}\n{text}")
        price = cls._price(text)
        application_period = cls._extract_labeled(
            text,
            ("応募期間", "抽選期間", "申込期間", "申し込み期間"),
        )
        reservation_period = cls._extract_labeled(
            text,
            ("予約受付期間", "予約期間"),
        )
        if not application_period:
            application_period = reservation_period
        application_start, application_end = cls._period_datetimes(
            application_period,
            published_at=published_at,
        )
        result_date = cls._extract_labeled(
            text,
            ("当選発表", "抽選発表", "結果発表"),
        )
        purchase_period = cls._extract_labeled(
            text,
            (
                "当選者店頭販売期間",
                "当選者購入期間",
                "当選者店頭予約期間",
                "購入期間",
            ),
        )
        receipt_period = cls._extract_labeled(
            text,
            (
                "予約商品の受取期間",
                "商品お受け取り期間",
                "受取期間",
                "引取期間",
            ),
        )
        links = page.get("links", [])
        application_url = cls._application_url(links, text)
        evidence = (
            article_type in cls.APPLICATION_TYPES
            and any((
                application_url,
                application_period,
                "店頭" in text and any(
                    word in text for word in ("抽選", "予約", "応募")
                ),
                "フォロー" in text and "リポスト" in text,
            ))
        )
        image_only = (
            article_type in cls.APPLICATION_TYPES
            and int(page.get("image_count", 0)) > 0
            and not product_name
            and not any((release_date, price, application_period))
        )
        if image_only:
            if title_tcg_key == "unknown":
                tcg_key, variant = "unknown", ""
            return {
                "article_id": cls._article_id(article_url),
                "article_type": "needs_review",
                "article_url": cls._canonical_url(article_url),
                "title": title,
                "tcg_key": tcg_key,
                "tcg": cls._tcg_display(tcg_key, variant),
                "tcg_variant": variant,
                "store_name": store["name"],
                "status": "要確認",
                "needs_review_reason": "画像情報のみ",
                "image_only": True,
                "application_evidence": False,
            }
        if article_type in cls.APPLICATION_TYPES and not product_name:
            return {
                "article_id": cls._article_id(article_url),
                "article_type": "needs_review",
                "article_url": cls._canonical_url(article_url),
                "title": title,
                "tcg_key": tcg_key,
                "tcg": cls._tcg_display(tcg_key, variant),
                "tcg_variant": variant,
                "store_name": store["name"],
                "status": "要確認",
                "needs_review_reason": "商品名未確定",
                "image_only": False,
                "application_evidence": False,
            }
        status = cls._status(
            article_type,
            application_start,
            application_end,
            now or datetime.now(JST),
            evidence,
        )
        if evidence and not application_url:
            application_url = cls._canonical_url(article_url)
        return {
            "article_id": cls._article_id(article_url),
            "article_type": article_type,
            "article_url": cls._canonical_url(article_url),
            "title": title,
            "product_name": product_name,
            "tcg_key": tcg_key,
            "tcg": cls._tcg_display(tcg_key, variant),
            "tcg_variant": variant,
            "store_name": store["name"],
            "store_slug": store["slug"],
            "release_date": release_date,
            "price": price,
            "application_url": application_url,
            "application_period": application_period,
            "application_start_at": application_start,
            "application_end_at": application_end,
            "result_date": result_date,
            "result_announcement_at": cls._first_datetime(
                result_date,
                published_at=published_at,
            ),
            "purchase_period": purchase_period,
            "receipt_period": receipt_period,
            "conditions": cls._conditions(text),
            "status": status,
            "application_evidence": bool(evidence),
            "published_at": published_at,
            "image_only": False,
        }

    @staticmethod
    def classify_article(title: str, text: str, tcg_key: str) -> str:
        combined = f"{title}\n{text}".casefold()
        title_lower = title.casefold()
        if any(word in combined for word in (
            "買取情報", "買取表", "高価買取", "買取価格",
            "優勝デッキ", "デッキレシピ", "対戦結果", "スタッフブログ",
        )):
            return "excluded"
        if any(word in title_lower for word in (
            "大会", "イベント", "交流会", "トーナメント",
        )) and not any(word in combined for word in (
            "抽選販売", "抽選予約", "商品予約",
        )):
            return "event"
        lottery_evidence = sum(
            word in combined
            for word in ("抽選", "応募期間", "当選発表", "対象商品")
        )
        reservation_evidence = sum(
            word in combined
            for word in ("予約受付", "予約期間", "店頭予約", "予約情報")
        )
        if lottery_evidence >= 2:
            return "resale" if any(
                word in combined for word in ("再販", "再販売")
            ) else "lottery"
        if reservation_evidence >= 2:
            return "resale" if any(
                word in combined for word in ("再販", "再販売")
            ) else "reservation"
        if tcg_key == "unknown":
            return "general_news" if any(word in combined for word in (
                "臨時休業", "営業時間", "移転", "重要なお知らせ",
            )) else "excluded"
        if any(word in combined for word in ("再販", "再販売")) and any(
            word in combined for word in ("発売日", "新品", "対象商品")
        ):
            return "resale"
        if any(word in combined for word in (
            "新品販売", "通常販売", "店頭販売", "一般販売",
        )) and any(word in combined for word in ("発売日", "税込", "新品")):
            return "regular_sale"
        if "発売日" in combined and any(
            word in combined for word in ("税込", "対象商品", "商品名")
        ):
            return "product_info"
        if any(word in combined for word in (
            "大会", "イベント", "交流会", "エントリー",
        )):
            return "event"
        if any(word in combined for word in (
            "お知らせ", "更新", "入荷",
        )):
            return "general_news"
        return "needs_review"

    @staticmethod
    def detect_tcg(value: Any) -> tuple[str, str]:
        text = unescape(str(value or "")).casefold()
        for key, variant, patterns in TCG_PATTERNS:
            if any(pattern.casefold() in text for pattern in patterns):
                return key, variant
        compact = re.sub(r"[^a-z0-9ぁ-んァ-ヶ一-龠]", "", text)
        aliases = (
            ("pokemon", "", ("ポケモン",)),
            ("onepiece", "", ("ワンピース", "onepiece")),
            ("gundam", "", ("ガンダム",)),
            ("duelmasters", "", ("デュエマ",)),
            ("weiss", "", ("ヴァイス",)),
            ("mtg", "", ("mtg", "マジックザギャザリング")),
            ("yugioh", "rush", ("遊戯王rd", "遊戯王ラッシュ")),
            ("yugioh", "ocg", ("遊戯王",)),
        )
        for key, variant, patterns in aliases:
            if any(pattern.casefold() in compact for pattern in patterns):
                return key, variant
        return "unknown", ""

    @classmethod
    def _build_hit(cls, record: dict[str, Any]) -> dict[str, Any]:
        article_type = str(record.get("article_type", ""))
        if article_type in {
            "excluded", "needs_review", "event", "general_news"
        }:
            return {}
        article_url = cls._canonical_url(record.get("article_url", ""))
        if not article_url:
            return {}
        evidence = bool(record.get("application_evidence"))
        hit = {
            "site_key": "card_labo",
            "name": (
                f"カードラボ {record.get('store_name')}"
                if record.get("store_name")
                else "カードラボ"
            ),
            "url": article_url,
            "product_url": article_url,
            "status": str(record.get("status", "")),
            "release_date": str(record.get("release_date", "")),
            "price": record.get("price"),
            "sale_price": record.get("price"),
            "price_includes_tax": True,
            "application_method": "Web / 店頭",
            "result_mode": "account_page",
            "regions": ["全国"],
            "retailer_verified": True,
            "seller": "カードラボ",
            "confidence": 0.98,
            "notice": str(record.get("title", "")),
            "tcg_key": str(record.get("tcg_key", "unknown")),
            "tcg": str(record.get("tcg", "")),
            "tcg_variant": str(record.get("tcg_variant", "")),
            "article_id": str(record.get("article_id", "")),
            "article_type": article_type,
            "target_stores": (
                [str(record.get("store_name"))]
                if record.get("store_name")
                else []
            ),
            "conditions": list(record.get("conditions", [])),
            "purchase_period": str(record.get("purchase_period", "")),
            "receipt_period": str(record.get("receipt_period", "")),
        }
        if evidence:
            hit["verification_status"] = "confirmed"
            hit["confirmed"] = True
            hit["source_type"] = "OFFICIAL_SHOP_BRANCH"
            hit["source_evidence"] = [{
                "source_type": "OFFICIAL_SHOP_BRANCH",
                "source_url": article_url,
            }]
            hit["application_url"] = str(
                record.get("application_url") or article_url
            )
            for key in (
                "application_period",
                "application_start_at",
                "application_end_at",
                "result_date",
                "result_announcement_at",
            ):
                if record.get(key):
                    hit[key] = record[key]
            hit["order_period"] = " / ".join(
                part for part in (
                    str(record.get("purchase_period", "")).strip(),
                    str(record.get("receipt_period", "")).strip(),
                )
                if part
            )
        return normalize_application_site(hit)

    @classmethod
    def _matches_candidate(
        cls,
        candidate: dict[str, Any],
        record: dict[str, Any],
    ) -> bool:
        candidate_code = cls._match_product_code(
            candidate.get("product_code", ""),
            candidate.get("name", ""),
        )
        record_code = cls._match_product_code(
            record.get("product_code", ""),
            record.get("product_name", ""),
            record.get("title", ""),
        )
        if candidate_code and record_code:
            return candidate_code == record_code
        candidate_name = cls._match_text(candidate.get("name", ""))
        product_name = cls._match_text(record.get("product_name", ""))
        if not candidate_name or not product_name:
            return False
        if candidate_name == product_name:
            return True
        candidate_signature = cls._product_name_signature(candidate_name)
        product_signature = cls._product_name_signature(product_name)
        if (
            len(candidate_signature) >= 4
            and len(product_signature) >= 4
            and (
                candidate_signature in product_signature
                or product_signature in candidate_signature
            )
        ):
            return True
        candidate_terms = {
            term for term in re.findall(r"[a-z0-9一-龠ァ-ヶ]{2,}", candidate_name)
            if term not in {"カードゲーム", "ブースターパック"}
        }
        product_terms = set(
            re.findall(r"[a-z0-9一-龠ァ-ヶ]{2,}", product_name)
        )
        shared = candidate_terms & product_terms
        return bool(shared) and len(shared) >= max(
            1,
            min(2, len(candidate_terms)),
        )

    @staticmethod
    def _match_product_code(*values: Any) -> str:
        text = " ".join(str(value or "") for value in values)
        match = re.search(
            r"\b(OP|EB|ST|PRB)\s*[-‐‑‒–—ー]?\s*(\d{2,3})\b",
            text,
            re.IGNORECASE,
        )
        return f"{match.group(1).upper()}-{match.group(2)}" if match else ""

    @staticmethod
    def _product_name_signature(value: str) -> str:
        signature = re.sub(
            r"ポケモンカードゲーム|ワンピースカードゲーム|onepieceカードゲーム|"
            r"ブースターパック|拡張パック|スタートデッキ|スターターセット|mega",
            "",
            value,
            flags=re.IGNORECASE,
        )
        signature = re.sub(r"(?:op|eb|st|prb)\d{2,3}", "", signature, flags=re.IGNORECASE)
        return signature.replace("の", "")

    @classmethod
    def _detect_store(
        cls,
        article_url: str,
        headings: list[str],
        text: str,
    ) -> dict[str, Any]:
        path = urllib.parse.urlparse(article_url).path
        slug_match = re.search(r"/shop/([^/]+)/blog/", path)
        slug = slug_match.group(1).casefold() if slug_match else ""
        slug_name = STORE_SLUGS.get(slug, "")
        heading_names: list[str] = []
        for heading in headings:
            match = re.search(
                r"([一-龠ぁ-んァ-ヶA-Za-z0-9]+(?:本店|店))"
                r"(?:の\s*)?店舗ブログ",
                heading,
            )
            if match:
                heading_names.append(match.group(1))
        body_names: list[str] = []
        for pattern in (
            r"(?:開催店舗|対象店舗)\s*[〉》】:\s]*"
            r"(?:・\s*)?(?:カードラボ\s*)?([^\n]{1,30}?店)",
            r"カードラボ\s*([^\n]{1,24}?店)(?:店頭|をご利用|にて|\s|$)",
        ):
            for match in re.finditer(pattern, text):
                value = re.sub(r"\s+", "", match.group(1))
                if value and value not in body_names:
                    body_names.append(value)
        candidates = [
            value
            for value in [slug_name, *heading_names, *body_names]
            if value
        ]
        normalized = {
            cls._normalize_store_name(value)
            for value in candidates
            if cls._normalize_store_name(value)
        }
        return {
            "name": candidates[0] if len(normalized) == 1 else "",
            "slug": slug,
            "mismatch": len(normalized) > 1,
        }

    @staticmethod
    def _normalize_store_name(value: str) -> str:
        return re.sub(
            r"[^a-z0-9ぁ-んァ-ヶ一-龠]",
            "",
            str(value).casefold().replace("カードラボ", ""),
        )

    @staticmethod
    def _product_name(title: str, text: str) -> str:
        labeled = CardLaboParser._extract_labeled(
            text,
            ("商品名",),
        )
        if labeled:
            return labeled[:160].strip(" 〈〉『』「」。")
        lines = [
            re.sub(r"\s+", " ", value).strip()
            for value in text.splitlines()
            if re.sub(r"\s+", " ", value).strip()
        ]
        for index, line in enumerate(lines):
            if not re.fullmatch(r"[〈《【]?\s*対象商品\s*[〉》】:]?", line):
                continue
            for candidate in lines[index + 1:index + 6]:
                if re.match(
                    r"^(?:発売日|販売価格|価格|お一人様|応募期間|抽選期間)"
                    r"\s*[：:]",
                    candidate,
                ):
                    continue
                if CardLaboParser.detect_tcg(candidate)[0] != "unknown":
                    return candidate[:160].strip(" 〈〉『』「」。")
        quoted = re.search(r"[『「](.{3,120}?)[』」]", title)
        if quoted:
            value = quoted.group(1).strip()
            if not any(word in value for word in ("予約情報", "お知らせ")):
                return value
        if any(word in title for word in (
            "予約受付中商品",
            "予約情報",
            "商品一覧",
            "まとめ",
        )):
            return ""
        clean = re.sub(
            r"^[〖【].*?[〗】]\s*",
            "",
            title,
        )
        clean = re.sub(
            r"(?:抽選予約販売|抽選販売|予約受付|販売)のお知らせ.*$",
            "",
            clean,
        ).strip(" 〈〉『』「」。-")
        if clean and clean != title and len(clean) >= 3:
            return clean
        return ""

    @staticmethod
    def _extract_labeled(text: str, labels: tuple[str, ...]) -> str:
        label_pattern = "|".join(re.escape(value) for value in labels)
        all_labels = (
            "応募期間", "抽選期間", "申込期間", "申し込み期間",
            "予約受付期間", "予約期間", "当選発表", "抽選発表",
            "結果発表", "当選者店頭販売期間", "当選者購入期間",
            "当選者店頭予約期間", "購入期間", "予約商品の受取期間",
            "商品お受け取り期間", "受取期間", "引取期間",
            "発売日", "商品名", "対象商品", "販売価格", "価格",
        )
        stop_pattern = "|".join(
            re.escape(value) for value in all_labels
        )
        match = re.search(
            rf"(?:{label_pattern})\s*[：:]\s*(.+?)"
            rf"(?=\s*(?:{stop_pattern})\s*[：:]|$)",
            text,
            flags=re.IGNORECASE,
        )
        return match.group(1).strip(" 。") if match else ""

    @classmethod
    def _period_datetimes(
        cls,
        value: str,
        *,
        published_at: str = "",
    ) -> tuple[str, str]:
        if not value:
            return "", ""
        matches = list(re.finditer(
            r"(?:(20\d{2})\s*年\s*)?"
            r"(\d{1,2})\s*月\s*(\d{1,2})\s*日"
            r"(?:\([^)]*\))?\s*"
            r"(?:(\d{1,2})\s*[：:]\s*(\d{2}))?",
            value,
        ))
        if not matches:
            return "", ""
        published = cls._parse_datetime(published_at)
        fallback_year = next(
            (
                int(match.group(1))
                for match in matches
                if match.group(1)
            ),
            published.astimezone(JST).year if published else datetime.now(JST).year,
        )

        def convert(match: re.Match[str], *, end: bool) -> str:
            year = int(match.group(1) or fallback_year)
            hour = int(match.group(4) or (23 if end else 0))
            minute = int(match.group(5) or (59 if end else 0))
            try:
                return datetime(
                    year,
                    int(match.group(2)),
                    int(match.group(3)),
                    hour,
                    minute,
                    tzinfo=JST,
                ).isoformat()
            except ValueError:
                return ""

        return convert(matches[0], end=False), convert(matches[-1], end=True)

    @classmethod
    def _first_datetime(
        cls,
        value: str,
        *,
        published_at: str = "",
    ) -> str:
        return cls._period_datetimes(
            value,
            published_at=published_at,
        )[0]

    @staticmethod
    def _release_date(text: str) -> str:
        for pattern in (
            r"発売日\s*[：:]\s*(20\d{2})年(\d{1,2})月(\d{1,2})日",
            r"(20\d{2})年(\d{1,2})月(\d{1,2})日(?:\([^)]*\))?\s*発売",
            r"[【〖<＜](\d{1,2})月(\d{1,2})日発売[】〗>＞]",
        ):
            match = re.search(pattern, text)
            if not match:
                continue
            values = [int(value) for value in match.groups()]
            if len(values) == 2:
                values.insert(0, datetime.now(JST).year)
            try:
                return datetime(*values).date().isoformat()
            except ValueError:
                continue
        return ""

    @staticmethod
    def _price(text: str) -> int | None:
        values = []
        for raw in re.findall(r"([\d,]+)\s*円\s*(?:（税込）|\(税込\)|税込)?", text):
            value = int(raw.replace(",", ""))
            if 100 <= value <= 1_000_000:
                values.append(value)
        return max(values) if values else None

    @classmethod
    def _application_url(cls, links: Any, text: str) -> str:
        candidates: list[str] = []
        for item in links if isinstance(links, list) else []:
            if not isinstance(item, dict):
                continue
            candidates.append(str(item.get("url", "")))
        candidates.extend(re.findall(r"https://[^\s<>'\"]+", text))
        for value in candidates:
            clean = cls._clean_external_url(value)
            parsed = urllib.parse.urlparse(clean)
            host = parsed.hostname or ""
            path = parsed.path.casefold().rstrip("/")
            if (
                host == "twitter.com" and path in {"/share", "/intent/tweet"}
            ) or (
                host == "x.com" and path in {"/share", "/intent/tweet"}
            ):
                continue
            if host in cls.EXTERNAL_APPLICATION_HOSTS:
                return clean
        return ""

    @staticmethod
    def _clean_external_url(value: Any) -> str:
        try:
            parsed = urllib.parse.urlparse(str(value or "").strip())
        except ValueError:
            return ""
        if parsed.scheme != "https" or not parsed.hostname:
            return ""
        tracking = {"_gl", "gclid", "fbclid", "yclid"}
        query = [
            (key, item)
            for key, item in urllib.parse.parse_qsl(
                parsed.query,
                keep_blank_values=True,
            )
            if key.casefold() not in tracking
            and not key.casefold().startswith("utm_")
        ]
        return urllib.parse.urlunparse((
            "https",
            parsed.netloc.casefold(),
            parsed.path or "/",
            "",
            urllib.parse.urlencode(sorted(query)),
            "",
        ))

    @staticmethod
    def _conditions(text: str) -> list[str]:
        patterns = (
            ("Xアカウント必須", ("Xアカウント未所持", "フォロー")),
            ("リポスト必須", ("リポスト",)),
            ("店舗受取限定", ("店頭でのお受取", "店頭でのみ", "店舗へ御来店")),
            ("本人確認", ("身分証明書", "本人確認")),
            ("購入数制限", ("お一人様",)),
            ("前金・内金", ("前金", "内金")),
            ("代理不可", ("代理", "ご本人様のみ")),
            ("キャンセル不可", ("キャンセル",)),
        )
        output = []
        for label, words in patterns:
            if any(word in text for word in words):
                output.append(label)
        return output

    @classmethod
    def _status(
        cls,
        article_type: str,
        start_at: str,
        end_at: str,
        now: datetime,
        evidence: bool,
    ) -> str:
        if article_type not in cls.APPLICATION_TYPES or not evidence:
            return "商品情報" if article_type == "product_info" else "日時不明"
        current = (
            now.replace(tzinfo=JST)
            if now.tzinfo is None
            else now.astimezone(JST)
        )
        start = cls._parse_datetime(start_at)
        end = cls._parse_datetime(end_at)
        if end and current > end:
            return "終了済み"
        if start and current < start:
            return "受付前"
        if start or end:
            return "受付中"
        return "日時不明"

    @classmethod
    def _deduplicate(
        cls,
        records: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str, str, str]] = set()
        for record in records:
            key = (
                str(record.get("article_id", "")),
                cls._match_text(record.get("product_name", "")),
                cls._normalize_store_name(str(record.get("store_name", ""))),
                str(record.get("application_period", "")),
                str(record.get("article_type", "")),
            )
            if key in seen:
                continue
            seen.add(key)
            output.append(record)
        return output

    def _request(self, url: str) -> FetchResult | None:
        canonical = self._canonical_url(url)
        if canonical in self._cache:
            return self._cache[canonical]
        if canonical in self._failed_urls or not self._is_allowed_url(canonical):
            if canonical:
                self._failed_urls.add(canonical)
            return None
        host = urllib.parse.urlparse(canonical).hostname or ""
        self._requested_hosts[host] += 1
        for attempt in range(self.max_retries + 1):
            self._respect_interval()
            try:
                result = self.fetcher(canonical, self.timeout_seconds)
                status, body, final_url = result
                final = self._canonical_url(final_url or canonical)
                if (
                    int(status) != 200
                    or not self._is_allowed_url(final)
                ):
                    raise ValueError(f"HTTP {status}")
                normalized = (int(status), str(body), final)
                self._cache[canonical] = normalized
                return normalized
            except (
                OSError,
                TimeoutError,
                ValueError,
                urllib.error.URLError,
            ) as error:
                if attempt >= self.max_retries:
                    self._failed_urls.add(canonical)
                    self._log(
                        f"カードラボHTTP失敗: {canonical} / {error}",
                        "ERROR",
                    )
                    return None
        return None

    def _respect_interval(self) -> None:
        wait = self.request_interval_seconds - (
            time.monotonic() - self._last_request_at
        )
        if wait > 0:
            time.sleep(wait)
        self._last_request_at = time.monotonic()

    def _default_fetch(self, url: str, timeout: float) -> FetchResult:
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": self.USER_AGENT,
                "Accept": (
                    "text/html,application/xhtml+xml,"
                    "application/rss+xml,application/xml;q=0.9,"
                    "text/plain;q=0.8,*/*;q=0.5"
                ),
                "Accept-Language": "ja-JP,ja;q=0.9,en;q=0.5",
            },
            method="GET",
        )
        opener = build_https_opener(_CardLaboRedirectHandler())
        with opener.open(request, timeout=timeout) as response:
            body = response.read(2_000_000)
            charset = response.headers.get_content_charset() or "utf-8"
            return (
                int(getattr(response, "status", 200)),
                body.decode(charset, errors="replace"),
                response.geturl(),
            )

    @classmethod
    def _is_allowed_url(cls, value: Any) -> bool:
        try:
            parsed = urllib.parse.urlparse(str(value or ""))
        except ValueError:
            return False
        return (
            parsed.scheme == "https"
            and (parsed.hostname or "").casefold() == cls.ALLOWED_HOST
            and parsed.port in {None, 443}
            and not parsed.username
            and not parsed.password
        )

    @classmethod
    def _is_article_url(cls, value: Any) -> bool:
        if not cls._is_allowed_url(value):
            return False
        path = urllib.parse.urlparse(str(value)).path
        return bool(re.search(
            r"(?:/shop/[^/]+)?/blog/\d+/?$",
            path,
        ))

    @staticmethod
    def _canonical_url(value: Any) -> str:
        try:
            parsed = urllib.parse.urlparse(str(value or "").strip())
        except ValueError:
            return ""
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return ""
        return urllib.parse.urlunparse((
            parsed.scheme.casefold(),
            parsed.netloc.casefold(),
            parsed.path or "/",
            "",
            urllib.parse.urlencode(sorted(
                urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
            )),
            "",
        ))

    @staticmethod
    def _article_id(value: Any) -> str:
        try:
            path = urllib.parse.urlparse(str(value or "")).path
        except ValueError:
            return ""
        match = re.search(r"/blog/(\d+)/?$", path)
        return match.group(1) if match else ""

    @staticmethod
    def _match_text(value: Any) -> str:
        return re.sub(
            r"[^a-z0-9ぁ-んァ-ヶ一-龠]",
            "",
            unescape(str(value or "")).casefold(),
        )

    @staticmethod
    def _tcg_display(key: str, variant: str) -> str:
        if key == "yugioh":
            return (
                "遊戯王ラッシュデュエル"
                if variant == "rush"
                else "遊戯王OCG"
            )
        return display_name(key)

    @staticmethod
    def _excluded(url: str, reason: str) -> dict[str, Any]:
        return {
            "article_type": "excluded",
            "article_url": url,
            "exclusion_reason": reason,
        }

    def _load_state(self) -> dict[str, Any]:
        try:
            if not self.state_path.exists():
                return {}
            loaded = json.loads(self.state_path.read_text(encoding="utf-8"))
            return loaded if isinstance(loaded, dict) else {}
        except (OSError, ValueError, TypeError):
            return {}

    def _save_state(self, state: dict[str, Any]) -> None:
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.state_path.with_suffix(".tmp")
            temporary.write_text(
                json.dumps(state, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temporary.replace(self.state_path)
        except OSError as error:
            self._log(f"カードラボ状態保存失敗: {error}", "ERROR")

    @staticmethod
    def _parse_datetime(value: Any) -> datetime | None:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            try:
                from email.utils import parsedate_to_datetime
                parsed = parsedate_to_datetime(text)
            except (TypeError, ValueError):
                return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=JST)
        return parsed

    def _today_jst(self) -> str:
        now = self.now_provider()
        if now.tzinfo is None:
            now = now.replace(tzinfo=JST)
        return now.astimezone(JST).date().isoformat()

    def _now_iso(self) -> str:
        now = self.now_provider()
        if now.tzinfo is None:
            now = now.replace(tzinfo=JST)
        return now.astimezone(JST).isoformat()

    def _log_summary(self, diagnostics: dict[str, Any]) -> None:
        fields = (
            ("実解析URL数", "parsed_url_count"),
            ("商品保存件数", "product_record_count"),
            ("応募案件保存件数", "application_record_count"),
            ("終了済み件数", "ended_count"),
            ("要確認件数", "needs_review_count"),
            ("画像のみ除外件数", "image_only_excluded_count"),
            ("HTTP失敗件数", "http_failure_count"),
            ("外部ホストアクセス件数", "external_host_request_count"),
        )
        for label, key in fields:
            self._log(f"カードラボ{label}: {diagnostics.get(key, 0)}件")
        for label, key in (
            ("記事分類別件数", "article_type_counts"),
            ("TCG別件数", "tcg_counts"),
            ("店舗別件数", "store_counts"),
            ("除外理由", "excluded_reasons"),
            ("アクセスホスト", "requested_hosts"),
        ):
            self._log(
                f"カードラボ{label}: "
                + json.dumps(
                    diagnostics.get(key, {}),
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
        self._log(
            "カードラボ所要時間: "
            f"{diagnostics.get('elapsed_seconds', 0):.3f}秒"
        )

    def _log(self, message: str, level: str = "INFO") -> None:
        try:
            self.log_manager.write(message, level)
        except OSError:
            pass
