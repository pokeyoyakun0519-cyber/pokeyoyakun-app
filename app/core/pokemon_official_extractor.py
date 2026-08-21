import hashlib
import json
import re
from datetime import date, timedelta
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

from core.product_candidate_validator import ProductCandidateValidator


PRODUCT_KINDS = (
    "強化拡張パック",
    "拡張パック",
    "ブースターパック",
    "ハイクラスパック",
    "プレミアムデッキセット",
    "スターターセットex",
    "スターターセット",
    "スタートデッキ",
    "スターターデッキ",
    "構築デッキ",
    "デッキセット",
)

DATE_PATTERN = re.compile(
    r"(?:(?P<year>\d{4})[./年]\s*)?"
    r"(?P<month>\d{1,2})[./月]\s*"
    r"(?P<day>\d{1,2})日?"
)

QUOTED_NAME_PATTERN = re.compile(
    r"(?P<kind>"
    + "|".join(re.escape(kind) for kind in PRODUCT_KINDS)
    + r")\s*[「『](?P<name>[^」』]{2,100})[」』]"
)

STARTER_NAME_PATTERN = re.compile(
    r"(スターターセットex\s+"
    r"(?:イーブイex|ゾロア[&＆]ゾロアークex|"
    r"ニャオハ[&＆]マスカーニャex|"
    r"[^\n、。！!]{2,60}))"
)


class _LinkCollector(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.current_href = ""
        self.current_parts: list[str] = []
        self.links: list[dict] = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)

        if tag.lower() == "a":
            self.current_href = urljoin(
                self.base_url,
                str(attrs_dict.get("href", "")).strip(),
            )
            self.current_parts = []

        if tag.lower() == "img":
            alt = str(attrs_dict.get("alt", "")).strip()
            if alt and self.current_href:
                self.current_parts.append(alt)

    def handle_data(self, data):
        text = data.strip()
        if text and self.current_href:
            self.current_parts.append(text)

    def handle_endtag(self, tag):
        if tag.lower() != "a" or not self.current_href:
            return

        text = re.sub(
            r"\s+",
            " ",
            " ".join(self.current_parts),
        ).strip()

        self.links.append(
            {
                "url": self.current_href,
                "text": text,
            }
        )
        self.current_href = ""
        self.current_parts = []


