import hashlib
import re
from datetime import date, timedelta
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urljoin
from core.product_candidate_validator import ProductCandidateValidator
from core.tcg_categories import display_name


PRODUCT_KEYWORDS = (
    "拡張パック",
    "強化拡張パック",
    "ブースターパック",
    "スターターセット",
    "スタートデッキ",
    "スターターデッキ",
    "構築デッキ",
    "プレミアムデッキセット",
    "デッキセット",
    "BOX",
    "ボックス",
)

IGNORE_KEYWORDS = (
    "大会",
    "イベント",
    "キャンペーン",
    "チャンピオンシップ",
    "プロモカード",
    "ルール",
    "カード検索",
)

DATE_PATTERN = re.compile(
    r"(?:(?P<year>\d{4})[./年]\s*)?"
    r"(?P<month>\d{1,2})[./月]\s*"
    r"(?P<day>\d{1,2})日?"
)

QUOTED_PRODUCT_PATTERN = re.compile(
    r"(?P<kind>"
    r"強化拡張パック|拡張パック|ブースターパック|"
    r"プレミアムデッキセット|構築デッキ|"
    r"スターターセットex|スターターセット|"
    r"スタートデッキ|スターターデッキ|デッキセット"
    r")\s*[「『](?P<name>[^」』]{2,80})[」』]"
)

PLAIN_PRODUCT_PATTERN = re.compile(
    r"(?P<kind>"
    r"強化拡張パック|拡張パック|ブースターパック|"
    r"プレミアムデッキセット|構築デッキ|"
    r"スターターセットex|スターターセット|"
    r"スタートデッキ|スターターデッキ|デッキセット"
    r")\s*(?P<name>[^\n。！!]{2,80})"
)


class _ContentParser(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.current_href = ""
        self.anchor_parts: list[str] = []
        self.entries: list[dict] = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)

        if tag.lower() == "a":
            self.current_href = urljoin(
                self.base_url,
                attrs_dict.get("href", ""),
            )
            self.anchor_parts = []

        if tag.lower() == "img":
            alt = str(attrs_dict.get("alt", "")).strip()
            if alt:
                self.entries.append(
                    {
                        "text": alt,
                        "url": self.current_href or self.base_url,
                    }
                )
                if self.current_href:
                    self.anchor_parts.append(alt)

    def handle_data(self, data):
        text = data.strip()
        if text and self.current_href:
            self.anchor_parts.append(text)

    def handle_endtag(self, tag):
        if tag.lower() == "a" and self.current_href:
            text = " ".join(self.anchor_parts).strip()
            if text:
                self.entries.append(
                    {
                        "text": text,
                        "url": self.current_href,
                    }
                )
            self.current_href = ""
            self.anchor_parts = []


