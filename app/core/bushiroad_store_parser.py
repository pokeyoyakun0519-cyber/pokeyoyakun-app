from __future__ import annotations

import re
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import date
from html import unescape
from html.parser import HTMLParser
from typing import Any, Callable
from urllib.parse import urljoin, urlparse

from core.application_site import normalize_application_site
from core.log_manager import LogManager
from core.secure_https import build_https_opener


FetchResult = tuple[int, str, str]
FetchCallable = Callable[[str, float], FetchResult]


class _BushiroadCollectionParser(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.products: list[dict[str, Any]] = []
        self.next_url = ""
        self._card: dict[str, Any] | None = None
        self._card_depth = 0
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key: value or "" for key, value in attrs}
        classes = set(values.get("class", "").split())

        if tag == "link" and "next" in values.get("rel", "").split():
            self.next_url = urljoin(self.base_url, values.get("href", ""))
        elif tag == "a" and "next" in values.get("rel", "").split():
            self.next_url = urljoin(self.base_url, values.get("href", ""))

        if (
            tag == "div"
            and self._card is None
            and "product-item" in classes
            and values.get("data-handle")
        ):
            self._card = {
                "title": unescape(values.get("data-title", "")).strip(),
                "handle": values.get("data-handle", "").strip(),
                "available": values.get("data-available", "").casefold() == "true",
                "url": "",
                "image_url": "",
            }
            self._card_depth = 1
            self._text = []
            return

        if self._card is None:
            return

        if tag == "div":
            self._card_depth += 1

        if tag == "a":
            href = values.get("href", "").strip()
            if "/products/" in href and not self._card.get("url"):
                self._card["url"] = urljoin(self.base_url, href)

        if tag == "img" and not self._card.get("image_url"):
            source = (
                values.get("data-src")
                or values.get("src")
                or values.get("data-original")
                or ""
            ).strip()
            if source:
                self._card["image_url"] = self._image_url(source)

    def handle_data(self, data: str) -> None:
        if self._card is not None and data.strip():
            self._text.append(data.strip())

    def handle_endtag(self, tag: str) -> None:
        if self._card is None or tag != "div":
            return
        self._card_depth -= 1
        if self._card_depth:
            return

        text = re.sub(r"\s+", " ", " ".join(self._text)).strip()
        product = dict(self._card)
        product["text"] = text
        product["status"] = _inventory_status(text, bool(product.get("available")))
        product["price"] = _price_from_text(text)
        product["release_date"] = _release_date(text)
        self.products.append(product)
        self._card = None
        self._text = []

    @staticmethod
    def _image_url(source: str) -> str:
        source = source.replace("{width}x", "600x")
        if source.startswith("//"):
            return "https:" + source
        return source


class _DetailMetadataParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.text: list[str] = []
        self.image_url = ""
        self._unavailable_depth = 0
        self.unavailable_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key: value or "" for key, value in attrs}
        if tag == "meta":
            property_name = values.get("property", "").casefold()
            if property_name == "og:image:secure_url":
                self.image_url = values.get("content", "").strip()
            elif property_name == "og:image" and not self.image_url:
                self.image_url = values.get("content", "").strip()
        if (
            tag in {"p", "div", "span"}
            and "product__no_longer_available" in values.get("class", "").split()
        ):
            self._unavailable_depth = 1
        elif self._unavailable_depth and tag in {"p", "div", "span"}:
            self._unavailable_depth += 1

    def handle_data(self, data: str) -> None:
        clean = data.strip()
        if clean:
            self.text.append(clean)
            if self._unavailable_depth:
                self.unavailable_text.append(clean)

    def handle_endtag(self, tag: str) -> None:
        if self._unavailable_depth and tag in {"p", "div", "span"}:
            self._unavailable_depth -= 1


def _inventory_status(text: str, available: bool) -> str:
    if "販売終了" in text:
        return "販売終了"
    if re.search(r"売\s*切|売り切れ|在庫なし", text):
        return "売り切れ"
    if re.search(r"予約受付中|予約注文|予約商品", text):
        return "予約受付中"
    if re.search(r"販売中|カートに追加", text) or available:
        return "販売中"
    return "状態不明"


