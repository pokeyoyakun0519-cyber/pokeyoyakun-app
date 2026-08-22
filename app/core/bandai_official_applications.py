from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
from typing import Any, Callable
from urllib.parse import urljoin, urlsplit

from core.application_filters import canonical_application_url
from core.application_filters import region_for_prefecture
from core.application_site import normalize_application_site
from core.tcg_categories import display_name


OFFICIAL_SHOP_INDEXES = {
    "onepiece": "https://bandainamco-am.co.jp/official_shop/onepiece-cardgame/index.html",
    "dragon_ball_fusion_world": "https://bandainamco-am.co.jp/official_shop/dbs-cardgame/index.html",
}
OFFICIAL_APPLICATION_CATEGORIES = {
    "onepiece": "https://parks2.bandainamco-am.co.jp/category/ECCL00000054",
    "dragon_ball_fusion_world": "https://parks2.bandainamco-am.co.jp/category/ECCL00000052",
}
_OFFICIAL_HOSTS = {
    "bandainamco-am.co.jp",
    "www.bandainamco-am.co.jp",
    "parks2.bandainamco-am.co.jp",
}
_APPLICATION_HOST = "parks2.bandainamco-am.co.jp"


class _DocumentParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.parts: list[str] = []
        self.links: list[dict[str, str]] = []
        self._href = ""
        self._link_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        values = dict(attrs)
        if tag.casefold() == "a":
            self._href = urljoin(self.base_url, str(values.get("href") or ""))
            self._link_parts = []
        if tag.casefold() == "img":
            alt = str(values.get("alt") or "").strip()
            if alt:
                self.parts.append(alt)
                if self._href:
                    self._link_parts.append(alt)

    def handle_data(self, data: str) -> None:
        value = re.sub(r"\s+", " ", unescape(data)).strip()
        if not value:
            return
        self.parts.append(value)
        if self._href:
            self._link_parts.append(value)

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "a" and self._href:
            self.links.append({
                "url": canonical_application_url(self._href),
                "text": " ".join(self._link_parts).strip(),
            })
            self._href = ""
            self._link_parts = []

    @property
    def text(self) -> str:
        return "\n".join(self.parts)


def normalize_bandai_tcg(text: object) -> str:
    """Classify Bandai application wording without treating a prefix alone as proof."""
    value = unicodedata.normalize("NFKC", str(text or ""))
    folded = value.casefold()
    if re.search(
        r"one\s*piece\s*(?:カードゲーム|card\s*game)|"
        r"ワンピースカード(?:ゲーム)?|ワンピカード",
        folded,
        re.IGNORECASE,
    ):
        return "onepiece"
    if re.search(
        r"dragon\s*ball\s*super\s*card\s*game\s*fusion\s*world|"
        r"fusion\s*world|dbscg\s*fw|dbfw|フュージョンワールド",
        folded,
        re.IGNORECASE,
    ):
        return "dragon_ball_fusion_world"
    # Product prefixes only reinforce an already named TCG; they never classify
    # an unrelated sentence on their own.
    if re.search(r"one\s*piece|ワンピ", folded, re.IGNORECASE) and re.search(
        r"(?:OP|EB|PRB|ST)-\d+", value, re.IGNORECASE
    ):
        return "onepiece"
    if (
        re.search(r"dragon\s*ball|ドラゴンボール|DBSCG", folded, re.IGNORECASE)
        and not re.search(r"masters|マスターズ", folded, re.IGNORECASE)
        and re.search(r"(?:FB|SB|FS)-?\d+", value, re.IGNORECASE)
    ):
        return "dragon_ball_fusion_world"
    return "other"


def _iso_datetime(value: str) -> str:
    match = re.search(
        r"(?P<year>20\d{2})\s*[年/]\s*(?P<month>\d{1,2})\s*[月/]\s*"
        r"(?P<day>\d{1,2})\s*日?\s*(?:\([^)]*\))?\s*"
        r"(?P<hour>\d{1,2})\s*[:時]\s*(?P<minute>\d{2})?",
        value,
    )
    if not match:
        return ""
    minute = int(match.group("minute") or 0)
    try:
        parsed = datetime(
            int(match.group("year")), int(match.group("month")),
            int(match.group("day")), int(match.group("hour")), minute,
        )
    except ValueError:
        return ""
    return parsed.isoformat(timespec="minutes") + "+09:00"


