from __future__ import annotations

import json
import re
import unicodedata
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

from core.application_period import ApplicationPeriodParser


APPLICATION_TERMS = re.compile(
    r"抽選販売|事前抽選|予約受付|応募受付|申し込み|申込受付|受付期間|"
    r"販売方法|購入権|購入抽選|店頭抽選|Web抽選|オンライン抽選|先着|受注|販売受付",
    re.I,
)
NEGATIVE_TERMS = re.compile(
    r"買取|デッキレシピ|大会(?:参加|情報|結果)?|対戦会|イベント入場|"
    r"プレゼント(?:企画|キャンペーン)|景品抽選|サイン会|福袋|"
    r"シングルカード|スリーブ|プレイマット|デッキケース|アクセサリー",
    re.I,
)
DATE_TERMS = re.compile(
    r"(?:20\d{2}[年/.-])?\d{1,2}[月/.-]\d{1,2}日?(?:\s*\d{1,2}[:：]\d{2})?"
)
DISCOVERY_PATH_TERMS = re.compile(
    r"news|notice|campaign|lottery|entry|apply|reserve|reservation|product|shop|store|"
    r"抽選|予約|応募|販売|商品|店舗|お知らせ|ニュース",
    re.I,
)
FORM_HOSTS = {
    "forms.gle", "docs.google.com", "form.run", "formok.com", "select-type.com",
    "airrsv.net", "eventregist.com", "livepocket.jp",
}

TCG_PATTERNS: tuple[tuple[str, re.Pattern[str], tuple[re.Pattern[str], ...]], ...] = (
    ("pokemon", re.compile(r"ポケモンカード(?:ゲーム)?|ポケカ|Pok[eé]mon\s+Card", re.I), (re.compile(r"\bSV\d+[A-Z]?\b", re.I),)),
    ("onepiece", re.compile(r"ONE\s*PIECE\s*(?:CARD\s*GAME|カード)|ワンピースカード", re.I), (re.compile(r"\b(?:OP|EB|PRB|ST)-?\d{2,3}\b", re.I),)),
    ("dragon_ball_fusion_world", re.compile(r"FUSION\s*WORLD|フュージョンワールド|DBSCG\s*FW|DBFW", re.I), (re.compile(r"\b(?:FB|FS|SB)\d{2}\b", re.I),)),
    ("yugioh", re.compile(r"遊戯王\s*OCG|Yu-?Gi-?Oh!?\s*OCG", re.I), (re.compile(r"\b(?:QCC|DUAD|ALIN|SUDA)-?[A-Z0-9]*\b", re.I),)),
    ("gundam", re.compile(r"ガンダムカードゲーム|GUNDAM\s*CARD\s*GAME", re.I), (re.compile(r"\bGD\d{2}\b", re.I),)),
    ("union_arena", re.compile(r"UNION\s*ARENA|ユニオンアリーナ|ユニアリ", re.I), (re.compile(r"\bUA\d{2}(?:BT|ST|EX)\b", re.I),)),
    ("duelmasters", re.compile(r"デュエル[・\s-]*マスターズ|デュエマ|DUEL\s*MASTERS", re.I), (re.compile(r"\bDM\d{2}-[A-Z0-9]+\b", re.I),)),
    ("weiss", re.compile(r"ヴァイスシュヴァルツ|WEISS\s*SCHWARZ", re.I), (re.compile(r"\bW[S]?\d{2}\b", re.I),)),
    ("mtg", re.compile(r"マジック[：:・\s]*ザ[・\s]*ギャザリング|MAGIC:\s*THE\s*GATHERING|\bMTG\b", re.I), ()),
)


def canonical_url(value: object) -> str:
    try:
        parsed = urlsplit(str(value or "").strip())
        port = parsed.port
    except ValueError:
        return ""
    if parsed.scheme.casefold() != "https" or not parsed.hostname:
        return ""
    host = parsed.hostname.casefold()
    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    query = "&".join(
        part for part in parsed.query.split("&")
        if part and not part.casefold().startswith(("utm_", "fbclid=", "gclid="))
    )
    netloc = host if port in (None, 443) else f"{host}:{port}"
    return urlunsplit(("https", netloc, path, query, ""))


