from __future__ import annotations

import hashlib
import re
from html import unescape
from urllib.parse import urljoin, urlparse


class GundamOfficialExtractor:
    """ガンダムカードゲーム日本公式の商品一覧専用Extractor。"""

    LIST_URL = "https://www.gundam-gcg.com/jp/products/list.php"
    MAX_LIST_PAGES = 4
    MAX_DETAIL_PAGES = 4
    _BLOCK = re.compile(
        r'<div[^>]*class=["\'][^"\']*productsDetail[^"\']*["\'][^>]*data-tags=["\'](?P<tag>[^"\']+)["\'][^>]*>'
        r'(?P<body>.*?)</a>\s*</div>',
        re.IGNORECASE | re.DOTALL,
    )

    def validate_japanese_page(self, html: str, final_url: str) -> None:
        parsed = urlparse(final_url)
        if (
            parsed.scheme.casefold() != "https"
            or
            (parsed.hostname or "").casefold() != "www.gundam-gcg.com"
            or not parsed.path.startswith("/jp/products/")
            or not re.search(r'<body[^>]+class=["\'][^"\']*lang-ja', html, re.IGNORECASE)
        ):
            raise ValueError("ガンダムカード公式の日本語商品ページではありません。")

    def extract_list_products(
        self, html: str, page_url: str, source_name: str
    ) -> list[dict]:
        self.validate_japanese_page(html, page_url)
        products: list[dict] = []
        for match in self._BLOCK.finditer(html):
            body = match.group("body")
            link = re.search(r'<a[^>]+href=["\'](?P<url>[^"\']+)["\'][^>]*class=["\'][^"\']*productsDetailInner', body, re.IGNORECASE)
            title = re.search(r'<div[^>]*class=["\'][^"\']*cardTit[^"\']*["\'][^>]*>(?P<value>.*?)</div>', body, re.IGNORECASE | re.DOTALL)
            if not link or not title:
                continue
            detail_url = urljoin(page_url, unescape(link.group("url")))
            if not self.is_product_detail_url(detail_url):
                continue
            name = self._clean_text(title.group("value"))
            date_match = re.search(r'<dt[^>]*>\s*発売日\s*</dt>\s*<dd[^>]*>(?P<date>20\d{2}[./]\d{1,2}[./]\d{1,2})</dd>', body, re.IGNORECASE | re.DOTALL)
            image = re.search(r'<img[^>]+src=["\'](?P<url>[^"\']+)["\']', body, re.IGNORECASE)
            products.append(self._product(
                name=name,
                release_date=self._normalize_date(date_match.group("date")) if date_match else "",
                detail_url=detail_url,
                tag=match.group("tag"),
                source_name=source_name,
                image_url=urljoin(page_url, unescape(image.group("url"))) if image else "",
                msrp=self._extract_price(self._clean_text(body)),
            ))
        return products

    def collect_page_urls(self, html: str, page_url: str) -> list[str]:
        pages = {1: page_url}
        for value in re.findall(r'href=["\']([^"\']*\bpage=\d+[^"\']*)["\']', html):
            url = urljoin(page_url, unescape(value.replace("&amp;", "&")))
            if self.is_list_url(url):
                pages.setdefault(self._page_number(url), url)
        return [pages[number] for number in sorted(pages)[: self.MAX_LIST_PAGES]]

    def supplement_from_detail(self, html: str, detail_url: str) -> dict[str, str]:
        self.validate_japanese_page(html, detail_url)
        title = re.search(r'<h2[^>]*class=["\'][^"\']*titleColInnerHead[^"\']*["\'][^>]*>(.*?)</h2>', html, re.IGNORECASE | re.DOTALL)
        date_match = re.search(r'<div[^>]*class=["\']date["\'][^>]*>\s*<span>(20\d{2}[./]\d{1,2}[./]\d{1,2})</span>', html, re.IGNORECASE)
        return {
            "name": self._clean_text(title.group(1)) if title else "",
            "release_date": self._normalize_date(date_match.group(1)) if date_match else "",
            "msrp": self._extract_price(self._clean_text(html)),
        }

    @staticmethod
    def is_list_url(url: str) -> bool:
        parsed = urlparse(url)
        return (parsed.hostname or "").casefold() == "www.gundam-gcg.com" and parsed.path == "/jp/products/list.php"

    @staticmethod
    def is_product_detail_url(url: str) -> bool:
        parsed = urlparse(url)
        return (
            (parsed.hostname or "").casefold() == "www.gundam-gcg.com"
            and bool(re.fullmatch(r"/jp/products/[a-z0-9_-]+\.html", parsed.path, re.IGNORECASE))
        )

    def _product(self, *, name: str, release_date: str, detail_url: str, tag: str, source_name: str, image_url: str, msrp: int | None) -> dict:
        digest = hashlib.sha256(detail_url.encode("utf-8")).hexdigest()[:20]
        return {
            "id": f"gundam_official_{digest}",
            "tcg_key": "gundam",
            "tcg": "ガンダムカード",
            "name": name[:180],
            "product_code": self._product_code(name, detail_url),
            "release_date": release_date,
            "product_kind": self._product_kind(tag, name),
            "msrp": msrp,
            "msrp_includes_tax": True,
            "reference_price": msrp,
            "official_url": detail_url,
            "image_url": image_url,
            "status": "発売予定",
            "favorite": False,
            "reserved": False,
            "source_type": "gundam_official",
            "candidate_confidence": 1.0,
            "candidate_reasons": ["ガンダムカードゲーム日本公式商品一覧"],
            "sites": [{
                "site_key": "gundam_official",
                "name": source_name or "ガンダムカードゲーム公式",
                "status": "公式商品ページを確認",
                "url": detail_url,
                "notice": "日本公式の商品一覧から取得しました。",
            }],
        }

    @staticmethod
    def _product_kind(tag: str, name: str) -> str:
        if tag == "BOOSTERPACK":
            return "ブースターパック"
        if tag == "STARTERDECK":
            return "スタートデッキ"
        if tag == "ACCESSORIES":
            return "アクセサリー"
        if tag == "PREMIUMBANDAI" or "プレミアムバンダイ" in name:
            return "プレミアムバンダイ"
        return "その他"

    @staticmethod
    def _product_code(name: str, detail_url: str) -> str:
        match = re.search(r"\b(?:GD|ST|EB|PC)\d{2,3}A?\b", name, re.IGNORECASE)
        if match:
            return match.group(0).upper()
        slug = urlparse(detail_url).path.rsplit("/", 1)[-1].split(".", 1)[0].upper()
        return slug if re.fullmatch(r"(?:GD|ST|EB|PC)\d{2,3}A?", slug) else ""

    @staticmethod
    def _clean_text(value: str) -> str:
        return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", value))).strip()

    @staticmethod
    def _extract_price(text: str) -> int | None:
        match = re.search(
            r"(?:メーカー希望小売価格|販売価格|価格)\s*[:：]?\s*[￥¥]?\s*(\d[\d,]*)\s*円",
            text,
        )
        return int(match.group(1).replace(",", "")) if match else None

    @staticmethod
    def _normalize_date(value: str) -> str:
        match = re.fullmatch(r"(20\d{2})[./](\d{1,2})[./](\d{1,2})", value.strip())
        return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-{int(match.group(3)):02d}" if match else ""

    @staticmethod
    def _page_number(url: str) -> int:
        match = re.search(r"(?:^|[?&])page=(\d+)", urlparse(url).query)
        return int(match.group(1)) if match else 1
