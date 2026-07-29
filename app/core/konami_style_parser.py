from __future__ import annotations

import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import date
from html import unescape
from html.parser import HTMLParser
from typing import Any, Callable

from core.application_site import normalize_application_site
from core.log_manager import LogManager
from core.secure_https import build_https_opener


FetchResult = tuple[int, str, str]
Fetcher = Callable[[str, float], FetchResult]


class _KonamiListParser(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.products: list[dict[str, Any]] = []
        self.total_count = 0
        self._main_depth = 0
        self._card_depth = 0
        self._card: dict[str, Any] | None = None
        self._capture = ""
        self._parts: list[str] = []

    @staticmethod
    def _classes(attrs: dict[str, str | None]) -> set[str]:
        return set(str(attrs.get("class") or "").split())

    def handle_starttag(self, tag: str, attrs_list):
        attrs = dict(attrs_list)
        classes = self._classes(attrs)

        if tag == "ul" and "main-item-list" in classes:
            self._main_depth = 1
            return
        if self._main_depth and tag == "ul":
            self._main_depth += 1

        if self._main_depth and tag == "li":
            if self._card is None and "grid-col5" in classes:
                self._card = {
                    "title": "",
                    "url": "",
                    "image_url": "",
                    "status_text": "",
                    "price_text": "",
                }
                self._card_depth = 1
            elif self._card is not None:
                self._card_depth += 1

        if self._card is not None:
            if tag == "a":
                href = str(attrs.get("href") or "").strip()
                if "detail.php" in href and not self._card["url"]:
                    self._card["url"] = urllib.parse.urljoin(
                        self.base_url, href
                    )
            elif tag == "img":
                alt = str(attrs.get("alt") or "").strip()
                src = str(
                    attrs.get("data-src")
                    or attrs.get("src")
                    or ""
                ).strip()
                if "picture" in classes:
                    if alt and not self._card["title"]:
                        self._card["title"] = alt
                    if src and not self._card["image_url"]:
                        self._card["image_url"] = urllib.parse.urljoin(
                            self.base_url, src
                        )
                if alt and any(
                    marker in alt
                    for marker in ("予約", "販売", "売切", "売り切れ")
                ):
                    self._card["status_text"] += " " + alt

            if "item-name" in classes:
                self._capture = "title"
                self._parts = []
            elif "item-price" in classes:
                self._capture = "price_text"
                self._parts = []
            elif "item-tag" in classes or "status" in classes:
                self._capture = "status_text"
                self._parts = []

        if "item-count" in classes:
            self._capture = "total_count"
            self._parts = []

    def handle_data(self, data: str):
        text = data.strip()
        if text and self._capture:
            self._parts.append(text)

    def handle_endtag(self, tag: str):
        if self._capture and tag in {"p", "span", "div"}:
            text = re.sub(r"\s+", " ", " ".join(self._parts)).strip()
            if self._capture == "total_count":
                match = re.search(r"(\d[\d,]*)", text)
                if match:
                    self.total_count = int(match.group(1).replace(",", ""))
            elif self._card is not None and text:
                key = self._capture
                if key == "status_text":
                    self._card[key] = (
                        str(self._card.get(key, "")) + " " + text
                    ).strip()
                else:
                    self._card[key] = text
            self._capture = ""
            self._parts = []

        if tag == "li" and self._card is not None:
            self._card_depth -= 1
            if self._card_depth == 0:
                title = str(self._card.get("title", "")).strip()
                url = str(self._card.get("url", "")).strip()
                if title and url:
                    self.products.append(dict(self._card))
                self._card = None

        if tag == "ul" and self._main_depth:
            self._main_depth -= 1


class _KonamiDetailParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.image_url = ""
        self.text_parts: list[str] = []
        self._capture_title = False
        self._title_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs_list):
        attrs = dict(attrs_list)
        classes = set(str(attrs.get("class") or "").split())
        if tag == "meta" and str(attrs.get("property") or "") == "og:image":
            self.image_url = str(attrs.get("content") or "").strip()
        if (
            tag == "h2"
            and "hdg-text" in classes
            and not self.title
            and not self._capture_title
        ):
            self._capture_title = True
            self._title_parts = []

    def handle_data(self, data: str):
        text = data.strip()
        if text:
            self.text_parts.append(text)
            if self._capture_title:
                self._title_parts.append(text)

    def handle_endtag(self, tag: str):
        if tag == "h2" and self._capture_title:
            self.title = re.sub(
                r"\s+", " ", " ".join(self._title_parts)
            ).strip()
            self._capture_title = False