def parse_application_dates(
    text: object, *, reference_date: datetime | None = None
) -> dict[str, str]:
    value = unicodedata.normalize("NFKC", str(text or ""))
    labels = {
        "application_start_at": r"(?:申込|申し込み|応募|予約)(?:受付)?開始",
        "application_end_at": r"(?:申込|申し込み|応募|予約)(?:受付)?終了|締切",
        "result_announcement_at": r"当選発表|結果発表",
    }
    output: dict[str, str] = {}
    date_fragment = (
        r"20\d{2}\s*[年/]\s*\d{1,2}\s*[月/]\s*\d{1,2}\s*日?"
        r"\s*(?:\([^)]*\))?\s*\d{1,2}\s*[:時]\s*\d{0,2}"
    )
    for key, label in labels.items():
        match = re.search(rf"(?:{label})\s*[:：]?\s*({date_fragment})", value, re.I)
        if match:
            parsed = _iso_datetime(match.group(1))
            if parsed:
                output[key] = parsed
    if reference_date and (
        "application_start_at" not in output or "application_end_at" not in output
    ):
        period = re.search(
            r"(?:応募|申込|予約)(?:受付)?期間\s*[:：]?\s*"
            r"(?:(20\d{2})年)?\s*(\d{1,2})月(\d{1,2})日(?:\([^)]*\))?\s*"
            r"(\d{1,2})[:時](\d{2})?\s*[~～〜-]\s*"
            r"(?:(20\d{2})年)?\s*(\d{1,2})月(\d{1,2})日(?:\([^)]*\))?\s*"
            r"(\d{1,2})[:時](\d{2})?",
            value,
        )
        if period:
            start_year = int(period.group(1) or reference_date.year)
            end_year = int(period.group(6) or start_year)
            try:
                start = datetime(
                    start_year, int(period.group(2)), int(period.group(3)),
                    int(period.group(4)), int(period.group(5) or 0),
                )
                end = datetime(
                    end_year, int(period.group(7)), int(period.group(8)),
                    int(period.group(9)), int(period.group(10) or 0),
                )
                if end < start and not period.group(6):
                    end = end.replace(year=end.year + 1)
                output.setdefault(
                    "application_start_at", start.isoformat(timespec="minutes") + "+09:00"
                )
                output.setdefault(
                    "application_end_at", end.isoformat(timespec="minutes") + "+09:00"
                )
            except ValueError:
                pass
    if reference_date and "application_end_at" not in output:
        same_day = re.search(r"当日\s*(\d{1,2})時(?:\s*(\d{1,2})分)?まで", value)
        if same_day:
            try:
                end = reference_date.replace(
                    hour=int(same_day.group(1)), minute=int(same_day.group(2) or 0),
                    second=0, microsecond=0,
                )
                output["application_end_at"] = (
                    end.replace(tzinfo=None).isoformat(timespec="minutes") + "+09:00"
                )
            except ValueError:
                pass
    return output


_BRANCH_LOCATIONS = {
    "大阪梅田店": ("大阪府", "近畿"),
    "大阪心斎橋店": ("大阪府", "近畿"),
    "東京店": ("東京都", "関東"),
    "東京池袋店": ("東京都", "関東"),
    "東京新宿店": ("東京都", "関東"),
    "東京渋谷店": ("東京都", "関東"),
    "横浜店": ("神奈川県", "関東"),
    "イオンモール大日店": ("大阪府", "近畿"),
}
_PREFECTURE = re.compile(
    r"(北海道|東京都|京都府|大阪府|(?:青森|岩手|宮城|秋田|山形|福島|茨城|栃木|"
    r"群馬|埼玉|千葉|神奈川|新潟|富山|石川|福井|山梨|長野|岐阜|静岡|愛知|"
    r"三重|滋賀|兵庫|奈良|和歌山|鳥取|島根|岡山|広島|山口|徳島|香川|愛媛|"
    r"高知|福岡|佐賀|長崎|熊本|大分|宮崎|鹿児島|沖縄)県)"
)


