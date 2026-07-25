from __future__ import annotations

import hashlib
import re
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", value))).strip()


def _normalize_date(value: str) -> str:
    match = re.search(r"(20\d{2})[年./-]\s*(\d{1,2})[月./-]\s*(\d{1,2})日?", value)
    if not match:
        return ""
    return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"


def _price(value: str) -> int | None:
    matches = re.findall(r"(?:￥|¥)?\s*(\d[\d,]*)\s*円", value)
    prices = [int(item.replace(",", "")) for item in matches]
    return max(prices) if prices else None


def _product(
    *,
    tcg_key: str,
    tcg: str,
    source_type: str,
    source_name: str,
    reason: str,
    name: str,
    release_date: str,
    detail_url: str,
    image_url: str = "",
    product_code: str = "",
    product_kind: str = "その他",
    msrp: int | None = None,
) -> dict:
    digest = hashlib.sha256(detail_url.encode("utf-8")).hexdigest()[:20]
    return {
        "id": f"{source_type}_{digest}",
        "tcg_key": tcg_key,
        "tcg": tcg,
        "name": name[:180],
        "product_code": product_code,
        "release_date": release_date,
        "product_kind": product_kind,
        "msrp": msrp,
        "msrp_includes_tax": True,
        "reference_price": msrp,
        "official_url": detail_url,
        "image_url": image_url,
        "status": "発売予定",
        "favorite": False,
        "reserved": False,
        "source_type": source_type,
        "candidate_confidence": 1.0,
        "candidate_reasons": [reason],
        "sites": [{
            "site_key": source_type,
            "name": source_name,
            "status": "公式商品ページを確認",
            "url": detail_url,
            "notice": "日本公式の商品一覧から取得しました。",
        }],
    }


class DuelMastersOfficialExtractor:
    """デュエル・マスターズ公式商品一覧専用Extractor。"""

    LIST_URL = "https://dm.takaratomy.co.jp/product/"
    _BLOCK = re.compile(
        r'<div[^>]*class=["\'][^"\']*itemList01_item[^"\']*["\'][^>]*>'
        r"(?P<body>.*?)(?=<div[^>]*class=[\"'][^\"']*itemList01_item|\Z)",
        re.IGNORECASE | re.DOTALL,
    )

    def validate_japanese_page(self, html: str, final_url: str) -> None:
        parsed = urlparse(final_url)
        if (
            parsed.scheme.casefold() != "https"
            or (parsed.hostname or "").casefold() != "dm.takaratomy.co.jp"
            or not parsed.path.startswith("/product")
            or "itemList01_item" not in html
        ):
            raise ValueError("デュエル・マスターズ公式の商品ページではありません。")

    def extract_list_products(
        self, html: str, page_url: str, source_name: str
    ) -> list[dict]:
        self.validate_japanese_page(html, page_url)
        products = []
        for match in self._BLOCK.finditer(html):
            body = match.group("body")
            link = re.search(
                r'<a[^>]+href=["\'](?P<url>[^"\']*?/product/[^"\']+)["\']',
                body,
                re.IGNORECASE,
            )
            title = re.search(
                r'<h2[^>]*class=["\'][^"\']*title[^"\']*["\'][^>]*>(?P<value>.*?)</h2>',
                body,
                re.IGNORECASE | re.DOTALL,
            )
            if not link or not title:
                continue
            detail_url = urljoin(page_url, unescape(link.group("url")))
            if not self.is_product_detail_url(detail_url):
                continue
            text = _clean_text(body)
            name = _clean_text(title.group("value"))
            date = _normalize_date(text)
            image = re.search(r'<img[^>]+(?:data-src|src)=["\']([^"\']+)["\']', body, re.IGNORECASE)
            kind = re.search(
                r'class=["\'][^"\']*product_type[^"\']*["\'][^>]*>(.*?)</div>',
                body,
                re.IGNORECASE | re.DOTALL,
            )
            code = re.search(r"\bDM\d{2}-[A-Z]{2,4}\d+\b", name, re.IGNORECASE)
            products.append(_product(
                tcg_key="duelmasters",
                tcg="デュエル・マスターズ",
                source_type="duelmasters_official",
                source_name=source_name or "デュエル・マスターズ公式",
                reason="デュエル・マスターズ公式商品一覧",
                name=name,
                release_date=date,
                detail_url=detail_url,
                image_url=urljoin(page_url, unescape(image.group(1))) if image else "",
                product_code=code.group(0).upper() if code else "",
                product_kind=_clean_text(kind.group(1)) if kind else "その他",
                msrp=_price(text),
            ))
        return products

    @staticmethod
    def is_product_detail_url(url: str) -> bool:
        parsed = urlparse(url)
        return (
            (parsed.hostname or "").casefold() == "dm.takaratomy.co.jp"
            and bool(re.fullmatch(r"/product/[a-z0-9_-]+/?", parsed.path, re.IGNORECASE))
        )


