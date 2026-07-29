from __future__ import annotations

import hashlib
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


TCG_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "yugioh",
        (
            "遊戯王ラッシュデュエル",
            "遊戯王rush duel",
            "rush duel",
        ),
    ),
    ("pokemon", ("ポケモンカードゲーム", "ポケモンカード", "ポケカ")),
    (
        "onepiece",
        (
            "one pieceカードゲーム",
            "one piece card game",
            "ワンピースカードゲーム",
        ),
    ),
    (
        "gundam",
        (
            "ガンダムカードゲーム",
            "gundam card game",
        ),
    ),
    (
        "yugioh",
        (
            "遊戯王ocg",
            "遊戯王オフィシャルカードゲーム",
            "遊戯王",
            "yu-gi-oh",
        ),
    ),
    (
        "duelmasters",
        (
            "デュエル・マスターズ",
            "デュエルマスターズ",
            "デュエマ",
        ),
    ),
    (
        "weiss",
        (
            "ヴァイスシュヴァルツ",
            "weiss schwarz",
        ),
    ),
    (
        "mtg",
        (
            "magic: the gathering",
            "magic：the gathering",
            "マジック：ザ・ギャザリング",
            "マジック:ザ・ギャザリング",
        ),
    ),
)


class _HobbyStationArticleParser(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.title = ""
        self.og_title = ""
        self.image_url = ""
        self.published_at = ""
        self.text_parts: list[str] = []
        self.links: list[dict[str, str]] = []
        self._heading_depth = 0
        self._heading_parts: list[str] = []
        self._link_url = ""
        self._link_parts: list[str] = []
        self._in_title = False
        self._title_parts: list[str] = []
        self._ignored_depth = 0
        self._article_section_depth = 0
        self._main_column_depth = 0

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        values = {key.casefold(): value or "" for key, value in attrs}
        lowered = tag.casefold()

        if lowered in {"script", "style", "noscript"}:
            self._ignored_depth += 1
            return
        if self._ignored_depth:
            return

        if (
            lowered == "section"
            and values.get("id", "").casefold() == "article"
        ):
            self._article_section_depth = 1
        elif lowered == "section" and self._article_section_depth:
            self._article_section_depth += 1

        if lowered == "title":
            self._in_title = True
            self._title_parts = []

        if lowered == "meta":
            key = (
                values.get("property")
                or values.get("name")
                or ""
            ).casefold()
            content = values.get("content", "").strip()
            if key == "og:title":
                self.og_title = unescape(content)
            elif key in {"og:image", "og:image:secure_url"} and not self.image_url:
                self.image_url = urllib.parse.urljoin(self.base_url, content)
            elif key in {"article:published_time", "date", "datepublished"}:
                self.published_at = content

        classes = set(values.get("class", "").split())
        if (
            lowered == "div"
            and self._article_section_depth
            and not self._main_column_depth
            and "col-md-9" in classes
        ):
            self._main_column_depth = 1
        elif lowered == "div" and self._main_column_depth:
            self._main_column_depth += 1

        if not self._main_column_depth:
            return

        if lowered in {"h1", "h2", "h3"} and not self._heading_depth:
            self._heading_depth = 1
            self._heading_parts = []
        elif self._heading_depth and lowered in {"span", "strong", "em"}:
            self._heading_depth += 1

        if lowered == "a":
            self._link_url = urllib.parse.urljoin(
                self.base_url,
                values.get("href", "").strip(),
            )
            self._link_parts = []

        if lowered == "img" and not self.image_url:
            source = (
                values.get("data-src")
                or values.get("src")
                or values.get("data-original")
                or ""
            ).strip()
            if source:
                self.image_url = urllib.parse.urljoin(self.base_url, source)

        if lowered in {"p", "div", "li", "br", "section", "h1", "h2", "h3"}:
            self.text_parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._ignored_depth:
            return
        clean = unescape(data).strip()
        if not clean:
            return
        if self._in_title:
            self._title_parts.append(clean)
        if not self._main_column_depth:
            return
        if self._heading_depth:
            self._heading_parts.append(clean)
        if self._link_url:
            self._link_parts.append(clean)
        self.text_parts.append(clean)

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.casefold()
        if lowered in {"script", "style", "noscript"} and self._ignored_depth:
            self._ignored_depth -= 1
            return
        if self._ignored_depth:
            return

        if lowered == "title" and self._in_title:
            self._in_title = False
            self.title = " ".join(self._title_parts).strip()

        if not self._article_section_depth:
            return

        if not self._main_column_depth:
            if lowered == "section":
                self._article_section_depth -= 1
            return

        if self._heading_depth:
            if lowered in {"span", "strong", "em"} and self._heading_depth > 1:
                self._heading_depth -= 1
            elif lowered in {"h1", "h2", "h3"}:
                self._heading_depth = 0
                heading = " ".join(self._heading_parts).strip()
                if heading and not self.og_title:
                    self.og_title = heading

        if lowered == "a" and self._link_url:
            self.links.append({
                "url": self._link_url,
                "text": " ".join(self._link_parts).strip(),
            })
            self._link_url = ""
            self._link_parts = []

        if lowered in {"p", "div", "li", "section", "h1", "h2", "h3"}:
            self.text_parts.append("\n")
        if lowered == "div":
            self._main_column_depth -= 1
        if lowered == "section":
            self._article_section_depth -= 1

    def result(self) -> dict[str, Any]:
        text = "\n".join(
            line.strip()
            for line in re.split(r"[\r\n]+", " ".join(self.text_parts))
            if line.strip()
        )
        title = self.og_title or self.title
        title = re.sub(r"\s*[-–|]\s*ホビーステーション\s*$", "", title).strip()
        return {
            "title": title,
            "text": text,
            "links": self.links,
            "image_url": self.image_url,
            "published_at": self.published_at,
        }


class HobbyStationParser:
    BASE_URL = "https://www.hbst.net/"
    RSS_URL = "https://www.hbst.net/sitemap.rss"
    ALLOWED_HOST = "www.hbst.net"
    LIVEPOCKET_HOSTS = {"livepocket.jp", "t.livepocket.jp"}
    USER_AGENT = (
        "PokeyoyaKun/1.25.0 "
        "(Windows; +https://pokeyoyakun.com)"
    )

    def __init__(
        self,
        *,
        fetcher: FetchCallable | None = None,
        log_manager: LogManager | None = None,
        state_path: Path | None = None,
        timeout_seconds: float = 15.0,
        max_retries: int = 1,
        request_interval_seconds: float = 0.5,
        max_article_requests: int = 50,
        now_provider: Callable[[], datetime] | None = None,
    ):
        self.fetcher = fetcher or self._default_fetch
        self.log_manager = log_manager or LogManager()
        self.state_path = (
            Path(state_path)
            if state_path is not None
            else app_root() / "config" / "hobby_station_state.json"
        )
        self.timeout_seconds = max(1.0, float(timeout_seconds))
        self.max_retries = max(0, min(int(max_retries), 1))
        self.request_interval_seconds = max(
            0.0,
            float(request_interval_seconds),
        )
        self.max_article_requests = max(
            1,
            min(int(max_article_requests), 50),
        )
        self.now_provider = now_provider or (
            lambda: datetime.now(timezone.utc)
        )
        self._cache: dict[str, FetchResult] = {}
        self._failed_urls: set[str] = set()
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
        matched = [
            record
            for record in self._records
            if record.get("tcg_key") == candidate_tcg
            and self._matches_candidate(candidate, record)
            and record.get("article_type") in {
                "product_schedule",
                "application",
            }
        ]
        hits = [self._build_hit(record) for record in matched]
        hits = [hit for hit in hits if hit]

        product_count = sum(
            1 for record in matched
            if record.get("article_type") == "product_schedule"
        )
        application_count = sum(
            1 for record in matched
            if record.get("article_type") == "application"
        )
        self.last_diagnostics["product_saved_count"] = product_count
        self.last_diagnostics["application_saved_count"] = application_count
        self._log(f"ホビーステーション商品保存件数: {product_count}件")
        self._log(
            f"ホビーステーション応募案件保存件数: {application_count}件"
        )
        return (
            hits,
            "ホビーステーション: "
            f"商品{product_count}件 / 応募{application_count}件",
        )

    def scan(self, *, force: bool = False) -> list[dict[str, Any]]:
        if self._scanned and not force:
            return [dict(record) for record in self._records]

        started = time.monotonic()
        diagnostics: dict[str, Any] = {
            "rss_detected_count": 0,
            "new_url_count": 0,
            "parsed_url_count": 0,
            "article_type_counts": {},
            "tcg_counts": {},
            "product_record_count": 0,
            "application_record_count": 0,
            "excluded_count": 0,
            "excluded_reasons": {},
            "http_failure_count": 0,
            "elapsed_seconds": 0.0,
            "livepocket_request_count": 0,
        }
        exclusion_reasons: Counter[str] = Counter()

        rss_response = self._request(self.RSS_URL)
        if rss_response is None:
            diagnostics["http_failure_count"] = len(self._failed_urls)
            diagnostics["excluded_count"] = 1
            diagnostics["excluded_reasons"] = {"RSS取得失敗": 1}
            diagnostics["elapsed_seconds"] = round(
                time.monotonic() - started,
                3,
            )
            self.last_diagnostics = diagnostics
            self._log("ホビーステーションRSS取得結果: 失敗", "ERROR")
            self._scanned = True
            return []

        _, xml_text, _ = rss_response
        entries = self.parse_rss(xml_text)
        diagnostics["rss_detected_count"] = len(entries)
        self._log(
            f"ホビーステーションRSS取得結果: 200 / {len(entries)}URL"
        )

        state = self._load_state()
        previous_checked = self._parse_datetime(
            str(state.get("last_checked_at", ""))
        )
        checked_urls = {
            str(url): str(value)
            for url, value in state.get("checked_urls", {}).items()
            if isinstance(url, str)
        }
        new_entries = []
        for entry in entries[:50]:
            url = self._canonical_url(entry.get("url", ""))
            if not self._is_article_url(url):
                exclusion_reasons["記事URLではない"] += 1
                continue
            modified = self._parse_datetime(str(entry.get("modified_at", "")))
            if url not in checked_urls:
                new_entries.append({**entry, "url": url})
                continue
            if (
                previous_checked is not None
                and modified is not None
                and modified > previous_checked
            ):
                new_entries.append({**entry, "url": url})

        diagnostics["new_url_count"] = len(new_entries)
        self._log(
            f"ホビーステーション新規URL件数: {len(new_entries)}件"
        )

        records: list[dict[str, Any]] = []
        successfully_checked: dict[str, str] = {}
        for entry in new_entries[: self.max_article_requests]:
            url = str(entry.get("url", ""))
            response = self._request(url)
            if response is None:
                exclusion_reasons["記事HTTP取得失敗"] += 1
                continue
            _, html, final_url = response
            record = self.parse_article_html(
                html,
                final_url,
                modified_at=str(entry.get("modified_at", "")),
                now=self.now_provider(),
            )
            diagnostics["parsed_url_count"] += 1
            successfully_checked[url] = str(
                entry.get("modified_at", "")
            ) or self._now_iso()
            if record.get("article_type") == "excluded":
                exclusion_reasons[
                    str(record.get("exclusion_reason", "対象外"))
                ] += 1
                continue
            records.append(record)

        checked_urls.update(successfully_checked)
        if successfully_checked or not state:
            self._save_state({
                "last_checked_at": self._now_iso(),
                "checked_urls": checked_urls,
            })

        type_counts = Counter(
            str(record.get("article_type", "unknown"))
            for record in records
        )
        tcg_counts = Counter(
            str(record.get("tcg_key", "unknown"))
            for record in records
        )
        diagnostics.update({
            "article_type_counts": dict(type_counts),
            "tcg_counts": dict(tcg_counts),
            "product_record_count": type_counts["product_schedule"],
            "application_record_count": type_counts["application"],
            "excluded_count": sum(exclusion_reasons.values()),
            "excluded_reasons": dict(exclusion_reasons),
            "http_failure_count": len(self._failed_urls),
            "elapsed_seconds": round(time.monotonic() - started, 3),
        })
        self.last_diagnostics = diagnostics
        self._records = records
        self._scanned = True
        self._log_scan_summary(diagnostics)
        return [dict(record) for record in records]

    @classmethod
    def parse_rss(cls, xml_text: str) -> list[dict[str, str]]:
        if not str(xml_text).strip():
            return []
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return []

        entries: list[dict[str, str]] = []
        seen: set[str] = set()

        def local_name(tag: str) -> str:
            return tag.rsplit("}", 1)[-1].casefold()

        for parent in root.iter():
            if local_name(parent.tag) not in {"url", "item"}:
                continue
            values: dict[str, str] = {}
            for child in list(parent):
                name = local_name(child.tag)
                if name in {"loc", "link", "lastmod", "pubdate", "title"}:
                    values[name] = (child.text or "").strip()
            url = values.get("loc") or values.get("link") or ""
            canonical = cls._canonical_url(url)
            if not canonical or canonical in seen:
                continue
            seen.add(canonical)
            entries.append({
                "url": canonical,
                "modified_at": (
                    values.get("lastmod")
                    or values.get("pubdate")
                    or ""
                ),
                "title": values.get("title", ""),
            })
        return entries[:50]

    @classmethod
    def parse_article_html(
        cls,
        html: str,
        article_url: str,
        *,
        modified_at: str = "",
        now: datetime | None = None,
    ) -> dict[str, Any]:
        parser = _HobbyStationArticleParser(article_url)
        try:
            parser.feed(str(html))
        except (ValueError, TypeError):
            return {
                "article_type": "excluded",
                "exclusion_reason": "HTML解析失敗",
                "article_url": article_url,
            }
        parsed = parser.result()
        title = str(parsed.get("title", "")).strip()
        text = str(parsed.get("text", "")).strip()
        combined = f"{title}\n{text}".strip()
        if not title or not text:
            return {
                "article_type": "excluded",
                "exclusion_reason": "タイトルまたは本文欠損",
                "article_url": article_url,
            }

        tcg_key = cls.detect_tcg(title)
        if tcg_key == "unknown":
            tcg_key = cls.detect_tcg(text)
        article_type = cls.classify_article(title, text, tcg_key)
        if article_type == "excluded":
            return {
                "article_type": "excluded",
                "exclusion_reason": "対象TCGまたは記事種別不明",
                "article_url": article_url,
            }

        application_period = cls._extract_labeled(
            text,
            ("応募期間", "申込期間", "申し込み期間", "予約期間"),
        )
        result_date = cls._extract_labeled(
            text,
            ("当選発表", "抽選発表", "結果発表"),
        )
        purchase_period = cls._extract_labeled(
            text,
            (
                "当選者購入期間",
                "商品代金お支払い期間",
                "購入期間",
                "支払期間",
            ),
        )
        receipt_period = cls._extract_labeled(
            text,
            ("商品お受け取り期間", "商品お渡し期間", "受取期間"),
        )
        application_start, application_end = cls._period_datetimes(
            application_period
        )
        result_at = cls._first_datetime(result_date)
        application_url = cls._application_url(
            parsed.get("links", []),
            text,
        )
        if article_type == "application":
            status = cls._application_status(
                title,
                text,
                application_start,
                application_end,
                now or datetime.now(JST),
            )
        elif article_type == "product_schedule":
            status = "商品掲載あり"
        elif article_type == "event":
            status = "イベント情報"
        else:
            status = "一般ニュース"
        release_date = cls._release_date(combined)
        price = cls._price(combined)
        product_name = cls._product_name(title, article_type)
        article_id = cls._article_id(article_url)

        record = {
            "article_id": article_id,
            "article_type": article_type,
            "article_url": cls._canonical_url(article_url),
            "title": title,
            "product_name": product_name,
            "tcg_key": tcg_key,
            "tcg": display_name(tcg_key),
            "release_date": release_date,
            "price": price,
            "image_url": cls._safe_image_url(parsed.get("image_url", "")),
            "description": cls._description(text),
            "application_url": application_url,
            "application_period": application_period,
            "application_start_at": application_start,
            "application_end_at": application_end,
            "result_date": result_date,
            "result_announcement_at": result_at,
            "purchase_period": purchase_period,
            "receipt_period": receipt_period,
            "target_stores": cls._target_stores(text),
            "conditions": cls._conditions(text),
            "status": status,
            "published_at": (
                str(parsed.get("published_at", ""))
                or modified_at
            ),
            "modified_at": modified_at,
        }
        return record

    @staticmethod
    def classify_article(
        title: str,
        text: str,
        tcg_key: str,
    ) -> str:
        combined = f"{title}\n{text}".casefold()
        lowered_title = title.casefold()
        if tcg_key == "unknown":
            return "general_news" if any(
                term in combined
                for term in ("お知らせ", "休業", "営業時間", "店舗")
            ) else "excluded"
        if (
            any(term in lowered_title for term in (
                "大会", "イベント", "grand prix", "グランプリ",
            ))
            and not any(term in lowered_title for term in (
                "抽選販売", "予約販売", "商品予約",
            ))
        ):
            return "event"
        if any(term in combined for term in (
            "抽選販売", "応募期間", "抽選受付", "予約受付",
            "予約販売", "お申し込み期間", "申込期間",
        )):
            return "application"
        if any(term in combined for term in (
            "大会", "イベント", "参加者募集", "エントリー",
        )):
            return "event"
        if (
            "発売" in combined
            and any(term in combined for term in ("円", "商品仕様", "パック"))
        ):
            return "product_schedule"
        if any(term in combined for term in ("お知らせ", "更新", "変更")):
            return "general_news"
        return "excluded"

    @staticmethod
    def detect_tcg(text: str) -> str:
        lowered = unescape(str(text)).casefold()
        for key, patterns in TCG_PATTERNS:
            if any(pattern.casefold() in lowered for pattern in patterns):
                return key
        return "unknown"

    @classmethod
    def _build_hit(cls, record: dict[str, Any]) -> dict[str, Any]:
        article_type = str(record.get("article_type", ""))
        if article_type not in {"product_schedule", "application"}:
            return {}
        article_url = cls._canonical_url(record.get("article_url", ""))
        if not article_url:
            return {}
        price = record.get("price")
        status = str(record.get("status", "")).strip()
        if article_type == "product_schedule":
            status = "商品掲載あり"

        hit = {
            "site_key": "hobby_station",
            "name": "ホビーステーション",
            "url": article_url,
            "product_url": article_url,
            "status": status,
            "release_date": str(record.get("release_date", "")),
            "price": price,
            "sale_price": price,
            "price_includes_tax": True,
            "image_url": str(record.get("image_url", "")),
            "description": str(record.get("description", "")),
            "application_method": "Web / 店頭",
            "result_mode": "account_page",
            "regions": ["全国"],
            "retailer_verified": True,
            "seller": "ホビーステーション",
            "confidence": 0.98,
            "notice": str(record.get("title", "")),
            "tcg_key": str(record.get("tcg_key", "unknown")),
            "tcg": str(record.get("tcg", "")),
            "article_id": str(record.get("article_id", "")),
            "article_type": article_type,
            "target_stores": list(record.get("target_stores", [])),
            "conditions": list(record.get("conditions", [])),
            "purchase_period": str(record.get("purchase_period", "")),
            "receipt_period": str(record.get("receipt_period", "")),
        }
        if article_type == "application":
            for key in (
                "application_url",
                "application_period",
                "application_start_at",
                "application_end_at",
                "result_date",
                "result_announcement_at",
            ):
                if record.get(key):
                    hit[key] = record[key]
            order_parts = [
                str(record.get("purchase_period", "")).strip(),
                str(record.get("receipt_period", "")).strip(),
            ]
            hit["order_period"] = " / ".join(
                part for part in order_parts if part
            )
        return normalize_application_site(hit)

    @classmethod
    def _matches_candidate(
        cls,
        candidate: dict[str, Any],
        record: dict[str, Any],
    ) -> bool:
        candidate_code = cls._match_text(candidate.get("product_code", ""))
        article_text = cls._match_text(
            f"{record.get('product_name', '')} {record.get('title', '')}"
        )
        if candidate_code and candidate_code in article_text:
            return True
        candidate_name = cls._match_text(candidate.get("name", ""))
        product_name = cls._match_text(record.get("product_name", ""))
        if not candidate_name or not product_name:
            return False
        return (
            candidate_name in product_name
            or product_name in candidate_name
        )

    @staticmethod
    def _match_text(value: Any) -> str:
        text = unescape(str(value or "")).casefold()
        for _, patterns in TCG_PATTERNS:
            for pattern in patterns:
                text = text.replace(pattern.casefold(), "")
        text = re.sub(
            r"(?:抽選販売|予約販売|応募終了|受付終了|発売予定|発売|再販|"
            r"ブースターパック|スタートデッキ|トライアルデッキ|"
            r"拡張パック|box|ボックス)",
            "",
            text,
        )
        return re.sub(
            r"[\s「」『』【】\[\]（）()・･、。!！?？:：/／_\-&＆]",
            "",
            text,
        )

    @staticmethod
    def _product_name(title: str, article_type: str) -> str:
        clean = re.sub(r"^〖[^〗]+〗", "", title).strip()
        clean = re.sub(r"^【[^】]*\d{4}[./年][^】]*】", "", clean).strip()
        clean = re.sub(
            r"^(?:※[^「『]+)?(?:抽選販売|予約販売|予約受付|販売)"
            r"(?:のお知らせ)?\s*[「『]?",
            "",
            clean,
        )
        clean = clean.rstrip("」』 ")
        if article_type == "product_schedule":
            clean = re.sub(
                r"\s*\d{4}年\d{1,2}月\d{1,2}日.*?発売(?:予定)?\s*$",
                "",
                clean,
            )
        return clean or title

    @staticmethod
    def _extract_labeled(
        text: str,
        labels: tuple[str, ...],
    ) -> str:
        label_pattern = "|".join(re.escape(label) for label in labels)
        stop = (
            r"(?=\s*(?:■|・)?(?:応募方法|応募期間|申込期間|"
            r"当選発表|抽選発表|結果発表|当選者購入期間|"
            r"商品代金お支払い期間|購入期間|商品お受け取り期間|"
            r"商品お渡し期間|受取期間|注意事項|当選者は|"
            r"お申し込みには|※)|$)"
        )
        match = re.search(
            rf"(?:■|・)?(?:{label_pattern})\s*[：:]\s*(.+?){stop}",
            re.sub(r"\s+", " ", text),
            flags=re.IGNORECASE,
        )
        return match.group(1).strip(" 。") if match else ""

    @classmethod
    def _period_datetimes(cls, value: str) -> tuple[str, str]:
        if not value:
            return "", ""
        matches = list(re.finditer(
            r"(?:(\d{4})\s*年\s*)?"
            r"(\d{1,2})\s*月\s*(\d{1,2})\s*日"
            r"(?:\([^)]*\))?\s*"
            r"(?:(\d{1,2})\s*[：:]\s*(\d{2}))?",
            value,
        ))
        if not matches:
            return "", ""
        fallback_year = next(
            (
                int(match.group(1))
                for match in matches
                if match.group(1)
            ),
            datetime.now().year,
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
    def _first_datetime(cls, value: str) -> str:
        start, _ = cls._period_datetimes(value)
        return start

    @staticmethod
    def _release_date(text: str) -> str:
        patterns = (
            r"発売予定日\s*[：:]\s*(\d{4})年(\d{1,2})月(\d{1,2})日",
            r"(\d{4})年(\d{1,2})月(\d{1,2})日(?:\([^)]*\))?\s*発売",
        )
        for pattern in patterns:
            match = re.search(pattern, text)
            if not match:
                continue
            try:
                return datetime(
                    *(int(value) for value in match.groups()),
                ).date().isoformat()
            except ValueError:
                continue
        return ""

    @staticmethod
    def _price(text: str) -> int | None:
        matches = re.findall(r"([\d,]+)\s*円\s*(?:（税込）|\(税込\))?", text)
        amounts = []
        for value in matches:
            amount = int(value.replace(",", ""))
            if 100 <= amount <= 1_000_000:
                amounts.append(amount)
        # パック単価とBOX価格が併記されるため、商品単位の代表価格を優先する。
        return max(amounts) if amounts else None

    @classmethod
    def _application_url(
        cls,
        links: Any,
        text: str,
    ) -> str:
        for item in links if isinstance(links, list) else []:
            url = cls._canonical_url(
                item.get("url", "") if isinstance(item, dict) else ""
            )
            try:
                host = (
                    urllib.parse.urlparse(url).hostname or ""
                ).casefold()
            except ValueError:
                continue
            if host in cls.LIVEPOCKET_HOSTS:
                return cls._clean_external_url(url)
        match = re.search(
            r"https://(?:t\.)?livepocket\.jp/e/[A-Za-z0-9_-]+",
            text,
        )
        return cls._clean_external_url(match.group(0)) if match else ""

    @staticmethod
    def _clean_external_url(url: str) -> str:
        parsed = urllib.parse.urlparse(str(url or "").strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return ""
        tracking_keys = {"_gl", "gclid", "fbclid", "yclid"}
        query = [
            (key, value)
            for key, value in urllib.parse.parse_qsl(
                parsed.query,
                keep_blank_values=True,
            )
            if key.casefold() not in tracking_keys
            and not key.casefold().startswith("utm_")
        ]
        return urllib.parse.urlunparse(
            (
                parsed.scheme.casefold(),
                parsed.netloc.casefold(),
                parsed.path or "/",
                "",
                urllib.parse.urlencode(sorted(query)),
                "",
            )
        )

    @staticmethod
    def _application_status(
        title: str,
        text: str,
        start_at: str,
        end_at: str,
        now: datetime,
    ) -> str:
        combined = f"{title}\n{text}"
        if re.search(r"(?:応募|受付|抽選)(?:は|が)?終了|募集終了", combined):
            return "終了済み"
        normalized_now = (
            now.replace(tzinfo=JST)
            if now.tzinfo is None
            else now.astimezone(JST)
        )
        start = HobbyStationParser._parse_datetime(start_at)
        end = HobbyStationParser._parse_datetime(end_at)
        if end is not None and normalized_now > end:
            return "終了済み"
        if start is not None and normalized_now < start:
            return "受付予定"
        if "予約" in combined:
            return "予約受付中"
        return "抽選受付中"

    @staticmethod
    def _target_stores(text: str) -> list[str]:
        output: list[str] = []
        for sentence in re.split(r"[\n。]", text):
            clean = re.sub(r"\s+", " ", sentence).strip()
            if "店" not in clean:
                continue
            if not any(
                word in clean
                for word in ("限定", "対象店舗", "購入店舗", "応募店舗", "にて")
            ):
                continue
            if len(clean) > 180:
                clean = clean[:180].rstrip() + "…"
            if clean and clean not in output:
                output.append(clean)
        return output[:8]

    @staticmethod
    def _conditions(text: str) -> list[str]:
        keywords = (
            "会員登録", "本人確認", "公的な本人確認書類",
            "店頭のみ", "複数店舗", "複数回", "現金のみ",
            "キャンセル", "受け取り", "購入期間",
        )
        output: list[str] = []
        for sentence in re.split(r"[\n。]", text):
            clean = re.sub(r"\s+", " ", sentence).strip(" ・※")
            if not clean or not any(word in clean for word in keywords):
                continue
            if len(clean) > 220:
                clean = clean[:220].rstrip() + "…"
            if clean not in output:
                output.append(clean)
        return output[:12]

    @staticmethod
    def _description(text: str) -> str:
        clean = re.sub(r"\s+", " ", text).strip()
        return clean[:1200]

    @staticmethod
    def _article_id(url: str) -> str:
        parsed = urllib.parse.urlparse(url)
        query = dict(urllib.parse.parse_qsl(parsed.query))
        if query.get("p", "").isdigit():
            return query["p"]
        path = parsed.path.strip("/")
        if path:
            return path.replace("/", ":")
        return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]

    def _request(self, url: str) -> FetchResult | None:
        canonical = self._canonical_url(url)
        if not self._is_allowed_url(canonical):
            self._log(
                f"ホビーステーションHTTP結果: URL拒否 {url}",
                "WARNING",
            )
            return None
        if canonical in self._cache:
            self._log(
                f"ホビーステーションHTTP結果: cache {canonical}"
            )
            return self._cache[canonical]
        if canonical in self._failed_urls:
            return None

        last_error = ""
        for attempt in range(self.max_retries + 1):
            self._respect_interval()
            try:
                status, body, final_url = self.fetcher(
                    canonical,
                    self.timeout_seconds,
                )
                if not self._is_allowed_url(final_url):
                    raise ValueError("許可されていないリダイレクト先")
                self._log(
                    "ホビーステーションHTTP結果: "
                    f"{status} {canonical} attempt={attempt + 1}"
                )
                if status == 200:
                    result = (status, body, final_url)
                    self._cache[canonical] = result
                    return result
                last_error = f"HTTP {status}"
                if status < 500:
                    break
            except (TimeoutError, urllib.error.URLError) as error:
                last_error = f"{type(error).__name__}: {error}"
                self._log(
                    "ホビーステーションHTTP結果: "
                    f"失敗 {canonical} attempt={attempt + 1} {last_error}",
                    "WARNING",
                )
            except Exception as error:
                last_error = f"{type(error).__name__}: {error}"
                self._log(
                    f"ホビーステーションHTTP結果: 失敗 "
                    f"{canonical} {last_error}",
                    "WARNING",
                )
                break
        self._failed_urls.add(canonical)
        self._log(
            f"ホビーステーションHTTP取得失敗: "
            f"{canonical} / {last_error}",
            "ERROR",
        )
        return None

    def _respect_interval(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        remaining = self.request_interval_seconds - elapsed
        if self._last_request_at and remaining > 0:
            time.sleep(remaining)
        self._last_request_at = time.monotonic()

    def _default_fetch(self, url: str, timeout: float) -> FetchResult:
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": self.USER_AGENT,
                "Accept": (
                    "text/html,application/xhtml+xml,"
                    "application/xml;q=0.9,text/plain;q=0.8,*/*;q=0.7"
                ),
                "Accept-Language": "ja,en-US;q=0.8,en;q=0.6",
            },
        )
        try:
            with build_https_opener().open(
                request,
                timeout=timeout,
            ) as response:
                raw = response.read(3_000_000)
                charset = (
                    response.headers.get_content_charset()
                    or "utf-8"
                )
                return (
                    int(response.status),
                    raw.decode(charset, errors="replace"),
                    response.geturl(),
                )
        except urllib.error.HTTPError as error:
            return (
                int(error.code),
                "",
                error.geturl() or url,
            )

    @classmethod
    def _is_allowed_url(cls, url: str) -> bool:
        try:
            parsed = urllib.parse.urlparse(url)
            return (
                parsed.scheme == "https"
                and (parsed.hostname or "").casefold() == cls.ALLOWED_HOST
                and parsed.port in (None, 443)
            )
        except ValueError:
            return False

    @classmethod
    def _is_article_url(cls, url: str) -> bool:
        if not cls._is_allowed_url(url):
            return False
        parsed = urllib.parse.urlparse(url)
        query = dict(urllib.parse.parse_qsl(parsed.query))
        if query.get("p", "").isdigit():
            return True
        ignored = {
            "", "result", "shop", "privacy", "company", "contact",
            "enjoy", "selling", "recruit", "category", "tag", "author",
        }
        first = parsed.path.strip("/").split("/", 1)[0].casefold()
        return bool(first and first not in ignored)

    @staticmethod
    def _canonical_url(value: Any) -> str:
        clean = str(value or "").strip()
        if not clean:
            return ""
        parsed = urllib.parse.urlparse(clean)
        query = urllib.parse.urlencode(sorted(
            urllib.parse.parse_qsl(
                parsed.query,
                keep_blank_values=True,
            )
        ))
        return parsed._replace(
            query=query,
            fragment="",
        ).geturl()

    @classmethod
    def _safe_image_url(cls, value: Any) -> str:
        url = cls._canonical_url(value)
        try:
            parsed = urllib.parse.urlparse(url)
            if (
                parsed.scheme == "https"
                and (
                    parsed.hostname or ""
                ).casefold() == cls.ALLOWED_HOST
            ):
                return url
        except ValueError:
            pass
        return ""

    def _load_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {}
        try:
            data = json.loads(
                self.state_path.read_text(encoding="utf-8")
            )
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_state(self, state: dict[str, Any]) -> None:
        try:
            self.state_path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )
            temporary = self.state_path.with_suffix(".json.tmp")
            temporary.write_text(
                json.dumps(
                    state,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            temporary.replace(self.state_path)
        except OSError as error:
            self._log(
                f"ホビーステーション状態保存失敗: {error}",
                "WARNING",
            )

    @staticmethod
    def _parse_datetime(value: str) -> datetime | None:
        clean = str(value).strip()
        if not clean:
            return None
        try:
            parsed = datetime.fromisoformat(
                clean.replace("Z", "+00:00")
            )
        except ValueError:
            try:
                from email.utils import parsedate_to_datetime

                parsed = parsedate_to_datetime(clean)
            except (TypeError, ValueError):
                return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def _now_iso(self) -> str:
        now = self.now_provider()
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        return now.astimezone(timezone.utc).isoformat()

    def _log_scan_summary(self, diagnostics: dict[str, Any]) -> None:
        self._log(
            "ホビーステーション記事種別件数: "
            + json.dumps(
                diagnostics.get("article_type_counts", {}),
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        self._log(
            "ホビーステーションTCG別件数: "
            + json.dumps(
                diagnostics.get("tcg_counts", {}),
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        type_counts = diagnostics.get("article_type_counts", {})
        self._log(
            "ホビーステーション保存候補件数: "
            f"商品={type_counts.get('product_schedule', 0)} "
            f"応募={type_counts.get('application', 0)}"
        )
        self._log(
            "ホビーステーション除外件数: "
            f"{diagnostics.get('excluded_count', 0)} / "
            + json.dumps(
                diagnostics.get("excluded_reasons", {}),
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        self._log(
            "ホビーステーションHTTP失敗件数: "
            f"{diagnostics.get('http_failure_count', 0)}"
        )
        self._log(
            "ホビーステーション所要時間: "
            f"{diagnostics.get('elapsed_seconds', 0):.3f}秒"
        )

    def _log(self, message: str, level: str = "INFO") -> None:
        try:
            self.log_manager.write(message, level)
        except OSError:
            pass