class BandaiOfficialApplicationParser:
    """Parse public NAMCO Parks application pages into official evidence."""

    @classmethod
    def parse(cls, html: str, application_url: str) -> dict[str, Any] | None:
        url = canonical_application_url(application_url)
        host = (urlsplit(url).hostname or "").casefold()
        if host != _APPLICATION_HOST:
            return None
        parser = _DocumentParser(url)
        parser.feed(str(html or ""))
        text = parser.text
        tcg_key = normalize_bandai_tcg(text)
        dates = parse_application_dates(text)
        if tcg_key not in {"onepiece", "dragon_ball_fusion_world"}:
            return None
        if not dates.get("application_end_at") or not re.search(
            r"抽選申込|事前抽選|抽選販売", text
        ):
            return None

        product_match = re.search(
            r"商品名\s*[:：]\s*([^\n]+)", text
        ) or re.search(r"[『「]([^』」]+(?:\[(?:OP|ST|FB|SB|FS)-?\d+\]|【OP-\d+】))['』」]", text, re.I)
        product_name = re.sub(r"\s+", " ", product_match.group(1)).strip() if product_match else ""
        if not product_name:
            return None
        code_match = re.search(r"[\[【]((?:OP|EB|PRB|ST|FB|SB|FS)-?\d+)[\]】]", product_name, re.I)
        product_code = code_match.group(1).upper() if code_match else ""

        branch = ""
        for name in sorted(_BRANCH_LOCATIONS, key=len, reverse=True):
            if name in text:
                branch = name
                break
        if not branch:
            branch_match = re.search(r"[【＜]([^【＜＞】\n]{1,30}店)[】＞]", text)
            branch = branch_match.group(1).strip() if branch_match else ""
        prefecture, region = _BRANCH_LOCATIONS.get(branch, ("UNKNOWN", "UNKNOWN"))
        # An address printed in the official page outranks the bundled branch
        # map.  Do not infer a prefecture from a vague place name.
        address_section = re.search(r"店舗概要(.{0,500})", text, re.S)
        address_match = _PREFECTURE.search(address_section.group(1)) if address_section else None
        if address_match:
            prefecture = address_match.group(1)
            region = region_for_prefecture(prefecture)
        source_type = "OFFICIAL_SHOP_BRANCH"
        evidence_fields = {
            "product_name": product_name,
            "product_code": product_code,
            "tcg_key": tcg_key,
            "store_name": branch,
            "application_url": url,
            **dates,
            "sales_mode": "STORE",
            "prefecture": prefecture,
        }
        evidence = {
            "source_type": source_type,
            "source_url": url,
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "trust": 100,
            "verification_status": "confirmed",
            "extracted_fields": evidence_fields,
        }
        site = normalize_application_site({
            "site_key": "bandai_official_shop_" + hashlib.sha256(
                f"{branch}|{url}".encode("utf-8")
            ).hexdigest()[:12],
            "name": branch or "BANDAI CARD GAMES 公式ショップ",
            "branch": branch,
            "chain": "bandai_official_shop",
            "url": url,
            "application_url": url,
            "product_url": next((
                item["url"] for item in parser.links
                if normalize_bandai_tcg(item.get("text")) == tcg_key
            ), ""),
            "status": "抽選受付",
            "article_type": "lottery",
            "application_method": "ナムコパークスで事前抽選・公式店舗で購入",
            "application_conditions": "公式応募ページの注意事項を確認",
            "application_period": (
                f'{dates.get("application_start_at", "")} ～ '
                f'{dates.get("application_end_at", "")}'
            ),
            "result_date": dates.get("result_announcement_at", ""),
            "sales_mode": "STORE",
            "prefecture": prefecture,
            "region": region,
            "location_source": "official_shop_name",
            "source_type": source_type,
            "verification_status": "confirmed",
            "confirmed": True,
            "confidence": 1.0,
            "retailer_verified": True,
            "seller": "BANDAI NAMCO Amusement",
            "evidence": [evidence],
            "period_evidence": "公式応募ページの申込開始・申込終了",
            "tcg_key": tcg_key,
            "tcg": display_name(tcg_key),
            **dates,
        })
        return {
            "article_id": "bandai-" + hashlib.sha256(url.encode("utf-8")).hexdigest()[:16],
            "article_type": "lottery",
            "article_url": url,
            "source_id": "bandai_official_application",
            "source_name": "BANDAI公式ショップ応募ページ",
            "source_type": source_type,
            "product_name": product_name,
            "product_code": product_code,
            "tcg_key": tcg_key,
            "tcg": display_name(tcg_key),
            "store_name": branch,
            "verification_status": "confirmed",
            "confirmed": True,
            "application_evidence": True,
            "application_url": url,
            **dates,
            "sales_mode": "STORE",
            "prefecture": prefecture,
            "region": region,
            "evidence": [evidence],
            "hit": site,
        }


