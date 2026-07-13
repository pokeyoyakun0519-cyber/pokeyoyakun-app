import hashlib
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
            product["candidate_confidence"] = (
                validation["confidence"]
            )
            product["candidate_reasons"] = (
                validation["reasons"]
            )
            products.append(product)

        return products

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

        path = urlparse(url).path.lower()
        looks_like_special_page = (
            path.startswith("/ex/")
            or "/products/" in path
            or "/info/" in path
        )

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
