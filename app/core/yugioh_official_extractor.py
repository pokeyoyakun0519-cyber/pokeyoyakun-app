import hashlib
import re
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse


YUGIOH_PRODUCT_KINDS = (
    "基本パック",
    "ブースターパック",
    "デッキビルドパック",
    "コンセプトパック",
    "スペシャルパック",
    "ストラクチャーデッキ",
    "構築済みデッキ",
    "LIMITED PACK",
    "PREMIUM PACK",
    "WORLD PREMIERE PACK",
)
SALES_KEYWORDS = ("予約", "抽選", "当選", "落選", "受注販売")
DATE_PATTERN = re.compile(
    r"(?P<year>20\d{2})年\s*(?P<month>\d{1,2})月\s*"
    r"(?P<day>\d{1,2})日(?:\s*\([^)]*\))?\s*発売"
)


class _YugiohLinkCollector(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.href = ""
        self.parts: list[str] = []
        self.links: list[dict[str, str]] = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag.lower() == "a":
            self.href = urljoin(
                self.base_url, str(attributes.get("href", "")).strip()
            )
            self.parts = []
        elif tag.lower() == "img" and self.href:
            alt = str(attributes.get("alt", "")).strip()
            if alt:
                self.parts.append(alt)

    def handle_data(self, data):
        if self.href and data.strip():
            self.parts.append(data.strip())

    def handle_endtag(self, tag):
        if tag.lower() != "a" or not self.href:
            return
        self.links.append(
            {
                "url": self.href,
                "text": re.sub(r"\s+", " ", " ".join(self.parts)).strip(),
            }
        )
        self.href = ""
        self.parts = []


class YugiohOfficialExtractor:
    """遊戯王OCG公式の商品一覧・詳細ページ専用アダプター。"""

    MAX_DETAIL_PAGES = 12

    def collect_candidate_links(
        self, html: str, source_url: str
    ) -> list[dict[str, str]]:
        parser = _YugiohLinkCollector(source_url)
        try:
            parser.feed(html)
        except Exception:
            return []
        output = []
        seen = set()
        for link in parser.links:
            normalized = link["url"].split("#", 1)[0]
            if not self.is_product_detail_url(normalized) or normalized in seen:
                continue
            seen.add(normalized)
            output.append({"url": normalized, "text": link["text"]})
        for item in self._collect_script_products(html, source_url):
            if item["url"] in seen:
                continue
            seen.add(item["url"])
            output.append(item)
        return output[: self.MAX_DETAIL_PAGES]

    @classmethod
    def _collect_script_products(
        cls, html: str, source_url: str
    ) -> list[dict[str, str]]:
        output = []
        for match in re.finditer(
            r"p\[\d+\]\s*=\s*\{(?P<body>.*?)\}\s*;",
            html,
            flags=re.DOTALL,
        ):
            body = match.group("body")
            values = {}
            for key in ("title", "release-date", "url", "detail"):
                field = re.search(
                    rf'["\']{re.escape(key)}["\']\s*:\s*["\'](?P<value>.*?)["\']',
                    body,
                    flags=re.DOTALL,
                )
                values[key] = (
                    unescape(field.group("value")).strip() if field else ""
                )
            if values["detail"] not in {"page", "ditem"}:
                continue
            slug = values["url"].strip(" /")
            if not re.fullmatch(r"[a-z0-9_-]+", slug):
                continue
            url = urljoin(source_url, f"{slug}/")
            if not cls.is_product_detail_url(url):
                continue
            output.append(
                {
                    "url": url,
                    "text": " ".join(
                        part
                        for part in (values["title"], values["release-date"])
                        if part
                    ),
                }
            )
        return output

    def extract_detail_products(
        self,
        html: str,
        detail_url: str,
        source_name: str,
        link_text: str = "",
    ) -> list[dict]:
        if not self.is_product_detail_url(detail_url):
            return []
        text = self._html_to_text(html)
        name = self._extract_name(html, link_text)
        release_date = self._extract_release_date(text + "\n" + link_text)
        if not name or not release_date:
            return []
        product_kind = self._extract_product_kind(text, name)
        sales_terms = [keyword for keyword in SALES_KEYWORDS if keyword in text]
        digest = hashlib.sha256(
            f"{name}|{release_date}|{detail_url}".encode("utf-8")
        ).hexdigest()[:20]
        return [
            {
                "id": f"yugioh_official_{digest}",
                "tcg_key": "yugioh",
                "tcg": "遊戯王OCG",
                "name": name,
                "release_date": release_date,
                "product_kind": product_kind,
                "official_url": detail_url,
                "sales_keywords": sales_terms,
                "reservation_related": any(
                    term in sales_terms for term in ("予約", "受注販売")
                ),
                "lottery_related": any(
                    term in sales_terms for term in ("抽選", "当選", "落選")
                ),
                "status": "発売予定",
                "favorite": False,
                "reserved": False,
                "source_type": "yugioh_official_detail",
                "candidate_confidence": 1.0,
                "candidate_reasons": ["遊戯王OCG公式商品詳細"],
                "sites": [
                    {
                        "site_key": "yugioh_official",
                        "name": source_name or "遊戯王OCG公式",
                        "status": "公式商品ページを確認",
                        "url": detail_url,
                        "notice": "公式商品一覧から詳細ページをたどって取得しました。",
                    }
                ],
            }
        ]

    @staticmethod
    def is_product_detail_url(url: str) -> bool:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if host != "yugioh-card.com" and not host.endswith(".yugioh-card.com"):
            return False
        path = parsed.path.rstrip("/") + "/"
        return bool(re.fullmatch(r"/japan/products/[a-z0-9_-]+/", path))

    @staticmethod
    def _extract_name(html: str, link_text: str) -> str:
        match = re.search(
            r"<h1[^>]*>(.*?)</h1>", html, flags=re.IGNORECASE | re.DOTALL
        )
        raw = match.group(1) if match else link_text
        value = re.sub(r"<[^>]+>", " ", raw)
        value = re.sub(r"\s+", " ", unescape(value)).strip()
        value = re.sub(r"\s*20\d{2}年\d{1,2}月\d{1,2}日.*$", "", value)
        if not re.search(r"遊(?:戯王|☆戯☆王)|YU-?GI-?OH", value, re.IGNORECASE):
            return ""
        return value[:160]

    @staticmethod
    def _extract_release_date(text: str) -> str:
        match = DATE_PATTERN.search(text)
        if not match:
            return ""
        try:
            return (
                f"{int(match.group('year')):04d}-"
                f"{int(match.group('month')):02d}-"
                f"{int(match.group('day')):02d}"
            )
        except (TypeError, ValueError):
            return ""

    @staticmethod
    def _extract_product_kind(text: str, name: str) -> str:
        for kind in YUGIOH_PRODUCT_KINDS:
            if kind.lower() in name.lower() or kind.lower() in text.lower():
                return kind
        return "その他商品"

    @staticmethod
    def _html_to_text(html: str) -> str:
        value = re.sub(
            r"<(script|style)[^>]*>.*?</\1>",
            " ",
            html,
            flags=re.IGNORECASE | re.DOTALL,
        )
        value = re.sub(r"<[^>]+>", " ", value)
        return re.sub(r"\s+", " ", unescape(value)).strip()