class _SemanticParser(HTMLParser):
    TEXT_TAGS = {"title", "h1", "h2", "h3", "article", "main", "time", "dt", "dd", "li", "td", "th", "p", "button"}

    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.parts: list[str] = []
        self.links: list[dict[str, str]] = []
        self.meta: dict[str, str] = {}
        self._active_tags: list[str] = []
        self._href = ""
        self._link_parts: list[str] = []
        self._json_ld = False
        self._json_parts: list[str] = []
        self._xml_link_tag = ""
        self._xml_link_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.casefold()
        values = {str(key).casefold(): str(value or "") for key, value in attrs}
        self._active_tags.append(tag)
        if tag == "a":
            self._href = urljoin(self.base_url, values.get("href", ""))
            self._link_parts = [values.get("title", ""), values.get("aria-label", "")]
        elif tag == "img" and self._href:
            self._link_parts.append(values.get("alt", ""))
        elif tag == "meta":
            key = values.get("property") or values.get("name")
            if key and values.get("content"):
                self.meta[key.casefold()] = values["content"][:1000]
        elif tag == "link" and values.get("rel", "").casefold() in {"canonical", "alternate"}:
            self.links.append({"url": urljoin(self.base_url, values.get("href", "")), "text": values.get("rel", "")})
        elif tag == "script" and "ld+json" in values.get("type", "").casefold():
            self._json_ld = True
            self._json_parts = []
        elif tag == "loc" or (tag == "link" and not values.get("href")):
            self._xml_link_tag = tag
            self._xml_link_parts = []

    def handle_data(self, data: str) -> None:
        clean = re.sub(r"\s+", " ", data).strip()
        if not clean:
            return
        if self._json_ld:
            self._json_parts.append(clean)
        if self._xml_link_tag:
            self._xml_link_parts.append(clean)
        if self._href:
            self._link_parts.append(clean)
        if any(tag in self.TEXT_TAGS for tag in self._active_tags[-4:]):
            self.parts.append(clean)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag == "a" and self._href:
            self.links.append({"url": self._href, "text": " ".join(self._link_parts).strip()[:1000]})
            self._href = ""
            self._link_parts = []
        elif tag == "script" and self._json_ld:
            raw = " ".join(self._json_parts)
            try:
                payload = json.loads(raw)
                self.parts.append(json.dumps(payload, ensure_ascii=False)[:20_000])
            except (ValueError, TypeError):
                pass
            self._json_ld = False
            self._json_parts = []
        elif tag == self._xml_link_tag:
            value = "".join(self._xml_link_parts).strip()
            if value.startswith("https://"):
                self.links.append({"url": value, "text": tag})
            self._xml_link_tag = ""
            self._xml_link_parts = []
        for index in range(len(self._active_tags) - 1, -1, -1):
            if self._active_tags[index] == tag:
                del self._active_tags[index]
                break