class PokemonOfficialExtractor:
    """pokemon-card.com専用の商品リンク・商品詳細解析。"""

    MAX_DETAIL_PAGES = 8

    def __init__(self):
        self.validator = ProductCandidateValidator()

    def extract_catalog_products(
        self,
        payload: str | bytes | dict,
        source_name: str,
        base_url: str = "https://www.pokemon-card.com/",
    ) -> list[dict]:
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8")
        data = json.loads(payload) if isinstance(payload, str) else payload
        if not isinstance(data, dict) or not isinstance(data.get("products"), list):
            raise ValueError("ポケモン公式商品APIの形式が不正です。")
        products = []
        for raw in data["products"]:
            if not isinstance(raw, dict):
                continue
            product_type = str(raw.get("productType", "")).strip()
            if product_type == "周辺グッズ":
                continue
            name = str(raw.get("productTitle", "")).strip()
            release_date = self._extract_release_date(str(raw.get("releaseDate", "")))
            detail = str(raw.get("link_detailPage", "")).strip()
            official_url = urljoin(base_url, detail or "/products/")
            if not name or not release_date or not detail:
                continue
            product = self._make_product(name, release_date, official_url, source_name)
            product.update({
                "product_kind": product_type or "その他",
                "official_product_id": self._official_id(official_url),
                "image_url": urljoin(base_url, str(raw.get("tumbsImg", ""))),
                "msrp": self._price(str(raw.get("priceTxt", ""))),
                "reference_price": self._price(str(raw.get("priceTxt", ""))),
                "official_url": official_url,
                "manufacturer_official": True,
                "information_type": "PRODUCT",
                "source_type": "pokemon_official_catalog",
                "candidate_confidence": 1.0,
                "candidate_reasons": ["ポケモンカード公式商品API"],
            })
            products.append(product)
        return products

    def collect_candidate_links(
        self,
        html: str,
        source_url: str,
    ) -> list[dict]:
        parser = _LinkCollector(source_url)
        parser.feed(html)

        candidates = []
        seen = set()

        for link in parser.links:
            url = link["url"]
            text = link["text"]

            parsed = urlparse(url)
            if not parsed.netloc.endswith("pokemon-card.com"):
                continue

            if not self._looks_like_product_link(url, text):
                continue

            normalized = url.split("#", 1)[0]
            if normalized in seen:
                continue

            seen.add(normalized)
            candidates.append(
                {
                    "url": normalized,
                    "text": text,
                }
            )

        candidates.sort(
            key=lambda item: (
                0 if "/ex/" in item["url"] else 1,
                len(item["url"]),
            )
        )
        return candidates[: self.MAX_DETAIL_PAGES]

    def extract_detail_products(
        self,
        html: str,
        detail_url: str,
        source_name: str,
        link_text: str = "",
    ) -> list[dict]:
        text = self._html_to_text(html)
        release_date = self._extract_release_date(
            text + " " + link_text
        )

        if not release_date:
            return []

        special_official = (urlparse(detail_url).hostname or "").endswith(
            "30th.pokemon-card.com"
        )
        if special_official:
            return self._extract_special_products(
                html, text, detail_url, source_name, release_date
            )
        names = self._extract_names(text, link_text)
        products = []
        seen = set()

        for candidate in names:
            raw_name = str(candidate.get("name", ""))
            evidence_type = str(
                candidate.get("evidence_type", "")
            )
            name = self.validator.clean_name(raw_name)

            validation = self.validator.evaluate(
                name,
                source_url=detail_url,
                evidence_type=evidence_type,
                release_date=release_date,
            )

            if not validation["accepted"]:
                continue

            key = self._normalize_name(name)
            if not key or key in seen:
                continue

            seen.add(key)
            product = self._make_product(
                name=name,
                release_date=release_date,
                detail_url=detail_url,
                source_name=source_name,
            )
            product["product_kind"] = next(
                (kind for kind in PRODUCT_KINDS if kind in name), "その他"
            )
            product["image_url"] = urljoin(
                detail_url, self._meta_content(html, "og:image")
            )
            product["msrp"] = self._price(text)
            product["reference_price"] = product["msrp"]
            product["official_product_id"] = self._official_id(detail_url)
            product["candidate_confidence"] = (
                validation["confidence"]
            )
            product["candidate_reasons"] = (
                validation["reasons"]
            )
            products.append(product)

        return products

    def _extract_special_products(
        self, html: str, text: str, detail_url: str, source_name: str,
        fallback_date: str,
    ) -> list[dict]:
        price_then_date = re.compile(
            r"商品名\s+(?P<name>.*?)\s+希望小売価格\s+"
            r"(?P<price>\d[\d,]*)円.*?発売日\s+"
            r"(?P<year>20\d{2})年(?P<month>\d{1,2})月(?P<day>\d{1,2})日",
            re.DOTALL,
        )
        date_then_price = re.compile(
            r"商品名\s+(?P<name>.*?)\s+発売日\s+"
            r"(?P<year>20\d{2})年(?P<month>\d{1,2})月(?P<day>\d{1,2})日"
            r"(?:(?!商品名).)*?"
            r"希望小売価格\s+(?P<price>\d[\d,]*)円",
            re.DOTALL,
        )
        matches = sorted(
            [*price_then_date.finditer(text), *date_then_price.finditer(text)],
            key=lambda match: match.start(),
        )
        if not matches:
            title = re.split(r"[｜|]", self._meta_content(html, "og:title"), maxsplit=1)[0]
            matches_data = [(title, None, fallback_date)] if title and fallback_date else []
        else:
            matches_data = []
            for match in matches:
                try:
                    release = (
                        f"{int(match.group('year')):04d}-"
                        f"{int(match.group('month')):02d}-"
                        f"{int(match.group('day')):02d}"
                    )
                except ValueError:
                    continue
                matches_data.append((match.group("name"), int(match.group("price").replace(",", "")), release))
        image_url = urljoin(detail_url, self._meta_content(html, "og:image"))
        application = self._special_application(html, text, detail_url)
        products = []
        for raw_name, price, release_date in matches_data:
            name = re.sub(r"\s+", " ", raw_name).strip()
            name = re.sub(r"^ポケモンカードゲーム\s+MEGA\s*", "", name)
            name = re.sub(r"\s+([「『])", r"\1", name)
            if name.startswith(("「", "『")) and name.endswith(("」", "』")):
                name = name[1:-1].strip()
            if not name:
                continue
            product = self._make_product(name, release_date, detail_url, source_name)
            official_id = self._official_id(detail_url)
            if len(matches_data) > 1:
                suffix = hashlib.sha256(self._normalize_name(name).encode("utf-8")).hexdigest()[:8]
                official_id = f"{official_id}-{suffix}"
            product.update({
                "product_kind": next((kind for kind in PRODUCT_KINDS if kind in name), "カード入り商品"),
                "image_url": image_url,
                "msrp": price,
                "reference_price": price,
                "official_product_id": official_id,
                "candidate_confidence": 1.0,
                "candidate_reasons": ["ポケモンカード30周年公式の商品情報欄"],
            })
            product.update(application)
            products.append(product)
        return products

    @staticmethod
    def _special_application(html: str, text: str, detail_url: str) -> dict:
        match = re.search(
            r"抽選応募受け付け期間\s+(20\d{2})年(\d{1,2})月(\d{1,2})日.*?"
            r"(\d{1,2}):(\d{2}).*?[～〜]\s*(20\d{2})年(\d{1,2})月(\d{1,2})日.*?"
            r"(\d{1,2}):(\d{2})",
            text,
            re.DOTALL,
        )
        if not match:
            return {}
        values = [int(value) for value in match.groups()]
        start = f"{values[0]:04d}-{values[1]:02d}-{values[2]:02d}T{values[3]:02d}:{values[4]:02d}:00+09:00"
        end = f"{values[5]:04d}-{values[6]:02d}-{values[7]:02d}T{values[8]:02d}:{values[9]:02d}:00+09:00"
        application_url = ""
        for href in re.findall(r'href=["\']([^"\']+)["\']', html, re.IGNORECASE):
            candidate = urljoin(detail_url, unescape(href))
            if (urlparse(candidate).hostname or "").endswith("pokemoncenter-online.com"):
                application_url = candidate
                break
        return {
            "application_start_at": start,
            "application_end_at": end,
            "application_url": application_url,
            "application_method": "Web抽選",
            "application_status": "抽選受付",
        }

    def _looks_like_product_link(
        self,
        url: str,
        text: str,
    ) -> bool:
        lowered = text.lower()

        has_product_word = any(
            kind.lower() in lowered
            for kind in PRODUCT_KINDS
        )
        has_release_word = (
            "発売" in text
            or DATE_PATTERN.search(text) is not None
        )

        parsed = urlparse(url)
        path = parsed.path.lower()
        looks_like_special_page = (
            path.startswith("/ex/")
            or "/products/" in path
            or "/product/" in path
            or "/info/" in path
        )

        if parsed.netloc.endswith("30th.pokemon-card.com") and "/product/" in path:
            return has_release_word

        if "/info/" in path and not has_product_word:
            return False

        return (
            (has_product_word and has_release_word)
            or (
                path.startswith("/ex/")
                and has_release_word
            )
        )

    def _extract_names(
        self,
        page_text: str,
        link_text: str,
    ) -> list[dict]:
        combined = f"{link_text}\n{page_text}"
        names: list[dict] = []

        for match in QUOTED_NAME_PATTERN.finditer(
            combined
        ):
            kind = match.group("kind").strip()
            name = match.group("name").strip()
            names.append(
                {
                    "name": f"{kind}「{name}」",
                    "evidence_type": "product_info",
                }
            )

        for match in STARTER_NAME_PATTERN.finditer(
            combined
        ):
            value = re.sub(
                r"\s+",
                " ",
                match.group(1),
            ).strip(" 、。！!")
            names.append(
                {
                    "name": value,
                    "evidence_type": "img_alt",
                }
            )

        block_pattern = re.compile(
            r"(強化拡張パック|拡張パック|ブースターパック|"
            r"ハイクラスパック|プレミアムデッキセット|"
            r"構築デッキ|スターターセットex|"
            r"スターターセット|スタートデッキ|"
            r"スターターデッキ)"
            r"\s*[「『]?\s*"
            r"([^」』\n]{2,80})"
        )

        for match in block_pattern.finditer(
            combined
        ):
            kind = match.group(1).strip()
            raw_name = match.group(2).strip()

            raw_name = re.split(
                r"希望小売価格|内容物|発売日|"
                r"収録カード|応募期間|"
                r"が、?\d{1,2}月\d{1,2}日",
                raw_name,
                maxsplit=1,
            )[0].strip(" 、。！!-/")

            if not raw_name:
                continue

            if raw_name.startswith("「"):
                value = f"{kind}{raw_name}"
            elif kind == "スターターセットex":
                value = f"{kind} {raw_name}"
            else:
                value = f"{kind}「{raw_name}」"

            names.append(
                {
                    "name": value[:120],
                    "evidence_type": "product_info",
                }
            )

        if "スターターセットex3種" in combined:
            for starter in (
                "スターターセットex イーブイex",
                "スターターセットex ゾロア＆ゾロアークex",
                "スターターセットex ニャオハ＆マスカーニャex",
            ):
                if (
                    starter in combined
                    or starter.replace("＆", "&") in combined
                ):
                    names.append(
                        {
                            "name": starter,
                            "evidence_type": "img_alt",
                        }
                    )

        return self._clean_names(names)

    def _clean_names(
        self,
        names: list[dict],
    ) -> list[dict]:
        cleaned = []
        seen = set()

        for item in names:
            name = re.sub(
                r"\s+",
                " ",
                str(item.get("name", "")),
            ).strip()

            name = re.sub(
                r"(が、?.*?発売.*)$",
                "",
                name,
            ).strip(" 、。！!")

            if len(name) < 4 or len(name) > 120:
                continue

            if (
                "収録カード" in name
                or "キャンペーン" in name
            ):
                continue

            if re.search(
                r"スターターセットex\s*3種$",
                name,
            ):
                continue

            normalized = self._normalize_name(name)
            if normalized in seen:
                continue

            seen.add(normalized)
            cleaned.append(
                {
                    "name": name,
                    "evidence_type": item.get(
                        "evidence_type",
                        "",
                    ),
                }
            )

        return cleaned

    def _extract_release_date(self, text: str) -> str:
        explicit = re.search(
            r"発売日\s*[:：]\s*"
            r"(?P<year>\d{4})年"
            r"(?P<month>\d{1,2})月"
            r"(?P<day>\d{1,2})日",
            text,
        )
        match = explicit or DATE_PATTERN.search(text)

        if not match:
            return ""

        today = date.today()

        try:
            year = (
                int(match.group("year"))
                if match.group("year")
                else today.year
            )
            month = int(match.group("month"))
            day = int(match.group("day"))
            candidate = date(year, month, day)
        except (TypeError, ValueError):
            return ""

        if not match.group("year"):
            if candidate < today - timedelta(days=120):
                try:
                    candidate = date(
                        today.year + 1,
                        month,
                        day,
                    )
                except ValueError:
                    return ""

        return candidate.isoformat()

    def _make_product(
        self,
        name: str,
        release_date: str,
        detail_url: str,
        source_name: str,
    ) -> dict:
        product_id = hashlib.sha256(
            (
                "pokemon-card.com|"
                f"{self._normalize_name(name)}|"
                f"{release_date}|{detail_url}"
            ).encode("utf-8")
        ).hexdigest()[:20]

        return {
            "id": f"pokemon_official_{product_id}",
            "tcg_key": "pokemon",
            "tcg": "ポケモンカード",
            "name": name,
            "release_date": release_date,
            "status": "発売予定",
            "favorite": False,
            "reserved": False,
            "source_type": "pokemon_official_detail",
            "official_url": detail_url,
            "manufacturer_official": True,
            "information_type": "PRODUCT",
            "sites": [
                {
                    "site_key": "pokemon_official",
                    "name": source_name or "ポケモンカード公式",
                    "status": "公式商品ページを確認",
                    "url": detail_url,
                    "notice": (
                        "公式トップから商品ページをたどり、"
                        "商品名と発売日をHTMLから取得しました。"
                    ),
                }
            ],
        }

    @staticmethod
    def _official_id(url: str) -> str:
        parsed = urlparse(url)
        parts = [part for part in parsed.path.split("/") if part]
        value = parts[-1].casefold() if parts else ""
        return f"{value}-{parsed.fragment.casefold()}" if parsed.fragment else value

    @staticmethod
    def _price(value: str) -> int | None:
        match = re.search(r"(\d[\d,]*)\s*円", value)
        return int(match.group(1).replace(",", "")) if match else None

    @staticmethod
    def _meta_content(html: str, property_name: str) -> str:
        for pattern in (
            rf'<meta[^>]+property=["\']{re.escape(property_name)}["\'][^>]+content=["\']([^"\']+)',
            rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']{re.escape(property_name)}["\']',
        ):
            match = re.search(pattern, html, re.IGNORECASE)
            if match:
                return unescape(match.group(1)).strip()
        return ""

    @staticmethod
    def _html_to_text(html: str) -> str:
        alt_texts = re.findall(
            r"<img[^>]+alt=[\"']([^\"']+)[\"'][^>]*>",
            html,
            flags=re.IGNORECASE,
        )

        html = re.sub(
            r"<script[^>]*>.*?</script>",
            " ",
            html,
            flags=re.IGNORECASE | re.DOTALL,
        )
        html = re.sub(
            r"<style[^>]*>.*?</style>",
            " ",
            html,
            flags=re.IGNORECASE | re.DOTALL,
        )
        html = re.sub(
            r"<(br|p|li|h1|h2|h3|h4|div|section)[^>]*>",
            "\n",
            html,
            flags=re.IGNORECASE,
        )
        text = re.sub(r"<[^>]+>", " ", html)
        text = unescape(text)
        text = "\n".join([*alt_texts, text])
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n+", "\n", text)
        return text.strip()

    @staticmethod
    def _normalize_name(name: str) -> str:
        return re.sub(
            r"[\s「」『』・･_\-&＆]",
            "",
            name,
        ).lower()
