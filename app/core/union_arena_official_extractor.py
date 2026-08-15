from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from html import unescape
from urllib.parse import urljoin, urlparse


class UnionArenaOfficialExtractor:
    """UNION ARENA日本公式の商品一覧専用Extractor。"""

    LIST_URL = "https://www.unionarena-tcg.com/jp/products/"
    MAX_DETAIL_PAGES = 12
    _BLOCK = re.compile(
        r'<li[^>]*class=["\'][^"\']*productsDetail[^"\']*["\'][^>]*'
        r'data-tags=["\'](?P<tags>[^"\']+)["\'][^>]*>(?P<body>.*?)</li>',
        re.IGNORECASE | re.DOTALL,
    )
    _CARD_OTHER = re.compile(
        r"NEW CARD SELECTION|PREMIUM CARD SET|プレミアムコレクションボックス|"
        r"BANDAI CARD GAMES Fest.*スペシャルセット",
        re.IGNORECASE,
    )
    _SUPPLY = re.compile(
        r"サプライ|スリーブ|カードケース|バインダー|プレイマット|"
        r"アクションポイントカードセット|フィギュア|グッズ",
        re.IGNORECASE,
    )

    def validate_japanese_page(self, html: str, final_url: str) -> None:
        parsed = urlparse(final_url)
        if (
            parsed.scheme.casefold() != "https"
            or (parsed.hostname or "").casefold() != "www.unionarena-tcg.com"
            or not parsed.path.startswith("/jp/products/")
            or "productsDetail" not in html
        ):
            raise ValueError("UNION ARENA日本公式の商品ページではありません。")

    def extract_list_products(
        self, html: str, page_url: str, source_name: str
    ) -> list[dict]:
        self.validate_japanese_page(html, page_url)
        verified_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        products: list[dict] = []
        for match in self._BLOCK.finditer(html):
            body = match.group("body")
            link = re.search(r'<a[^>]+href=["\'](?P<url>[^"\']+)', body, re.I)
            title = re.search(
                r'<dt[^>]*class=["\'][^"\']*productsTit[^"\']*["\'][^>]*>'
                r'(?P<value>.*?)</dt>', body, re.I | re.S
            )
            if not link or not title:
                continue
            name = self._clean_text(title.group("value"))
            tags = match.group("tags")
            category = tags.split(",", 1)[0].casefold()
            if not self._is_card_product(category, name):
                continue
            detail_url = urljoin(page_url, unescape(link.group("url")))
            if not self.is_product_detail_url(detail_url):
                continue
            date = re.search(r"(20\d{2})[./年](\d{1,2})[./月](\d{1,2})", self._clean_text(body))
            image = re.search(r'<img[^>]+src=["\'](?P<url>[^"\']+)', body, re.I)
            price = self._extract_price(self._clean_text(body))
            official_id = urlparse(detail_url).path.removeprefix("/jp/products/").rsplit(".", 1)[0]
            digest = hashlib.sha256(detail_url.encode("utf-8")).hexdigest()[:20]
            products.append({
                "id": f"union_arena_official_{digest}",
                "tcg_key": "union_arena",
                "tcg": "UNION ARENA",
                "name": name[:180],
                "title_name": self._title_name(name),
                "official_product_id": official_id,
                "product_code": "",
                "jan": "",
                "release_date": self._date(date) if date else "",
                "product_kind": self._product_kind(category, name),
                "msrp": price,
                "msrp_includes_tax": True,
                "reference_price": price,
                "official_url": detail_url,
                "image_url": urljoin(page_url, unescape(image.group("url"))) if image else "",
                "source": source_name or "UNION ARENA公式",
                "source_type": "union_arena_official",
                "last_verified_at": verified_at,
                "manufacturer_official": True,
                "status": "発売予定",
                "favorite": False,
                "reserved": False,
                "candidate_confidence": 1.0,
                "candidate_reasons": ["UNION ARENA日本公式商品一覧"],
                "sites": [{
                    "site_key": "union_arena_official",
                    "name": source_name or "UNION ARENA公式",
                    "status": "公式商品ページを確認",
                    "url": detail_url,
                    "notice": "日本公式の商品一覧から取得しました。",
                }],
            })
        return products

    def supplement_from_detail(self, html: str, detail_url: str) -> dict[str, str | int]:
        parsed = urlparse(detail_url)
        if (
            parsed.scheme != "https"
            or (parsed.hostname or "").casefold() != "www.unionarena-tcg.com"
            or not self.is_product_detail_url(detail_url)
        ):
            raise ValueError("UNION ARENA公式商品詳細ではありません。")
        text = self._clean_text(html)
        # Related products and card descriptions may contain a different product
        # code.  Only the page's own title/primary heading is authoritative.
        heading = " ".join(
            self._clean_text(match.group(1))
            for match in re.finditer(
                r"<(?:title|h1)[^>]*>(.*?)</(?:title|h1)>", html, re.I | re.S
            )
        )
        code = re.search(r"[【\[]((?:UA|EX)\d{2}(?:BT|ST|DC))[】\]]", heading, re.I)
        jan = re.search(r"(?:JAN(?:コード)?)[：:\s]*(\d{13})", text, re.I)
        date = re.search(r"発売日\s*(20\d{2})年(\d{1,2})月(\d{1,2})日", text)
        return {
            "product_code": code.group(1).upper() if code else "",
            "jan": jan.group(1) if jan else "",
            "release_date": self._date(date) if date else "",
            "msrp": self._extract_price(text) or 0,
        }

    @staticmethod
    def is_product_detail_url(url: str) -> bool:
        parsed = urlparse(url)
        return (
            (parsed.hostname or "").casefold() == "www.unionarena-tcg.com"
            and bool(re.fullmatch(
                r"/jp/products/(?:boosters|decks|other)/[a-z0-9_./-]+\.php",
                parsed.path,
                re.I,
            ))
        )

    @classmethod
    def _is_card_product(cls, category: str, name: str) -> bool:
        if cls._SUPPLY.search(name):
            return False
        return category in {"boosters", "decks"} or bool(cls._CARD_OTHER.search(name))

    @staticmethod
    def _product_kind(category: str, name: str) -> str:
        if category == "boosters":
            return "ブースターパック"
        if category == "decks":
            return "スタートデッキ" if "スタートデッキ" in name else "構築済みデッキ"
        if "PREMIUM" in name.upper() or "プレミアム" in name:
            return "プレミアム商品"
        return "その他カード商品"

    @staticmethod
    def _title_name(name: str) -> str:
        return re.sub(
            r"^(?:UNION ARENA\s+)?(?:プレシャス)?ブースターパック\s*|"
            r"^(?:UNION ARENA\s+)?(?:スタート|アドバンスド)デッキ\s*|"
            r"^NEW CARD SELECTION\s*|^UNION ARENA PREMIUM CARD SET\s*",
            "", name, flags=re.I,
        ).strip()

    @staticmethod
    def _clean_text(value: str) -> str:
        return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", value))).strip()

    @staticmethod
    def _extract_price(text: str) -> int | None:
        match = re.search(r"(?:メーカー希望小売価格|価格)\s*[：:]?\s*(\d[\d,]*)円", text)
        return int(match.group(1).replace(",", "")) if match else None

    @staticmethod
    def _date(match: re.Match[str]) -> str:
        return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"
