from __future__ import annotations

import re
from datetime import datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlsplit

from core.application_status import JST
from core.nyuka_now_discovery import TIER_B_DISCOVERY, merge_discovery_candidates


SOURCE_URL = "https://gamenv.net/tc/"
ADOPTION_STATUS = "TERMS_RESTRICTED"
TIER_C_REFERENCE = "TIER_C_REFERENCE"
TCG_PATTERNS = (
    ("pokemon", re.compile(r"ポケ(?:モン)?カード|ポケカ|Pokémon", re.I)),
    ("onepiece", re.compile(r"ONE\s*PIECE|ワンピース", re.I)),
    ("dragon_ball_fusion_world", re.compile(r"Fusion\s*World|フュージョンワールド|ドラゴンボール", re.I)),
    ("yugioh", re.compile(r"遊戯王", re.I)),
    ("gundam", re.compile(r"ガンダムカード", re.I)),
    ("union_arena", re.compile(r"UNION\s*ARENA|ユニオンアリーナ", re.I)),
)
APPLICATION_TERMS = re.compile(r"抽選|予約|応募|受付|先着|再販|入荷", re.I)
REFERENCE_TERMS = re.compile(r"コメント|掲示板|コミュニティ|ユーザー投稿", re.I)


class _EditorialLinkParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.href = ""
        self.parts: list[str] = []
        self.links: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        values = {str(key).casefold(): str(value or "") for key, value in attrs}
        if tag.casefold() == "a":
            self.href = urljoin(self.base_url, values.get("href", ""))
            self.parts = [values.get("title", ""), values.get("aria-label", "")]

    def handle_data(self, data: str) -> None:
        if self.href and data.strip():
            self.parts.append(data.strip())

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "a" and self.href:
            text = re.sub(r"\s+", " ", " ".join(self.parts)).strip()
            self.links.append({"url": self.href, "text": text})
            self.href, self.parts = "", []


class GamenvDiscovery:
    """Offline parser for an editorial discovery source.

    The site's terms reserve reuse of published content, so automated polling is
    deliberately disabled. Operators may supply an explicitly audited document;
    resulting records remain discovery/reference evidence and never confirm alone.
    """

    def __init__(self, *, now=None) -> None:
        self.now = now or (lambda: datetime.now(JST))
        self.last_diagnostics = self._empty_diagnostics()

    def poll(self) -> list[dict[str, Any]]:
        self.last_diagnostics["prevented_fetch_count"] += 1
        self.last_diagnostics["last_check"] = self.now().isoformat(timespec="seconds")
        return []

    def parse_editorial_index(self, html: str, source_url: str = SOURCE_URL) -> list[dict[str, Any]]:
        parser = _EditorialLinkParser(source_url)
        parser.feed(str(html or ""))
        candidates = []
        for link in parser.links:
            text = link["text"]
            tcg = next((key for key, pattern in TCG_PATTERNS if pattern.search(text)), "")
            if not tcg or not APPLICATION_TERMS.search(text) or not _safe_gamenv_url(link["url"]):
                continue
            tier = TIER_C_REFERENCE if REFERENCE_TERMS.search(text) else TIER_B_DISCOVERY
            observed = self.now().isoformat(timespec="seconds")
            candidates.append({
                "tcg_key": tcg,
                "product_name": text[:300],
                "store_name": "",
                "branch": "",
                "application_end_at": "",
                "application_url": "",
                "source_name": "人気トレカゲットナビ",
                "source_type": "EDITORIAL_DISCOVERY" if tier == TIER_B_DISCOVERY else "USER_REFERENCE",
                "source_article_url": link["url"],
                "discovery_source_url": link["url"],
                "freshness": observed,
                "trust_tier": tier,
                "verification_status": "candidate",
                "confirmed": False,
                "evidence": [{
                    "source_type": "EDITORIAL_DISCOVERY" if tier == TIER_B_DISCOVERY else "USER_REFERENCE",
                    "source_url": link["url"], "observed_at": observed,
                    "trust": 55 if tier == TIER_B_DISCOVERY else 20,
                    "verification_status": "candidate",
                    "extracted_fields": {"tcg_key": tcg, "headline": text[:300]},
                }],
            })
        unique = merge_discovery_candidates(candidates)
        self.last_diagnostics.update({
            "last_check": self.now().isoformat(timespec="seconds"),
            "links_parsed": len(parser.links), "candidates": len(unique),
            "tier_b": sum(item["trust_tier"] == TIER_B_DISCOVERY for item in unique),
            "tier_c": sum(item["trust_tier"] == TIER_C_REFERENCE for item in unique),
            "by_tcg": {key: sum(item["tcg_key"] == key for item in unique) for key, _ in TCG_PATTERNS},
        })
        return unique

    def diagnostics(self) -> dict[str, Any]:
        return dict(self.last_diagnostics)

    @staticmethod
    def _empty_diagnostics() -> dict[str, Any]:
        return {
            "source_name": "人気トレカゲットナビ", "source_url": SOURCE_URL,
            "trust_tier": TIER_B_DISCOVERY, "comment_tier": TIER_C_REFERENCE,
            "adoption_status": ADOPTION_STATUS, "auto_enabled": False,
            "policy_reason": "site terms prohibit unauthorized reuse of published content",
            "last_check": "", "links_parsed": 0, "candidates": 0,
            "tier_b": 0, "tier_c": 0, "prevented_fetch_count": 0,
        }


def _safe_gamenv_url(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        return (
            parsed.scheme.casefold() == "https"
            and (parsed.hostname or "").casefold() == "gamenv.net"
            and parsed.path.startswith("/tc/")
            and not parsed.username and not parsed.password
        )
    except ValueError:
        return False
