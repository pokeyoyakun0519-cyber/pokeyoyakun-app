from __future__ import annotations

import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from html import unescape
from html.parser import HTMLParser
from typing import Any, Callable

from core.application_period import ApplicationPeriodParser
from core.application_site import normalize_application_site
from core.secure_https import build_https_opener


class _OfficialLinkParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.href = ""
        self.parts: list[str] = []
        self.links: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag.casefold() == "a":
            self.href = urllib.parse.urljoin(
                self.base_url, str(values.get("href") or "")
            )
            self.parts = [str(values.get("title") or "")]
        elif tag.casefold() == "img" and self.href:
            self.parts.append(str(values.get("alt") or ""))

    def handle_data(self, data: str) -> None:
        if self.href and data.strip():
            self.parts.append(data.strip())

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() != "a" or not self.href:
            return
        self.links.append({
            "url": self.href,
            "text": re.sub(r"\s+", " ", " ".join(self.parts)).strip(),
        })
        self.href = ""
        self.parts = []


class _OfficialApplicationAdapter:
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/124 Safari/537.36 PokeyoyaKun/1.25.0"
    )

    def __init__(self, fetcher: Callable[[str], str] | None = None) -> None:
        self.fetcher = fetcher or self._fetch
        self._cache: dict[str, str] = {}
        self.http_request_count = 0

    def fetch(self, url: str) -> str:
        if url in self._cache:
            return self._cache[url]
        html = self.fetcher(url)
        self._cache[url] = html
        self.http_request_count += 1
        return html

    def _fetch(self, url: str) -> str:
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "https" or parsed.port not in (None, 443):
            raise ValueError("HTTPS公式URL以外は取得しません。")
        request = urllib.request.Request(url, headers={
            "User-Agent": self.USER_AGENT,
            "Accept-Language": "ja,en-US;q=0.8,en;q=0.6",
            "Accept": "text/html,application/xhtml+xml",
        })
        with build_https_opener().open(request, timeout=20) as response:
            final = urllib.parse.urlsplit(response.geturl())
            if final.scheme != "https" or final.hostname != parsed.hostname:
                raise ValueError("公式ドメイン外へのリダイレクトを拒否しました。")
            raw = response.read(3_000_000)
            charset = response.headers.get_content_charset() or "utf-8"
        return raw.decode(charset, errors="replace")

    @staticmethod
    def parse_links(html: str, base_url: str) -> list[dict[str, str]]:
        parser = _OfficialLinkParser(base_url)
        parser.feed(html)
        output: list[dict[str, str]] = []
        seen: set[str] = set()
        for link in parser.links:
            url = str(link.get("url", ""))
            if url in seen:
                continue
            seen.add(url)
            output.append(link)
        return output

    @staticmethod
    def html_to_text(html: str) -> str:
        return re.sub(
            r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", html))
        ).strip()

    @staticmethod
    def product_code(*values: Any) -> str:
        match = re.search(
            r"\b(?:(OP|EB|ST|PRB)\s*[-‐‑‒–—ー]?\s*(\d{2,3})|"
            r"((?:UA|EX)\d{2}(?:BT|ST|DC)))\b",
            " ".join(str(value or "") for value in values),
            re.IGNORECASE,
        )
        if not match:
            return ""
        if match.group(3):
            return match.group(3).upper()
        return f"{match.group(1).upper()}-{match.group(2)}"

    @classmethod
    def matches_candidate(cls, candidate: dict[str, Any], text: str) -> bool:
        candidate_signature = cls._normalize(candidate.get("name", ""))
        text_signature = cls._normalize(text)
        if ("futuristicbox" in candidate_signature) != (
            "futuristicbox" in text_signature
        ):
            return False
        if ("プレミアムデッキ" in candidate_signature) != (
            "プレミアムデッキ" in text_signature
        ):
            return False
        expected_code = cls.product_code(
            candidate.get("product_code", ""), candidate.get("name", "")
        )
        actual_code = cls.product_code(text)
        if expected_code:
            return actual_code == expected_code
        normalized_text = cls._normalize(text)
        terms = [
            cls._normalize(term) for term in re.findall(
                r"[a-z0-9一-龠ァ-ヶ]{3,}",
                str(candidate.get("name", "")).casefold(),
            )
            if cls._normalize(term) not in {
                "ポケモンカードゲーム", "onepieceカードゲーム", "pieceカードゲーム",
                "one", "カードゲーム", "ゲーム", "ブースターパック",
            }
        ]
        return bool(terms) and sum(term in normalized_text for term in terms) >= min(2, len(terms))

    @staticmethod
    def _normalize(value: Any) -> str:
        return re.sub(r"[\s　「」『』【】・_-]", "", str(value)).casefold()