class GenericOfficialApplicationParser:
    """Conservative fallback used only after dedicated and structured parsers."""

    def parse(self, html: str, source_url: str, *, tcg_hint: list[str] | None = None) -> dict[str, Any]:
        parser = _SemanticParser(source_url)
        parser.feed(str(html or "")[:3_000_000])
        meta_text = " ".join(parser.meta.values())
        text = unicodedata.normalize("NFKC", " ".join([*parser.parts, meta_text]))
        text = re.sub(r"\s+", " ", text).strip()[:200_000]
        tcg = self.classify_tcg(text, source_url, hints=tcg_hint)
        relevance = self.relevance_score(text, tcg_confidence=tcg["confidence"], links=parser.links)
        period = ApplicationPeriodParser.parse(text, release_date="")
        application_links = self._application_links(parser.links)
        product = self.product_identity(text, parser.meta)
        negative = bool(NEGATIVE_TERMS.search(text))
        path = (urlsplit(source_url).path or "/").rstrip("/").casefold()
        index_like = path in {"", "/news", "/notice", "/topics", "/shop", "/store", "/products", "/product"}
        is_application = bool(
            relevance["score"] >= 0.7
            and tcg["key"] != "other"
            and APPLICATION_TERMS.search(text)
            and not negative
            and not index_like
            and (product["name"] or product["code"])
        )
        return {
            "source_url": canonical_url(source_url),
            "canonical_url": canonical_url(parser.meta.get("og:url") or source_url),
            "title": str(parser.meta.get("og:title") or product.get("title") or "")[:300],
            "text_excerpt": text[:1000],
            "tcg_key": tcg["key"],
            "tcg_confidence": tcg["confidence"],
            "tcg_evidence": tcg["evidence"],
            "product_name": product["name"],
            "product_code": product["code"],
            "application_relevance": relevance["score"],
            "relevance_reasons": relevance["reasons"],
            "is_application": is_application,
            "application_type": self._application_type(text),
            "application_url": application_links[0]["url"] if application_links else canonical_url(source_url),
            "application_links": application_links,
            "external_forms": [item for item in application_links if item["external_form"]],
            "period": period,
            "discovery_links": self.discovery_links(parser.links, source_url),
            "negative_match": negative,
            "page_kind": "index" if index_like else "detail",
            "parser_strategy": "generic_official",
        }

    @staticmethod
    def classify_tcg(text: str, url: str = "", *, hints: list[str] | None = None) -> dict[str, Any]:
        scores: dict[str, float] = {}
        evidence: dict[str, list[str]] = {}
        combined = f"{text} {url}"
        for key, title_pattern, code_patterns in TCG_PATTERNS:
            reasons = []
            score = 0.0
            if title_pattern.search(combined):
                score += 0.75
                reasons.append("title_or_text")
            if any(pattern.search(combined) for pattern in code_patterns):
                score += 0.2
                reasons.append("product_code")
            if key in set(hints or []):
                score += 0.15
                reasons.append("seed_hint")
            if score:
                scores[key] = min(1.0, score)
                evidence[key] = reasons
        if not scores:
            return {"key": "other", "confidence": 0.0, "evidence": []}
        ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        if len(ordered) > 1 and ordered[0][1] - ordered[1][1] < 0.2:
            return {"key": "other", "confidence": 0.0, "evidence": ["ambiguous_tcg"]}
        key, score = ordered[0]
        return {"key": key, "confidence": round(score, 3), "evidence": evidence[key]}

    @staticmethod
    def relevance_score(text: str, *, tcg_confidence: float, links: list[dict[str, str]]) -> dict[str, Any]:
        score = 0.0
        reasons = []
        if APPLICATION_TERMS.search(text):
            score += 0.35
            reasons.append("application_terms")
        if tcg_confidence >= 0.7:
            score += 0.2
            reasons.append("tcg")
        if DATE_TERMS.search(text):
            score += 0.15
            reasons.append("date")
        if any(APPLICATION_TERMS.search(str(item.get("text", ""))) for item in links):
            score += 0.15
            reasons.append("application_link")
        if re.search(r"支店|店舗|店頭|オンライン|WEB|受取|購入条件|会員", text, re.I):
            score += 0.1
            reasons.append("sales_context")
        if NEGATIVE_TERMS.search(text):
            score -= 0.5
            reasons.append("negative_context")
        return {"score": round(max(0.0, min(1.0, score)), 3), "reasons": reasons}

    @staticmethod
    def product_identity(text: str, meta: dict[str, str] | None = None) -> dict[str, str]:
        title = str((meta or {}).get("og:title") or "")
        code_match = re.search(
            r"\b(?:(?:OP|EB|PRB|ST|FB|FS|SB)-?\d{2,3}|UA\d{2}(?:BT|ST|EX)-?\d{1,3}|DM\d{2}-[A-Z0-9]{2,8})\b",
            text,
            re.I,
        )
        quoted = re.search(r"[「『](.{2,120}?)[」』]", text)
        name = quoted.group(1).strip() if quoted else title.strip()
        code = code_match.group(0).upper() if code_match else ""
        compact = re.fullmatch(r"(OP|EB|PRB|ST|FB|FS|SB)(\d{2,3})", code)
        if compact:
            code = f"{compact.group(1)}-{compact.group(2)}"
        return {"name": name[:240], "code": code, "title": title}

    @staticmethod
    def discovery_links(links: list[dict[str, str]], source_url: str) -> list[dict[str, str]]:
        output = []
        seen = set()
        source_host = (urlsplit(source_url).hostname or "").casefold()
        for item in links:
            url = canonical_url(item.get("url"))
            text = re.sub(r"\s+", " ", str(item.get("text", ""))).strip()
            if not url or url in seen or not DISCOVERY_PATH_TERMS.search(f"{url} {text}"):
                continue
            seen.add(url)
            host = (urlsplit(url).hostname or "").casefold()
            output.append({"url": url, "text": text[:300], "same_domain": host == source_host})
        return output[:100]

    @staticmethod
    def _application_links(links: list[dict[str, str]]) -> list[dict[str, Any]]:
        output = []
        seen = set()
        for item in links:
            url = canonical_url(item.get("url"))
            text = str(item.get("text", ""))
            if not url or url in seen or not APPLICATION_TERMS.search(f"{text} {url}"):
                continue
            seen.add(url)
            host = (urlsplit(url).hostname or "").casefold()
            output.append({"url": url, "text": text[:300], "external_form": host in FORM_HOSTS or "/forms/" in url})
        return output[:20]

    @staticmethod
    def _application_type(text: str) -> str:
        if re.search(r"抽選|応募|購入権", text):
            return "LOTTERY"
        if re.search(r"予約|受注", text):
            return "RESERVATION"
        if re.search(r"再販|再入荷", text):
            return "RESTOCK"
        return "SALE"