def _price_from_text(text: str) -> int | None:
    match = re.search(r"(\d[\d,]*)\s*円\s*(?:\(\s*税込\s*\))?", text)
    if not match:
        return None
    amount = int(match.group(1).replace(",", ""))
    return amount if amount > 0 else None


def _release_date(text: str) -> str:
    normalized = re.sub(r"\s+", " ", unescape(text))
    match = re.search(
        r"発売日\s*[】\]：:]?\s*"
        r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日",
        normalized,
    )
    if not match:
        match = re.search(
            r"(\d{4})[./-](\d{1,2})[./-](\d{1,2})\s*発売(?:予定)?",
            normalized,
        )
    if not match:
        return ""
    year, month, day = (int(value) for value in match.groups())
    try:
        date(year, month, day)
        return f"{year:04d}-{month:02d}-{day:02d}"
    except ValueError:
        return ""


class BushiroadStoreParser:
    COLLECTION_URL = "https://bushiroad-store.com/collections/ws-tcg"
    ALLOWED_HOST = "bushiroad-store.com"

    def __init__(
        self,
        *,
        fetcher: FetchCallable | None = None,
        log_manager: LogManager | None = None,
        timeout_seconds: float = 20.0,
        max_retries: int = 1,
        request_interval_seconds: float = 0.5,
        max_pages: int = 5,
        max_detail_pages: int = 3,
    ):
        self.fetcher = fetcher or self._default_fetch
        self.log_manager = log_manager or LogManager()
        self.timeout_seconds = max(1.0, float(timeout_seconds))
        self.max_retries = max(0, min(int(max_retries), 2))
        self.request_interval_seconds = max(0.0, float(request_interval_seconds))
        self.max_pages = max(1, min(int(max_pages), 10))
        self.max_detail_pages = max(0, min(int(max_detail_pages), 10))
        self._cache: dict[str, FetchResult] = {}
        self._failed_urls: set[str] = set()
        self._last_request_at = 0.0
        self.last_diagnostics: dict[str, Any] = {}

    def search_candidate(
        self,
        candidate: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], str]:
        started = time.monotonic()
        candidate_name = str(candidate.get("name", "")).strip()
        self._log(f"ブシロードストア取得開始: {candidate_name or '商品名なし'}")

        products: list[dict[str, Any]] = []
        exclusion_reasons: Counter[str] = Counter()
        visited_pages: set[str] = set()
        next_url = self.COLLECTION_URL
        page_count = 0

        while next_url and page_count < self.max_pages:
            canonical = self._canonical_url(next_url)
            if canonical in visited_pages:
                exclusion_reasons["ページングURL重複"] += 1
                break
            visited_pages.add(canonical)

            response = self._request(next_url)
            if response is None:
                exclusion_reasons["一覧取得失敗"] += 1
                break
            _, html, final_url = response
            parser = _BushiroadCollectionParser(final_url)
            parser.feed(html)
            if not parser.products:
                exclusion_reasons["商品カード構造を検出できない"] += 1
            products.extend(parser.products)
            next_url = parser.next_url
            page_count += 1

        unique_products: dict[str, dict[str, Any]] = {}
        for product in products:
            product_url = self._canonical_url(str(product.get("url", "")))
            if not product_url or not product.get("title"):
                exclusion_reasons["商品名または商品URLが欠損"] += 1
                continue
            if product_url in unique_products:
                exclusion_reasons["商品URL重複"] += 1
                continue
            unique_products[product_url] = product

        detected_count = len(unique_products)
        self._log(f"ブシロードストア一覧検出件数: {detected_count}件")

        matched = []
        for product in unique_products.values():
            if self._matches_candidate(candidate, product):
                matched.append(product)
            else:
                exclusion_reasons["候補商品名と不一致"] += 1

        detail_count = 0
        for product in matched[: self.max_detail_pages]:
            if product.get("release_date") and product.get("image_url"):
                continue
            response = self._request(str(product.get("url", "")))
            if response is None:
                exclusion_reasons["商品詳細取得失敗"] += 1
                continue
            _, detail_html, _ = response
            detail = self.parse_detail_html(detail_html)
            detail_count += 1
            if detail.get("release_date"):
                product["release_date"] = detail["release_date"]
            if detail.get("image_url"):
                product["image_url"] = detail["image_url"]
            if product.get("status") == "状態不明" and detail.get("status"):
                product["status"] = detail["status"]

        hits = [self._build_hit(product) for product in matched]
        elapsed = time.monotonic() - started
        excluded_count = sum(exclusion_reasons.values())
        reason_text = "、".join(
            f"{reason}={count}" for reason, count in sorted(exclusion_reasons.items())
        ) or "なし"

        self.last_diagnostics = {
            "collection_page_count": page_count,
            "detected_count": detected_count,
            "detail_checked_count": detail_count,
            "saved_count": len(hits),
            "excluded_count": excluded_count,
            "excluded_reasons": dict(exclusion_reasons),
            "elapsed_seconds": round(elapsed, 3),
            "http_cache_count": len(self._cache),
        }
        self._log(f"ブシロードストア詳細確認件数: {detail_count}件")
        self._log(f"ブシロードストア保存件数: {len(hits)}件")
        self._log(
            f"ブシロードストア除外件数: {excluded_count}件 / 理由: {reason_text}"
        )
        self._log(f"ブシロードストア所要時間: {elapsed:.2f}秒")

        return (
            hits,
            "ブシロード オンラインストア: "
            f"一覧{detected_count}件 / 詳細{detail_count}件 / "
            f"保存{len(hits)}件 / 除外{excluded_count}件 / {elapsed:.2f}秒",
        )

    @staticmethod
    def parse_collection_html(
        html: str,
        base_url: str = COLLECTION_URL,
    ) -> tuple[list[dict[str, Any]], str]:
        parser = _BushiroadCollectionParser(base_url)
        parser.feed(html)
        return parser.products, parser.next_url

    @staticmethod
    def parse_detail_html(html: str) -> dict[str, Any]:
        parser = _DetailMetadataParser()
        parser.feed(html)
        text = re.sub(r"\s+", " ", " ".join(parser.text)).strip()
        unavailable = " ".join(parser.unavailable_text)
        return {
            "release_date": _release_date(text),
            "image_url": BushiroadStoreParser._safe_image_url(parser.image_url),
            "status": _inventory_status(unavailable, False) if unavailable else "",
        }

    def _request(self, url: str) -> FetchResult | None:
        canonical = self._canonical_url(url)
        if not canonical or not self._is_allowed_url(canonical):
            self._log(f"ブシロードストアHTTP結果: URL拒否 {url}", "WARNING")
            return None
        if canonical in self._cache:
            self._log(f"ブシロードストアHTTP結果: cache {canonical}")
            return self._cache[canonical]
        if canonical in self._failed_urls:
            self._log(
                f"ブシロードストアHTTP結果: 失敗キャッシュ {canonical}",
                "WARNING",
            )
            return None

        last_error = ""
        for attempt in range(self.max_retries + 1):
            self._respect_interval()
            try:
                status, html, final_url = self.fetcher(
                    canonical,
                    self.timeout_seconds,
                )
                if not self._is_allowed_url(final_url):
                    raise ValueError("許可されていないリダイレクト先")
                self._log(
                    "ブシロードストアHTTP結果: "
                    f"{status} {canonical} attempt={attempt + 1}"
                )
                if status != 200:
                    last_error = f"HTTP {status}"
                    if status < 500:
                        break
                    continue
                result = (status, html, final_url)
                self._cache[canonical] = result
                return result
            except (TimeoutError, urllib.error.URLError) as error:
                last_error = f"{type(error).__name__}: {error}"
                self._log(
                    "ブシロードストアHTTP結果: "
                    f"失敗 {canonical} attempt={attempt + 1} {last_error}",
                    "WARNING",
                )
            except Exception as error:
                last_error = f"{type(error).__name__}: {error}"
                self._log(
                    f"ブシロードストアHTTP結果: 失敗 {canonical} {last_error}",
                    "WARNING",
                )
                break

        self._log(
            f"ブシロードストアHTTP取得失敗: {canonical} / {last_error}",
            "ERROR",
        )
        self._failed_urls.add(canonical)
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
                "User-Agent": (
                    "PokeyoyaKun/1.25.0 "
                    "(Windows; +https://pokeyoyakun.com)"
                ),
                "Accept": (
                    "text/html,application/xhtml+xml,"
                    "application/xml;q=0.9,*/*;q=0.8"
                ),
                "Accept-Language": "ja,en-US;q=0.8,en;q=0.6",
            },
        )
        try:
            with build_https_opener().open(request, timeout=timeout) as response:
                raw = response.read(3_000_000)
                charset = response.headers.get_content_charset() or "utf-8"
                return (
                    int(response.status),
                    raw.decode(charset, errors="replace"),
                    response.geturl(),
                )
        except urllib.error.HTTPError as error:
            return int(error.code), "", error.geturl() or url

    @classmethod
    def _matches_candidate(
        cls,
        candidate: dict[str, Any],
        product: dict[str, Any],
    ) -> bool:
        candidate_name = cls._match_text(str(candidate.get("name", "")))
        product_name = cls._match_text(str(product.get("title", "")))
        product_code = cls._match_text(str(candidate.get("product_code", "")))

        if product_code and product_code in product_name:
            return True
        if not candidate_name or not product_name:
            return False
        return (
            candidate_name in product_name
            or product_name in candidate_name
        )

    @staticmethod
    def _match_text(text: str) -> str:
        normalized = re.sub(
            r"[\s「」『』・･_\-&＆（）()【】\[\]、。！!：:×]",
            "",
            unescape(text).casefold(),
        )
        for removable in (
            "ヴァイスシュヴァルツ",
            "ブースターパック",
            "トライアルデッキ",
            "プレミアムブースター",
            "スペシャルカードセット",
            "カードセット",
            "box",
        ):
            normalized = normalized.replace(
                re.sub(r"\s+", "", removable.casefold()),
                "",
            )
        return normalized

    @staticmethod
    def _build_hit(product: dict[str, Any]) -> dict[str, Any]:
        status = str(product.get("status", "状態不明"))
        title = str(product.get("title", "")).strip()
        price = product.get("price")
        product_url = str(product.get("url", "")).strip()
        clean_text = title
        if price:
            clean_text += f" 販売価格 {int(price):,}円（税込）"

        hit = {
            "site_key": "bushiroad_store",
            "name": "ブシロード オンラインストア",
            "url": product_url,
            "product_url": product_url,
            "status": status,
            "release_date": str(product.get("release_date", "")),
            "price": price,
            "sale_price": price,
            "price_includes_tax": True,
            "image_url": str(product.get("image_url", "")),
            "reservation_open": status == "予約受付中",
            "on_sale": status == "販売中",
            "sold_out": status in {"売り切れ", "販売終了"},
            "application_method": "Web",
            "result_mode": "account_page",
            "regions": ["全国"],
            "retailer_verified": True,
            "seller": "ブシロード オンラインストア",
            "confidence": 0.99,
            "text": clean_text,
            "notice": (
                f"発売日: {product.get('release_date')}"
                if product.get("release_date")
                else ""
            ),
            "tcg_key": "weiss",
        }
        return normalize_application_site(hit)

    @classmethod
    def _canonical_url(cls, url: str) -> str:
        clean = str(url).strip()
        if not clean:
            return ""
        parsed = urlparse(clean)
        return parsed._replace(fragment="").geturl()

    @classmethod
    def _is_allowed_url(cls, url: str) -> bool:
        try:
            parsed = urlparse(url)
            return (
                parsed.scheme == "https"
                and (parsed.hostname or "").casefold() == cls.ALLOWED_HOST
                and parsed.port in (None, 443)
            )
        except ValueError:
            return False

    @classmethod
    def _safe_image_url(cls, url: str) -> str:
        clean = str(url).strip()
        if clean.startswith("http://bushiroad-store.com/"):
            clean = "https://" + clean.removeprefix("http://")
        if clean.startswith("//"):
            clean = "https:" + clean
        try:
            parsed = urlparse(clean)
            host = (parsed.hostname or "").casefold()
            allowed_hosts = (
                "bushiroad-store.com",
                "cdn.shopify.com",
                "cdn.shopifycdn.com",
            )
            if (
                parsed.scheme == "https"
                and any(
                    host == allowed or host.endswith("." + allowed)
                    for allowed in allowed_hosts
                )
            ):
                return clean
        except ValueError:
            pass
        return ""

    def _log(self, message: str, level: str = "INFO") -> None:
        try:
            self.log_manager.write(message, level)
        except OSError:
            pass