class MagiApplicationAdapter(_OfficialApplicationAdapter):
    INDEX_URL = "https://magi.camp/news"

    def search_candidate(
        self, candidate: dict[str, Any]
    ) -> tuple[list[dict[str, Any]], str]:
        if str(candidate.get("tcg_key", "")) != "pokemon":
            return [], "magi公式: 対象外"
        try:
            first_links = self.parse_links(self.fetch(self.INDEX_URL), self.INDEX_URL)
            page_urls = [
                link["url"] for link in first_links
                if re.fullmatch(r"https://magi\.camp/news\?page=[2-4]", link.get("url", ""))
            ]
            links = list(first_links)
            for page_url in page_urls:
                links.extend(self.parse_links(self.fetch(page_url), page_url))
        except (OSError, ValueError, urllib.error.URLError) as error:
            return [], f"magi公式: 取得失敗 ({error})"
        targets = [
            link for link in links
            if re.fullmatch(r"https://magi\.camp/news/\d+/web", link.get("url", ""))
            and re.search(r"抽選|予約|再販|再入荷", link.get("text", ""))
            and self.matches_candidate(candidate, link.get("text", ""))
        ][:4]
        hits: list[dict[str, Any]] = []
        for link in targets:
            try:
                text = self.html_to_text(self.fetch(link["url"]))
            except (OSError, ValueError, urllib.error.URLError):
                continue
            if not re.search(r"抽選|予約|再販|再入荷", text):
                continue
            hit = {
                "site_key": "magi_official",
                "name": "magi公式",
                "url": link["url"],
                "application_url": link["url"],
                "status": "抽選受付情報あり",
                "application_method": "Web / X連携条件",
                "result_mode": "direct_message",
                "regions": ["全国"],
                "retailer_verified": True,
                "seller": "magi",
                "confidence": 0.98,
                "verification_status": "candidate",
                "confirmed": False,
                "application_evidence": True,
                "notice": link.get("text", ""),
                "text": text,
                "source_type": "OFFICIAL_STORE",
                "source_evidence": [{
                    "source_type": "OFFICIAL_STORE",
                    "source_url": link["url"],
                }],
                "checked_at": datetime.now().isoformat(timespec="seconds"),
            }
            hit.update(self._extract_labeled_period(text))
            enriched = ApplicationPeriodParser().enrich_site(
                hit, text, release_date=str(candidate.get("release_date", ""))
            )
            normalized = normalize_application_site(enriched, product=candidate)
            period_verified = bool(
                normalized.get("application_start_at")
                or normalized.get("application_end_at")
            )
            normalized["verification_status"] = (
                "confirmed" if period_verified else "candidate"
            )
            normalized["confirmed"] = period_verified
            if not period_verified:
                normalized["status"] = "公式応募記事・期間要確認"
            hits.append(normalized)
        return hits, f"magi公式: {len(hits)}件"

    @staticmethod
    def _extract_labeled_period(text: str) -> dict[str, str]:
        segment_match = re.search(
            r"(?:キャンペーン参加期間|抽選参加期間|応募受付期間|受付期間)\s*[:：]"
            r"(?P<value>.*?)(?=当選発表|その他注意|応募方法|$)",
            text,
            re.DOTALL,
        )
        if not segment_match:
            return {}
        segment = segment_match.group("value")
        values: list[str] = []
        for match in re.finditer(
            r"(20\d{2})年\s*(\d{1,2})月\s*(\d{1,2})日"
            r"(?:[^0-9]{0,12}(\d{1,2}):(\d{2}))?",
            segment,
        ):
            year, month, day, hour, minute = match.groups()
            try:
                parsed = datetime(
                    int(year), int(month), int(day), int(hour or 0), int(minute or 0)
                )
            except ValueError:
                continue
            values.append(parsed.isoformat() + "+09:00")
        if not values:
            return {}
        if segment.lstrip().startswith(("～", "〜", "~")):
            return {"application_end_at": values[0]}
        result = {"application_start_at": values[0]}
        if len(values) >= 2:
            result["application_end_at"] = values[1]
        return result