class SourceProductExtractor:
    def __init__(self):
        self.validator = ProductCandidateValidator()

    def extract(
        self,
        html: str,
        source_url: str,
        source_name: str,
    ) -> list[dict]:
        parser = _ContentParser(source_url)
        parser.feed(html)

        entries = list(parser.entries)

        # JSON-LDや通常本文にしか出ない商品告知も拾う。
        plain_text = re.sub(
            r"<script[^>]*>.*?</script>",
            " ",
            html,
            flags=re.IGNORECASE | re.DOTALL,
        )
        plain_text = re.sub(
            r"<style[^>]*>.*?</style>",
            " ",
            plain_text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        plain_text = re.sub(r"<[^>]+>", " ", plain_text)
        plain_text = re.sub(r"\s+", " ", unescape(plain_text)).strip()

        for sentence in re.split(r"[。！？!\n]", plain_text):
            if any(keyword in sentence for keyword in PRODUCT_KEYWORDS):
                entries.append(
                    {
                        "text": sentence.strip(),
                        "url": source_url,
                    }
                )

        products = []
        seen = set()

        for entry in entries:
            product = self._parse_entry(
                entry.get("text", ""),
                entry.get("url", source_url),
                source_name,
            )
            if not product:
                continue

            key = (
                self._normalize_name(product["name"]),
                product["release_date"],
            )
            if key in seen:
                continue

            seen.add(key)
            products.append(product)

        return products[:30]

    def _parse_entry(
        self,
        raw_text: str,
        url: str,
        source_name: str,
    ) -> dict | None:
        text = re.sub(r"\s+", " ", unescape(raw_text)).strip()

        if len(text) < 4:
            return None

        if not any(keyword.lower() in text.lower() for keyword in PRODUCT_KEYWORDS):
            return None

        if any(keyword in text for keyword in IGNORE_KEYWORDS):
            return None

        date_match = DATE_PATTERN.search(text)
        if not date_match:
            return None

        release_date = self._resolve_date(date_match)
        if not release_date:
            return None

        name = self._extract_name(text)
        if not name:
            return None

        name = self.validator.clean_name(name)
        validation = self.validator.evaluate(
            name,
            source_url=url,
            evidence_type="body_text",
            release_date=release_date,
        )
        if not validation["accepted"]:
            return None

        product_id = hashlib.sha256(
            f"{source_name}|{name}|{release_date}".encode("utf-8")
        ).hexdigest()[:20]

        return {
            "id": f"source_{product_id}",
            "tcg_key": "other",
            "tcg": display_name("other"),
            "name": name,
            "release_date": release_date,
            "status": "発売予定",
            "favorite": False,
            "reserved": False,
            "source_type": "official_source",
            "candidate_confidence": validation["confidence"],
            "candidate_reasons": validation["reasons"],
            "sites": [
                {
                    "site_key": "official_source",
                    "name": source_name or "公式情報ソース",
                    "status": "公式発表を確認",
                    "url": url,
                    "notice": (
                        "公式サイトから自動取得した商品情報です。"
                        "予約状況はリンク先で確認してください。"
                    ),
                }
            ],
        }

    def _extract_name(self, text: str) -> str:
        quoted = QUOTED_PRODUCT_PATTERN.search(text)
        if quoted:
            kind = quoted.group("kind").strip()
            name = quoted.group("name").strip()
            suffix = ""

            after = text[quoted.end():quoted.end() + 20]
            count_match = re.search(r"(\d+)種", after)
            if count_match:
                suffix = f" {count_match.group(1)}種"

            return f"{kind}「{name}」{suffix}"[:120]

        plain = PLAIN_PRODUCT_PATTERN.search(text)
        if plain:
            kind = plain.group("kind").strip()
            name = plain.group("name").strip()

            name = re.split(
                r"\d{1,2}月\d{1,2}日|発売|登場|収録カード",
                name,
                maxsplit=1,
            )[0].strip(" 、。！!-/")

            if name and name != kind:
                return f"{kind} {name}"[:120]

        # バナーaltのように商品種別より商品名が前にあるケース。
        date_part = DATE_PATTERN.search(text)
        before_date = text[:date_part.start()] if date_part else text
        before_date = re.sub(
            r"(登場|発売|好評発売中)[。！!、\s]*$",
            "",
            before_date,
        ).strip(" 、。！!")

        for keyword in PRODUCT_KEYWORDS:
            if keyword in before_date:
                return before_date[-120:]

        return ""

    @staticmethod
    def _normalize_name(name: str) -> str:
        return re.sub(r"[\s「」『』・･_\-]", "", name).lower()

    @staticmethod
    def _resolve_date(match: re.Match) -> str:
        today = date.today()

        try:
            year = int(match.group("year")) if match.group("year") else today.year
            month = int(match.group("month"))
            day = int(match.group("day"))
            candidate = date(year, month, day)
        except (TypeError, ValueError):
            return ""

        if not match.group("year"):
            # 年末に翌年の商品が掲載された場合を考慮。
            if candidate < today - timedelta(days=120):
                try:
                    candidate = date(today.year + 1, month, day)
                except ValueError:
                    return ""

        return candidate.isoformat()