class KonamiStyleParser:
    BASE_URL = "https://www.konamistyle.jp/"
    SEARCH_URL = (
        "https://www.konamistyle.jp/products/list.php"
        "?mode=search&name={query}&disp_stock_status=1"
    )
    ALLOWED_HOST = "www.konamistyle.jp"
    IMAGE_HOSTS = {
        "www.konamistyle.jp",
        "konamistyle.jp",
        "eccdn-endpoint01.azureedge.net",
    }
    MAX_PAGES = 3
    MAX_DETAILS = 6
    MIN_CONFIDENCE = 0.82

    def __init__(
        self,
        fetcher: Fetcher | None = None,
        log_manager: LogManager | None = None,
        timeout_seconds: float = 20.0,
        max_retries: int = 1,
        request_interval_seconds: float = 0.6,
    ):
        self.fetcher = fetcher or self._default_fetch
        self.log_manager = log_manager or LogManager()
        self.timeout_seconds = timeout_seconds
        self.max_retries = max(0, max_retries)
        self.request_interval_seconds = max(0.0, request_interval_seconds)
        self._last_request_at = 0.0
        self._cache: dict[str, FetchResult] = {}
        self._failed_urls: set[str] = set()
        self.last_diagnostics: dict[str, Any] = {}

    def search_candidate(
        self, candidate: dict[str, Any]
    ) -> tuple[list[dict[str, Any]], str]:
        started = time.monotonic()
        if str(candidate.get("tcg_key", "")).casefold() != "yugioh":
            return [], "KONAMI STYLE: 遊戯王以外は対象外"

        terms = self.build_search_terms(candidate)
        detected: dict[str, dict[str, Any]] = {}
        exclusions: Counter[str] = Counter()
        http_before = len(self._cache)
        for term in terms:
            self._log(f"KONAMI STYLE検索語: {term}")
            term_count = 0
            total = 0
            for page in range(1, self.MAX_PAGES + 1):
                url = self._search_url(term, page)
                response = self._request(url)
                if response is None:
                    exclusions["検索ページ取得失敗"] += 1
                    break
                _, html, final_url = response
                products, total = self.parse_list_html(html, final_url)
                term_count += len(products)
                for product in products:
                    canonical = self._canonical_url(product.get("url", ""))
                    if not canonical:
                        exclusions["商品URL不正"] += 1
                        continue
                    product["url"] = canonical
                    product["_search_term"] = term
                    detected.setdefault(canonical, product)
                if not products or page * 10 >= total:
                    break
            self._log(
                f"KONAMI STYLE検出件数: 検索語={term} {term_count}件"
            )

        plausible = [
            item for item in detected.values()
            if self._preliminary_confidence(candidate, item) >= 0.55
        ]
        excluded_preliminary = len(detected) - len(plausible)
        if excluded_preliminary:
            exclusions["事前照合の信頼度不足"] += excluded_preliminary

        hits: list[dict[str, Any]] = []
        matched = 0
        detail_count = 0
        for product in plausible[: self.MAX_DETAILS]:
            response = self._request(str(product["url"]))
            if response is not None:
                detail_count += 1
                detail = self.parse_detail_html(response[1])
                for key, value in detail.items():
                    if value not in ("", None):
                        product[key] = value

            confidence, reason = self._match_confidence(candidate, product)
            if confidence < self.MIN_CONFIDENCE:
                exclusions[reason or "照合の信頼度不足"] += 1
                continue
            matched += 1
            hit = self._build_hit(product, confidence)
            if hit:
                hits.append(hit)
            else:
                exclusions["商品情報不足"] += 1

        if len(plausible) > self.MAX_DETAILS:
            exclusions["詳細確認上限"] += len(plausible) - self.MAX_DETAILS

        hits = list({
            str(item["product_url"]): item for item in hits
        }.values())
        elapsed = time.monotonic() - started
        self.last_diagnostics = {
            "search_terms": terms,
            "detected_count": len(detected),
            "detail_checked_count": detail_count,
            "matched_count": matched,
            "saved_count": len(hits),
            "excluded_count": sum(exclusions.values()),
            "excluded_reasons": dict(exclusions),
            "elapsed_seconds": round(elapsed, 3),
            "http_request_count": len(self._cache) - http_before,
        }
        reason_text = ", ".join(
            f"{key}:{value}" for key, value in exclusions.items()
        ) or "なし"
        self._log(f"KONAMI STYLE照合成功件数: {matched}件")
        self._log(
            f"KONAMI STYLE除外件数: {sum(exclusions.values())}件 / "
            f"理由: {reason_text}"
        )
        self._log(f"KONAMI STYLE保存件数: {len(hits)}件")
        self._log(f"KONAMI STYLE所要時間: {elapsed:.2f}秒")
        return (
            hits,
            "KONAMI STYLE: "
            f"検出{len(detected)}件 / 照合{matched}件 / "
            f"保存{len(hits)}件 / 除外{sum(exclusions.values())}件 / "
            f"{elapsed:.2f}秒",
        )

    @classmethod
    def build_search_terms(cls, candidate: dict[str, Any]) -> list[str]:
        raw_name = cls.repair_mojibake(str(candidate.get("name", ""))).strip()
        code = cls.repair_mojibake(str(
            candidate.get("product_code")
            or candidate.get("code")
            or ""
        )).strip()
        stripped = cls._strip_decorations(raw_name)
        if "ラッシュデュエル" in raw_name:
            series = "遊戯王ラッシュデュエル"
        elif "OCG" in raw_name.upper():
            series = "遊戯王OCG"
        else:
            series = "遊戯王"
        terms = [code, raw_name, stripped, series]
        return list(dict.fromkeys(term for term in terms if term))

    @staticmethod
    def parse_list_html(
        html: str, base_url: str = BASE_URL
    ) -> tuple[list[dict[str, Any]], int]:
        parser = _KonamiListParser(base_url)
        parser.feed(html)
        products = []
        for item in parser.products:
            item["price"] = KonamiStyleParser._price(item.get("price_text", ""))
            item["status"] = KonamiStyleParser._status(
                " ".join([
                    str(item.get("status_text", "")),
                    str(item.get("title", "")),
                ])
            )
            item["image_url"] = KonamiStyleParser._safe_image_url(
                item.get("image_url", "")
            )
            products.append(item)
        return products, parser.total_count or len(products)

    @staticmethod
    def parse_detail_html(html: str) -> dict[str, Any]:
        parser = _KonamiDetailParser()
        parser.feed(html)
        text = re.sub(r"\s+", " ", " ".join(parser.text_parts)).strip()
        code_match = re.search(
            r"商品番号\s*[:：]?\s*([A-Za-z0-9_-]+)", text
        )
        price_match = re.search(
            r"(?:希望小売価格|販売価格)\s*[:：]?\s*([\d,]+)\s*円", text
        )
        release_text = ""
        release_match = re.search(
            r"発売日\s*[:：]?\s*"
            r"((?:20\d{2})年\d{1,2}月"
            r"(?:\d{1,2}日|上旬|中旬|下旬)?"
            r"(?:頃|より順次お届け予定)?)",
            text,
        )
        if release_match:
            release_text = release_match.group(1).strip()
        release_date = ""
        exact = re.search(
            r"(20\d{2})年(\d{1,2})月(\d{1,2})日", release_text
        )
        if exact:
            try:
                release_date = date(
                    int(exact.group(1)),
                    int(exact.group(2)),
                    int(exact.group(3)),
                ).isoformat()
            except ValueError:
                release_date = ""
        return {
            "title": parser.title,
            "product_code": code_match.group(1) if code_match else "",
            "price": (
                int(price_match.group(1).replace(",", ""))
                if price_match else None
            ),
            "image_url": KonamiStyleParser._safe_image_url(parser.image_url),
            "status": KonamiStyleParser._status(text),
            "release_date": release_date,
            "release_date_text": release_text,
        }

    @staticmethod
    def repair_mojibake(text: str) -> str:
        if not text or not any(marker in text for marker in ("ƒ", "‰", "—", "‹")):
            return text
        raw = bytearray()
        try:
            for char in text:
                try:
                    raw.extend(char.encode("cp1252"))
                except UnicodeEncodeError:
                    code = ord(char)
                    if code > 255:
                        return text
                    raw.append(code)
            repaired = bytes(raw).decode("cp932")
            return repaired if repaired else text
        except (UnicodeDecodeError, ValueError):
            return text

    @classmethod
    def _match_confidence(
        cls, candidate: dict[str, Any], product: dict[str, Any]
    ) -> tuple[float, str]:
        candidate_code = cls._match_text(
            str(candidate.get("product_code") or candidate.get("code") or "")
        )
        product_code = cls._match_text(str(product.get("product_code", "")))
        if candidate_code and product_code:
            if candidate_code == product_code:
                return 1.0, ""
            return 0.0, "商品コード不一致"

        score = cls._preliminary_confidence(candidate, product)
        candidate_date = str(candidate.get("release_date", ""))[:10]
        product_date = str(product.get("release_date", ""))[:10]
        if candidate_date and product_date:
            if candidate_date == product_date:
                score += 0.08
            else:
                return 0.0, "発売日不一致"
        if score < cls.MIN_CONFIDENCE:
            return score, "商品名・主要語の信頼度不足"
        return min(score, 0.99), ""

    @classmethod
    def _preliminary_confidence(
        cls, candidate: dict[str, Any], product: dict[str, Any]
    ) -> float:
        candidate_name = cls.repair_mojibake(str(candidate.get("name", "")))
        product_name = str(product.get("title", ""))
        left = cls._match_text(candidate_name)
        right = cls._match_text(product_name)
        if not left or not right:
            return 0.0
        if left == right:
            return 0.95
        if left in right or right in left:
            shorter = min(len(left), len(right))
            longer = max(len(left), len(right))
            return 0.84 + (0.10 * shorter / max(longer, 1))

        left_tokens = cls._major_tokens(candidate_name)
        right_tokens = cls._major_tokens(product_name)
        if not left_tokens:
            return 0.0
        overlap = len(left_tokens & right_tokens)
        coverage = overlap / len(left_tokens)
        precision = overlap / max(len(right_tokens), 1)
        return 0.65 * coverage + 0.25 * precision

    @staticmethod
    def _strip_decorations(name: str) -> str:
        clean = re.sub(r"[【\[].*?[】\]]", " ", name)
        clean = re.sub(
            r"\b(?:BOX|ボックス|新品|予約|特典付き|初回限定)\b",
            " ",
            clean,
            flags=re.IGNORECASE,
        )
        return re.sub(r"\s+", " ", clean).strip()

    @staticmethod
    def _match_text(text: str) -> str:
        normalized = re.sub(
            r"[\s「」『』・･_\-－&＆（）()【】\[\]、。！!：:×/☆〜～]",
            "",
            unescape(text).casefold(),
        )
        for prefix in (
            "遊戯王ocgデュエルモンスターズ",
            "遊戯王ocg",
        ):
            normalized = normalized.replace(prefix, "")
        return re.sub(r"\d+(?:pack|パック)", "", normalized)

    @classmethod
    def _major_tokens(cls, text: str) -> set[str]:
        clean = cls._strip_decorations(text).casefold()
        tokens = re.findall(r"[a-z0-9]{2,}|[一-龯ぁ-んァ-ヶー]{2,}", clean)
        stop = {
            "遊戯王", "ocg", "デュエルモンスターズ",
            "カード", "パック", "セット",
        }
        return {token for token in tokens if token not in stop}

    @staticmethod
    def _price(text: str) -> int | None:
        match = re.search(r"([\d,]+)\s*円", str(text))
        return int(match.group(1).replace(",", "")) if match else None

    @staticmethod
    def _status(text: str) -> str:
        compact = re.sub(r"\s+", "", str(text))
        if any(word in compact for word in ("売り切れ", "売切", "品切れ")):
            return "売り切れ"
        if any(word in compact for word in ("販売終了", "受付終了")):
            return "販売終了"
        if any(word in compact for word in ("予約注文", "予約受付", "予約商品")):
            return "予約受付中"
        if any(word in compact for word in ("カートに入れる", "販売中", "購入する")):
            return "販売中"
        return "状態不明"

    @classmethod
    def _build_hit(
        cls, product: dict[str, Any], confidence: float
    ) -> dict[str, Any]:
        title = str(product.get("title", "")).strip()
        product_url = cls._canonical_url(product.get("url", ""))
        if not title or not product_url:
            return {}
        status = str(product.get("status", "状態不明"))
        price = product.get("price")
        hit = {
            "site_key": "konami_style",
            "name": "KONAMI STYLE",
            "url": product_url,
            "product_url": product_url,
            "status": status,
            "price": price,
            "sale_price": price,
            "price_includes_tax": True,
            "image_url": cls._safe_image_url(product.get("image_url", "")),
            "release_date": str(product.get("release_date", "")),
            "release_date_text": str(product.get("release_date_text", "")),
            "product_code": str(product.get("product_code", "")),
            "reservation_open": status == "予約受付中",
            "on_sale": status == "販売中",
            "sold_out": status in {"売り切れ", "販売終了"},
            "application_method": "Web",
            "result_mode": "account_page",
            "regions": ["全国"],
            "retailer_verified": True,
            "seller": "KONAMI STYLE",
            "confidence": confidence,
            "text": (
                f"{title} {int(price):,}円（税込）"
                if isinstance(price, (int, float)) else title
            ),
            "notice": (
                f"発売日: {product.get('release_date_text')}"
                if product.get("release_date_text") else ""
            ),
            "tcg_key": "yugioh",
        }
        return normalize_application_site(hit)

    @classmethod
    def _search_url(cls, term: str, page: int) -> str:
        url = cls.SEARCH_URL.format(
            query=urllib.parse.quote_plus(term, safe="")
        )
        if page > 1:
            url += f"&pageno={page}"
        return url

    def _request(self, url: str) -> FetchResult | None:
        canonical = self._canonical_url(url)
        if not self._is_allowed_url(canonical):
            self._log(f"KONAMI STYLE HTTP結果: URL拒否 {url}", "WARNING")
            return None
        if canonical in self._cache:
            self._log(f"KONAMI STYLE HTTP結果: cache {canonical}")
            return self._cache[canonical]
        if canonical in self._failed_urls:
            return None

        last_error = ""
        for attempt in range(self.max_retries + 1):
            self._respect_interval()
            try:
                status, html, final_url = self.fetcher(
                    canonical, self.timeout_seconds
                )
                if not self._is_allowed_url(final_url):
                    raise ValueError("許可されていないリダイレクト先")
                self._log(
                    f"KONAMI STYLE HTTP結果: {status} {canonical} "
                    f"attempt={attempt + 1}"
                )
                if status == 200:
                    result = (status, html, final_url)
                    self._cache[canonical] = result
                    return result
                last_error = f"HTTP {status}"
                if status < 500:
                    break
            except (TimeoutError, urllib.error.URLError) as error:
                last_error = f"{type(error).__name__}: {error}"
                self._log(
                    f"KONAMI STYLE HTTP結果: 失敗 {canonical} "
                    f"attempt={attempt + 1} {last_error}",
                    "WARNING",
                )
            except Exception as error:
                last_error = f"{type(error).__name__}: {error}"
                self._log(
                    f"KONAMI STYLE HTTP結果: 失敗 {canonical} {last_error}",
                    "WARNING",
                )
                break
        self._failed_urls.add(canonical)
        self._log(
            f"KONAMI STYLE HTTP取得失敗: {canonical} / {last_error}",
            "ERROR",
        )
        return None

    def _respect_interval(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        remaining = self.request_interval_seconds - elapsed
        if self._last_request_at and remaining > 0:
            time.sleep(remaining)
        self._last_request_at = time.monotonic()

    @classmethod
    def _canonical_url(cls, url: Any) -> str:
        clean = str(url or "").strip()
        if not clean:
            return ""
        parsed = urllib.parse.urlparse(clean)
        query = urllib.parse.urlencode(sorted(
            urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        ))
        return parsed._replace(query=query, fragment="").geturl()

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
    def _safe_image_url(cls, url: Any) -> str:
        clean = str(url or "").strip()
        if clean.startswith("//"):
            clean = "https:" + clean
        try:
            parsed = urllib.parse.urlparse(clean)
            if (
                parsed.scheme == "https"
                and (parsed.hostname or "").casefold() in cls.IMAGE_HOSTS
                and parsed.port in (None, 443)
            ):
                return clean
        except ValueError:
            pass
        return ""

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

    def _log(self, message: str, level: str = "INFO") -> None:
        try:
            self.log_manager.write(message, level)
        except OSError:
            pass