class PremiumBandaiApplicationAdapter(_OfficialApplicationAdapter):
    INDEX_URL = "https://p-bandai.jp/carddas/a0018/list-pa20-n0/"
    UNION_ARENA_INDEX_URL = "https://p-bandai.jp/carddas/a0015/list-da10-n0/"
    DRAGON_BALL_FUSION_WORLD_INDEX_URL = (
        "https://p-bandai.jp/carddas/a0008/b0003/dbscgfw/list-da20-n0/"
    )

    def search_candidate(
        self, candidate: dict[str, Any]
    ) -> tuple[list[dict[str, Any]], str]:
        tcg_key = str(candidate.get("tcg_key", ""))
        index_url = {
            "onepiece": self.INDEX_URL,
            "union_arena": self.UNION_ARENA_INDEX_URL,
            "dragon_ball_fusion_world": self.DRAGON_BALL_FUSION_WORLD_INDEX_URL,
        }.get(tcg_key)
        if not index_url:
            return [], "プレミアムバンダイ公式: 対象外"
        try:
            links = self.parse_links(self.fetch(index_url), index_url)
        except (OSError, ValueError, urllib.error.URLError) as error:
            return [], f"プレミアムバンダイ公式: 取得失敗 ({error})"
        hits = []
        for link in links:
            url = str(link.get("url", ""))
            text = str(link.get("text", ""))
            if not re.fullmatch(r"https://p-bandai\.jp/item/item-\d+/", url):
                continue
            if tcg_key == "onepiece" and (
                "ONE PIECEカードゲーム" not in text
                and "ONEPIECEカードゲーム" not in text
            ):
                continue
            if tcg_key == "union_arena" and not re.search(
                r"UNION\s*ARENA|ユニオンアリーナ|ユニアリ", text, re.I
            ):
                continue
            if tcg_key == "dragon_ball_fusion_world" and not re.search(
                r"ドラゴンボールスーパーカードゲーム\s*(?:フュージョンワールド|FW)|"
                r"DBSCG\s*(?:FUSION\s*WORLD|FW)", text, re.I
            ):
                continue
            if not re.search(r"抽選販売|予約|受注", text):
                continue
            if not self.matches_candidate(candidate, text):
                continue
            # The list is official evidence, but the detail body is JS/challenge
            # dependent in the desktop HTTP client.  Preserve it as a candidate
            # instead of guessing an active period or auto-confirming it.
            hits.append(normalize_application_site({
                "site_key": "premium_bandai",
                "name": "プレミアムバンダイ",
                "url": url,
                "application_url": url,
                "status": "公式抽選一覧掲載・期間要確認",
                "application_method": "Web",
                "result_mode": "account_page",
                "regions": ["全国"],
                "retailer_verified": True,
                "seller": "プレミアムバンダイ",
                "confidence": 0.9,
                "verification_status": "candidate",
                "confirmed": False,
                "application_evidence": True,
                "notice": text,
                "text": text,
                "source_type": "OFFICIAL_STORE",
                "source_evidence": [{
                    "source_type": "OFFICIAL_STORE",
                    "source_url": index_url,
                }],
                "checked_at": datetime.now().isoformat(timespec="seconds"),
            }, product=candidate))
        return hits, f"プレミアムバンダイ公式候補: {len(hits)}件"