class WeissOfficialExtractor:
    """ヴァイスシュヴァルツ公式商品一覧専用Extractor。"""

    LIST_URL = "https://ws-tcg.com/products/"
    _LINK = re.compile(
        r'<a[^>]+href=["\'](?P<url>[^"\']+/products/[^"\']+)["\'][^>]*'
        r'class=["\'][^"\']*products__link[^"\']*["\'][^>]*>(?P<body>.*?)</a>',
        re.IGNORECASE | re.DOTALL,
    )

    def validate_japanese_page(self, html: str, final_url: str) -> None:
        parsed = urlparse(final_url)
        if (
            parsed.scheme.casefold() != "https"
            or (parsed.hostname or "").casefold() != "ws-tcg.com"
            or not parsed.path.startswith("/products")
            or "products__link" not in html
        ):
            raise ValueError("ヴァイスシュヴァルツ公式の商品ページではありません。")

    def extract_list_products(
        self, html: str, page_url: str, source_name: str
    ) -> list[dict]:
        self.validate_japanese_page(html, page_url)
        products = []
        for match in self._LINK.finditer(html):
            body = match.group("body")
            detail_url = urljoin(page_url, unescape(match.group("url")))
            if not self.is_product_detail_url(detail_url):
                continue
            title = re.search(
                r'class=["\'][^"\']*products__name[^"\']*["\'][^>]*>(.*?)</',
                body,
                re.IGNORECASE | re.DOTALL,
            )
            if not title:
                continue
            text = _clean_text(body)
            kind = re.search(
                r'class=["\'][^"\']*products__catItem[^"\']*["\'][^>]*>(.*?)</',
                body,
                re.IGNORECASE | re.DOTALL,
            )
            image = re.search(r'<img[^>]+(?:data-src|src)=["\']([^"\']+)["\']', body, re.IGNORECASE)
            products.append(_product(
                tcg_key="weiss",
                tcg="ヴァイスシュヴァルツ",
                source_type="weiss_official",
                source_name=source_name or "ヴァイスシュヴァルツ公式",
                reason="ヴァイスシュヴァルツ公式商品一覧",
                name=_clean_text(title.group(1)),
                release_date=_normalize_date(text),
                detail_url=detail_url,
                image_url=urljoin(page_url, unescape(image.group(1))) if image else "",
                product_kind=_clean_text(kind.group(1)) if kind else "その他",
                msrp=_price(text),
            ))
        return products

    @staticmethod
    def is_product_detail_url(url: str) -> bool:
        parsed = urlparse(url)
        return (
            (parsed.hostname or "").casefold() == "ws-tcg.com"
            and bool(re.fullmatch(r"/products/[a-z0-9_-]+/?", parsed.path, re.IGNORECASE))
        )


class _MtgLinkParser(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.href = ""
        self.parts: list[str] = []
        self.links: list[dict[str, str]] = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag.lower() == "a":
            self.href = urljoin(self.base_url, str(attributes.get("href", "")).strip())
            self.parts = []
        elif tag.lower() == "img" and self.href:
            alt = str(attributes.get("alt", "")).strip()
            if alt:
                self.parts.append(alt)

    def handle_data(self, data):
        if self.href and data.strip():
            self.parts.append(data.strip())

    def handle_endtag(self, tag):
        if tag.lower() == "a" and self.href:
            self.links.append({"url": self.href, "text": " ".join(self.parts).strip()})
            self.href = ""
            self.parts = []


class MtgOfficialExtractor:
    """Magic: The Gathering日本公式の商品一覧・詳細ページ専用Extractor。"""

    LIST_URL = "https://mtg-jp.com/products/index.php"
    MAX_DETAIL_PAGES = 12

    def validate_japanese_page(self, html: str, final_url: str) -> None:
        parsed = urlparse(final_url)
        if (
            parsed.scheme.casefold() != "https"
            or (parsed.hostname or "").casefold() != "mtg-jp.com"
            or not parsed.path.startswith("/products")
        ):
            raise ValueError("マジック：ザ・ギャザリング日本公式の商品ページではありません。")

    def extract_list_products(
        self, html: str, page_url: str, source_name: str
    ) -> list[dict]:
        self.validate_japanese_page(html, page_url)
        parser = _MtgLinkParser(page_url)
        parser.feed(html)
        products = []
        seen = set()
        for link in parser.links:
            detail_url = link["url"].split("#", 1)[0]
            if detail_url in seen or not self.is_product_detail_url(detail_url):
                continue
            seen.add(detail_url)
            name = re.sub(r"\s+", " ", link["text"]).strip()
            words = name.split()
            for repeat_count in (3, 2):
                size = len(words) // repeat_count
                if (
                    size
                    and len(words) == size * repeat_count
                    and all(
                        words[index * size:(index + 1) * size] == words[:size]
                        for index in range(1, repeat_count)
                    )
                ):
                    name = " ".join(words[:size])
                    break
            if not name:
                continue
            products.append(_product(
                tcg_key="mtg",
                tcg="マジック：ザ・ギャザリング",
                source_type="mtg_official",
                source_name=source_name or "マジック：ザ・ギャザリング日本公式",
                reason="マジック：ザ・ギャザリング日本公式商品一覧",
                name=name,
                release_date="",
                detail_url=detail_url,
            ))
        return products[: self.MAX_DETAIL_PAGES]

    def supplement_from_detail(self, html: str, detail_url: str) -> dict[str, object]:
        self.validate_japanese_page(html, detail_url)
        text = _clean_text(html)
        date_match = re.search(
            r"公式発売日\s*[|｜:]?\s*(20\d{2}年\s*\d{1,2}月\s*\d{1,2}日)",
            text,
        )
        image = re.search(
            r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
            html,
            re.IGNORECASE,
        )
        return {
            "release_date": _normalize_date(date_match.group(1)) if date_match else "",
            "image_url": urljoin(detail_url, unescape(image.group(1))) if image else "",
            "msrp": _price(text),
        }

    @staticmethod
    def is_product_detail_url(url: str) -> bool:
        parsed = urlparse(url)
        return (
            (parsed.hostname or "").casefold() == "mtg-jp.com"
            and bool(re.fullmatch(r"/products/\d+/?", parsed.path))
        )