class BandaiOfficialApplicationMonitor:
    """Follow only official index -> official news -> official application links."""

    def __init__(self, fetch: Callable[[str], dict[str, Any]]) -> None:
        self.fetch = fetch
        self.diagnostics = {
            "index_fetched": 0, "news_fetched": 0, "application_fetched": 0,
            "candidate": 0, "confirmed": 0, "failed": 0, "duplicate": 0,
        }

    def scan(self, enabled_tcg_keys: set[str]) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        seen_news: set[str] = set()
        seen_landings: set[str] = set()
        seen_apps: set[str] = set()
        for tcg_key, index_url in OFFICIAL_SHOP_INDEXES.items():
            if tcg_key not in enabled_tcg_keys:
                continue
            index = self.fetch(index_url)
            if not index.get("ok"):
                self.diagnostics["failed"] += 1
                continue
            self.diagnostics["index_fetched"] += 1
            parser = _DocumentParser(index_url)
            parser.feed(str(index.get("html") or ""))
            news_urls = []
            for link in parser.links:
                url = link["url"]
                host = (urlsplit(url).hostname or "").casefold()
                if host in _OFFICIAL_HOSTS and "/news/important/" in url and url not in seen_news:
                    seen_news.add(url)
                    news_urls.append(url)
            for news_url in news_urls[:6]:
                news = self.fetch(news_url)
                if not news.get("ok"):
                    self.diagnostics["failed"] += 1
                    continue
                self.diagnostics["news_fetched"] += 1
                news_parser = _DocumentParser(news_url)
                news_parser.feed(str(news.get("html") or ""))
                links = [
                    *news_parser.links,
                    {"url": OFFICIAL_APPLICATION_CATEGORIES[tcg_key], "text": "公式応募一覧"},
                ]
                for link in links:
                    landing_url = link["url"]
                    if (urlsplit(landing_url).hostname or "").casefold() != _APPLICATION_HOST:
                        continue
                    if "/category/" not in landing_url or "ECCL" not in landing_url:
                        continue
                    if landing_url in seen_landings:
                        self.diagnostics["duplicate"] += 1
                        continue
                    seen_landings.add(landing_url)
                    landing = self.fetch(landing_url)
                    if not landing.get("ok"):
                        self.diagnostics["failed"] += 1
                        continue
                    landing_html = str(landing.get("html") or "")
                    landing_parser = _DocumentParser(landing_url)
                    landing_parser.feed(landing_html)
                    application_urls = [
                        value["url"] for value in landing_parser.links
                        if (urlsplit(value["url"]).hostname or "").casefold() == _APPLICATION_HOST
                        and value["url"].endswith(".html")
                        and "ECCL" in value["url"]
                        and re.search(r"抽選申込|事前抽選|抽選販売", value["text"])
                        and normalize_bandai_tcg(value["text"]) == tcg_key
                    ]
                    # Some news links already point to the individual product.
                    if landing_url.endswith(".html"):
                        application_urls.insert(0, landing_url)
                    for app_url in application_urls:
                        if app_url in seen_apps:
                            self.diagnostics["duplicate"] += 1
                            continue
                        seen_apps.add(app_url)
                        self.diagnostics["candidate"] += 1
                        if app_url == landing_url:
                            application = landing
                        else:
                            application = self.fetch(app_url)
                            if not application.get("ok"):
                                self.diagnostics["failed"] += 1
                                continue
                        self.diagnostics["application_fetched"] += 1
                        record = BandaiOfficialApplicationParser.parse(
                            str(application.get("html") or ""), app_url
                        )
                        if not record or record["tcg_key"] != tcg_key:
                            self.diagnostics["failed"] += 1
                            continue
                        self.diagnostics["confirmed"] += 1
                        records.append({"record": record, "hit": record["hit"]})
        return records
