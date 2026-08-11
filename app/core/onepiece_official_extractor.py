from __future__ import annotations

import hashlib
import re
from html import unescape
from urllib.parse import urljoin, urlparse


class OnePieceOfficialExtractor:
    """ONE PIECEカードゲーム日本公式の商品一覧専用Extractor。"""

    MAX_LIST_PAGES = 3
    MAX_DETAIL_PAGES = 4
    _BLOCK = re.compile(
        r'<li[^>]*class="[^"]*linkListColBox[^"]*"[^>]*data-cat="(?P<cat>[^"]+)"[^>]*>'
        r'(?P<body>.*?)</li>',
        re.IGNORECASE | re.DOTALL,
    )

    def validate_japanese_page(self, html: str, final_url: str) -> None:
        parsed = urlparse(final_url)
        if (
            parsed.scheme.casefold() != "https"
            or
            (parsed.hostname or "").casefold() != "www.onepiece-cardgame.com"
            or not parsed.path.startswith("/products/")
            or not re.search(r'<html[^>]+lang=["\']ja["\']', html, re.IGNORECASE)
        ):
            raise ValueError("ワンピース公式の日本語商品ページではありません。")

    def extract_list_products(
        self, html: str, page_url: str, source_name: str
    ) -> list[dict]:
        self.validate_japanese_page(html, page_url)
        products: list[dict] = []
        for match in self._BLOCK.finditer(html):
            body = match.group("body")
            link = re.search(
                r'<a[^>]+href=["\'](?P<url>[^"\']+)["\'][^>]*class=["\'][^"\']*linkListColItem',
                body,
                re.IGNORECASE,
            )
            title = re.search(
                r'<h4[^>]*class=["\'][^"\']*linkListColTitle[^"\']*["\'][^>]*>(?P<value>.*?)</h4>',
                body,
                re.IGNORECASE | re.DOTALL,
            )
            if not link or not title:
                continue
            detail_url = urljoin(page_url, unescape(link.group("url")))
            if not self.is_product_detail_url(detail_url):
                continue
            name = self._clean_text(title.group("value"))
            if not name:
                continue
            if any(term in name for term in (
                "カードケース", "プレイマット", "スリーブ", "ラバーマット",
            )):
                continue
            date_match = re.search(
                r'<time[^>]+datetime=["\'](?P<date>20\d{2}-\d{2}-\d{2})["\']',
                body,
                re.IGNORECASE,
            )
            image = re.search(
                r'<img[^>]+(?:data-src|src)=["\'](?P<url>[^"\']+)["\']',
                body,
                re.IGNORECASE,
            )
            products.append(
                self._product(
                    name=name,
                    release_date=date_match.group("date") if date_match else "",
                    detail_url=detail_url,
                    category=match.group("cat"),
                    source_name=source_name,
                    image_url=urljoin(page_url, unescape(image.group("url"))) if image else "",
                    msrp=self._extract_price(self._clean_text(body)),
                )
            )
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
        title = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)', html, re.IGNORECASE)
        text = self._clean_text(re.sub(r"<[^>]+>", " ", html))
        date_match = re.search(r"(20\d{2})[./年](\d{1,2})[./月](\d{1,2})日?", text)
        return {
            "name": self._clean_title(title.group(1)) if title else "",
            "release_date": self._iso_date(date_match) if date_match else "",
            "msrp": self._extract_price(text),
        }

    @staticmethod
    def is_list_url(url: str) -> bool:
        parsed = urlparse(url)
        return (parsed.hostname or "").casefold() == "www.onepiece-cardgame.com" and parsed.path == "/products/"

    @staticmethod
    def is_product_detail_url(url: str) -> bool:
        parsed = urlparse(url)
        return (
            (parsed.hostname or "").casefold() == "www.onepiece-cardgame.com"
            and bool(re.fullmatch(
                r"/products/(?:[a-z0-9_-]+\.html|(?:boosters|decks|other)/[a-z0-9_-]+/)",
                parsed.path,
                re.IGNORECASE,
            ))
        )

    def _product(
        self,
        *,
        name: str,
        release_date: str,
        detail_url: str,
        category: str,
        source_name: str,
        image_url: str,
        msrp: int | None,
    ) -> dict:
        product_code = self._product_code(name, detail_url)
        digest = hashlib.sha256(detail_url.encode("utf-8")).hexdigest()[:20]
        return {
            "id": f"onepiece_official_{digest}",
            "tcg_key": "onepiece",
            "tcg": "ワンピースカード",
            "name": name[:180],
            "product_code": product_code,
            "release_date": release_date,
            "product_kind": self._product_kind(name, category),
            "msrp": msrp,
            "msrp_includes_tax": True,
            "reference_price": msrp,
            "official_url": detail_url,
            "image_url": image_url,
            "status": "発売予定",
            "favorite": False,
            "reserved": False,
            "source_type": "onepiece_official",
            "manufacturer_official": True,
            "information_type": "PRODUCT",
            "candidate_confidence": 1.0,
            "candidate_reasons": ["ワンピースカード日本公式商品一覧"],
            "sites": [{
                "site_key": "onepiece_official",
                "name": source_name or "ワンピースカードゲーム公式",
                "status": "公式商品ページを確認",
                "url": detail_url,
                "notice": "日本公式の商品一覧から取得しました。",
            }],
        }

    @staticmethod
    def _product_kind(name: str, category: str) -> str:
        for value in ("エクストラブースター", "ブースターパック", "スタートデッキ", "プレミアムカードコレクション"):
            if value in name:
                return value
        return {"boosters": "ブースターパック", "decks": "スタートデッキ"}.get(category, "その他")

    @staticmethod
    def _product_code(name: str, detail_url: str) -> str:
        match = re.search(r"\b(?:OP|EB|ST|PRB)-?\d{2,3}\b", name, re.IGNORECASE)
        if match:
            value = match.group(0).upper()
            return value if "-" in value else re.sub(r"([A-Z]+)(\d+)", r"\1-\2", value)
        slug = urlparse(detail_url).path.rstrip("/").rsplit("/", 1)[-1].split(".", 1)[0].upper()
        return slug if re.fullmatch(r"(?:OP|EB|ST|PRB)\d+", slug) else ""

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

    @classmethod
    def _clean_title(cls, value: str) -> str:
        return cls._clean_text(value).split(" | ONE PIECE", 1)[0].strip()

    @staticmethod
    def _iso_date(match: re.Match) -> str:
        try:
            return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"
        except (ValueError, TypeError):
            return ""

    @staticmethod
    def _page_number(url: str) -> int:
        match = re.search(r"(?:^|[?&])page=(\d+)", urlparse(url).query)
        return int(match.group(1)) if match else 1
