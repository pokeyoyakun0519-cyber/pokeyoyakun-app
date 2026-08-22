from __future__ import annotations

import re
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit
from typing import Any

from core.application_filters import canonical_application_url


APPLICATION_TERMS = re.compile(r"抽選販売|事前抽選|予約受付|応募受付|販売方法")
TCG_TERMS = re.compile(
    r"ポケモンカード|ポケカ|ONE\s*PIECE\s*CARD\s*GAME|ワンピースカード|"
    r"FUSION\s*WORLD|DBSCG\s*FW|(?:OP|EB|PRB|FB|SB)-\d+",
    re.IGNORECASE,
)


class _LinkCollector(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.href = ""
        self.text: list[str] = []
        self.links: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.casefold() == "a":
            self.href = urljoin(self.base_url, str(dict(attrs).get("href") or ""))
            self.text = []

    def handle_data(self, data: str) -> None:
        if self.href and data.strip():
            self.text.append(data.strip())

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "a" and self.href:
            self.links.append((self.href, " ".join(self.text)))
            self.href = ""
            self.text = []


class SafeChainApplicationExtractor:
    """Parse only public official HTML and return evidence-first candidates."""

    chain = ""
    allowed_hosts: tuple[str, ...] = ()

    def extract_index(self, html: str, source_url: str, *, known_urls=()) -> dict[str, Any]:
        source_host = (urlsplit(source_url).hostname or "").casefold()
        if source_host not in self.allowed_hosts:
            raise ValueError("登録済み公式ドメイン以外は解析しません。")
        parser = _LinkCollector(source_url)
        parser.feed(html)
        known = {canonical_application_url(value) for value in known_urls}
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw_url, raw_text in parser.links:
            url = canonical_application_url(raw_url)
            host = (urlsplit(url).hostname or "").casefold()
            text = re.sub(r"\s+", " ", unescape(raw_text)).strip()
            if not url or host not in self.allowed_hosts or url in seen:
                continue
            seen.add(url)
            if not APPLICATION_TERMS.search(text) or not TCG_TERMS.search(text):
                continue
            rows.append({
                "chain": self.chain,
                "source_url": source_url,
                "application_url": url,
                "canonical_application_url": url,
                "evidence": [{"source_type": "OFFICIAL_STORE_PAGE", "source_url": source_url,
                              "text": text}],
                "verification_status": "candidate",
                "confirmed": False,
                "is_new_url": url not in known,
                "text": text,
            })
        return {"rows": rows, "new_urls": [row["application_url"] for row in rows if row["is_new_url"]]}


class BatorocoApplicationExtractor(SafeChainApplicationExtractor):
    chain, allowed_hosts = "batoroco", ("bato-loco.com", "www.bato-loco.com")


class PlaysApplicationExtractor(SafeChainApplicationExtractor):
    chain, allowed_hosts = "plays", ("www.preyz.com", "preyz.com")


class OtakarasoukoApplicationExtractor(SafeChainApplicationExtractor):
    chain, allowed_hosts = "otakarasouko", ("www.otakarasouko.com", "otakarasouko.com")


class CardboxApplicationExtractor(SafeChainApplicationExtractor):
    chain, allowed_hosts = "cardbox", ("www.cardbox.sc", "cardbox.sc")


class TsutayaApplicationExtractor(SafeChainApplicationExtractor):
    chain, allowed_hosts = "tsutaya", ("tsutaya.tsite.jp",)


class FuruichiApplicationExtractor(SafeChainApplicationExtractor):
    chain, allowed_hosts = "furuichi", ("www.furu1.net", "furu1.net")


class BookoffApplicationExtractor(SafeChainApplicationExtractor):
    chain, allowed_hosts = "bookoff", ("www.bookoff.co.jp", "bookoff.co.jp")


class BandaiOfficialShopApplicationExtractor(SafeChainApplicationExtractor):
    chain = "bandai_official_shop"
    allowed_hosts = ("bandainamco-am.co.jp", "www.bandainamco-am.co.jp")
