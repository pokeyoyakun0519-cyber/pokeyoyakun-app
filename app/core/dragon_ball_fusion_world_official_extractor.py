from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, timezone
from html import unescape
from urllib.parse import urljoin, urlparse


class DragonBallFusionWorldOfficialExtractor:
    """DBSCG FUSION WORLD日本公式の商品一覧専用Extractor。"""

    LIST_URL = "https://www.dbs-cardgame.com/fw/jp/products/"
    PAGE_COUNT = 6
    TCG_IDENTIFIER = "DRAGON_BALL_FUSION_WORLD"
    _BLOCK = re.compile(
        r'<li\s+class=["\']prpductListItem\s+cardCol["\']>(?P<body>.*?)</li>',
        re.IGNORECASE | re.DOTALL,
    )
    _SUPPLY = re.compile(
        r"スリーブ|プレイマット|カードケース|ストレージボックス|"
        r"チャンピオンシップセット|フィギュア|グッズ|サプライ",
        re.IGNORECASE,
    )
    _CARD_OTHER = re.compile(
        r"プレミアムカードコレクション|ANNIVERSARY\s*SET|アニバーサリーセット",
        re.IGNORECASE,
    )
    _PRODUCT_CODE = re.compile(r"[\[【]((?:FB|FS|SB|ST)\d{2})[\]】]", re.I)

    @classmethod
    def list_page_urls(cls) -> tuple[str, ...]:
        return tuple(f"{cls.LIST_URL}?page={page}" for page in range(1, cls.PAGE_COUNT + 1))

    def validate_japanese_page(self, html: str, final_url: str) -> None:
        parsed = urlparse(final_url)
        if (
            parsed.scheme.casefold() != "https"
            or (parsed.hostname or "").casefold() != "www.dbs-cardgame.com"
            or not parsed.path.startswith("/fw/jp/products/")
            or "prpductListItem" not in html
        ):
            raise ValueError("DBSCG FUSION WORLD日本公式の商品ページではありません。")

    def extract_list_products(
        self, html: str, page_url: str, source_name: str
    ) -> list[dict]:
        self.validate_japanese_page(html, page_url)
        verified_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        comingsoon_at = html.find('id="comingsoon"')
        products: list[dict] = []
        for match in self._BLOCK.finditer(html):
            body = match.group("body")
            link = re.search(r'<a[^>]+href=["\'](?P<url>[^"\']+)', body, re.I)
            title = re.search(
                r'<h3[^>]*class=["\'][^"\']*cardText[^"\']*["\'][^>]*>'
                r'(?P<value>.*?)</h3>', body, re.I | re.S,
            )
            if not link or not title:
                continue
            name = self._clean_text(title.group("value"))
            if not self._is_card_product(name):
                continue
            detail_url = urljoin(page_url, unescape(link.group("url")))
            if not self.is_product_detail_url(detail_url):
                continue
            code_match = self._PRODUCT_CODE.search(name)
            product_code = code_match.group(1).upper() if code_match else ""
            date_text = self._field_value(body, "発売日")
            release_date, date_precision = self._release_date(date_text)
            price = self._price(self._field_value(body, "メーカー希望小売価格"))
            image = re.search(r'data-src=["\'](?P<url>[^"\']+)', body, re.I)
            if not image:
                image = re.search(r'<img[^>]+src=["\'](?P<url>[^"\']+)', body, re.I)
            official_id = urlparse(detail_url).path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
            upcoming = comingsoon_at >= 0 and match.start() > comingsoon_at
            digest = hashlib.sha256(detail_url.encode("utf-8")).hexdigest()[:20]
            products.append({
                "id": f"dragon_ball_fusion_world_official_{digest}",
                "tcg_identifier": self.TCG_IDENTIFIER,
                "tcg_key": "dragon_ball_fusion_world",
                "tcg": "ドラゴンボールSCG フュージョンワールド",
                "name": name[:180],
                "official_product_id": official_id,
                "product_code": product_code,
                # 日本公式にJANの記載がない商品は推測しない。
                "jan": "",
                "release_date": release_date,
                "release_date_text": date_text,
                "release_date_precision": date_precision,
                "product_kind": self._product_kind(name, product_code),
                "msrp": price,
                "msrp_includes_tax": True,
                "reference_price": price,
                "official_url": detail_url,
                "image_url": urljoin(page_url, unescape(image.group("url"))) if image else "",
                "source": source_name or "DBSCG FUSION WORLD公式",
                "source_type": "dragon_ball_fusion_world_official",
                "last_verified_at": verified_at,
                "manufacturer_official": True,
                "status": "発売予定" if upcoming else "発売中",
                "product_status": "UPCOMING" if upcoming else "RELEASED",
                "favorite": False,
                "reserved": False,
                "candidate_confidence": 1.0,
                "candidate_reasons": ["DBSCG FUSION WORLD日本公式商品一覧"],
                "sites": [{
                    "site_key": "dragon_ball_fusion_world_official",
                    "name": source_name or "DBSCG FUSION WORLD公式",
                    "status": "公式商品ページを確認",
                    "url": detail_url,
                    "notice": "日本公式の商品一覧から取得しました。",
                }],
            })
        return products

    @staticmethod
    def is_product_detail_url(url: str) -> bool:
        parsed = urlparse(url)
        return (
            parsed.scheme.casefold() == "https"
            and (parsed.hostname or "").casefold() == "www.dbs-cardgame.com"
            and bool(re.fullmatch(r"/fw/jp/products/(?:01|02)_\d+\.html", parsed.path))
        )

    @classmethod
    def _is_card_product(cls, name: str) -> bool:
        if cls._SUPPLY.search(name):
            return False
        return bool(cls._PRODUCT_CODE.search(name) or cls._CARD_OTHER.search(name))

    @staticmethod
    def _product_kind(name: str, code: str) -> str:
        if code.startswith(("FB", "SB", "ST")):
            return "ブースターパック"
        if code.startswith("FS"):
            return "スタートデッキ"
        if "プレミアム" in name or "ANNIVERSARY" in name.upper() or "アニバーサリー" in name:
            return "プレミアム商品"
        return "その他カード商品"

    @classmethod
    def _field_value(cls, body: str, label: str) -> str:
        match = re.search(
            rf'<dt[^>]*class=["\'][^"\']*cardInfoTit[^"\']*["\'][^>]*>\s*{label}\s*</dt>'
            rf'\s*<dd[^>]*class=["\'][^"\']*cardInfoTxt[^"\']*["\'][^>]*>(.*?)</dd>',
            body, re.I | re.S,
        )
        return cls._clean_text(match.group(1)) if match else ""

    @staticmethod
    def _release_date(value: str) -> tuple[str, str]:
        exact = re.search(r"(20\d{2})[./年](\d{1,2})[./月](\d{1,2})", value)
        if exact:
            return (
                f"{int(exact.group(1)):04d}-{int(exact.group(2)):02d}-{int(exact.group(3)):02d}",
                "day",
            )
        month = re.search(r"(20\d{2})年(\d{1,2})月", value)
        if month:
            # ProductStoreのrelease_dateは日精度のISO日付。月しか公式掲載が
            # ない場合は日を推測せず、release_date_textへ原文を保持する。
            return "", "month"
        return "", "unknown"

    @staticmethod
    def _price(value: str) -> int | None:
        match = re.search(r"(?:￥|¥)?\s*(\d[\d,]*)\s*円?", value)
        return int(match.group(1).replace(",", "")) if match else None

    @staticmethod
    def _clean_text(value: str) -> str:
        return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", value))).strip()
