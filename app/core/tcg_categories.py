from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable
import re
import unicodedata


@dataclass(frozen=True)
class TcgCategory:
    key: str
    display_name: str
    short_name: str
    display_order: int
    enabled: bool = True


_CATEGORIES = (
    TcgCategory("pokemon", "ポケモンカード", "ポケモン", 10),
    TcgCategory("onepiece", "ワンピースカード", "ワンピース", 20),
    TcgCategory("yugioh", "遊戯王OCG", "遊戯王", 30),
    TcgCategory("gundam", "ガンダムカード", "ガンダム", 40),
    TcgCategory("union_arena", "UNION ARENA", "ユニアリ", 45),
    TcgCategory("duelmasters", "デュエル・マスターズ", "デュエマ", 50),
    TcgCategory("weiss", "ヴァイスシュヴァルツ", "ヴァイス", 60),
    TcgCategory("mtg", "マジック：ザ・ギャザリング", "MTG", 70),
    TcgCategory("other", "その他", "その他", 90),
)
CATEGORY_REGISTRY = {item.key: item for item in _CATEGORIES}
_LABEL_ALIASES = {
    "ポケモンカードゲーム": "pokemon",
    "pokemon": "pokemon",
    "one pieceカードゲーム": "onepiece",
    "one piece": "onepiece",
    "ワンピース": "onepiece",
    "ワンピースカードゲーム": "onepiece",
    "遊戯王": "yugioh",
    "遊戯王ocg": "yugioh",
    "yu-gi-oh!": "yugioh",
    "ガンダム": "gundam",
    "ガンダムカードゲーム": "gundam",
    "pokemon card game": "pokemon",
    "pokémon card game": "pokemon",
    "onepiece": "onepiece",
    "one piece card game": "onepiece",
    "opcg": "onepiece",
    "yugioh": "yugioh",
    "yu gi oh": "yugioh",
    "yu-gi-oh": "yugioh",
    "遊戯王カードゲーム": "yugioh",
    "gundam": "gundam",
    "gundam card game": "gundam",
    "gundam gcg": "gundam",
    "union arena": "union_arena",
    "union_arena": "union_arena",
    "ユニオンアリーナ": "union_arena",
    "ユニアリ": "union_arena",
    "デュエル・マスターズ": "duelmasters",
    "デュエルマスターズ": "duelmasters",
    "デュエマ": "duelmasters",
    "duel masters": "duelmasters",
    "duelmasters": "duelmasters",
    "dm": "duelmasters",
    "ヴァイスシュヴァルツ": "weiss",
    "ヴァイス": "weiss",
    "weiss schwarz": "weiss",
    "weissschwarz": "weiss",
    "ws": "weiss",
    "マジック：ザ・ギャザリング": "mtg",
    "マジック:ザ・ギャザリング": "mtg",
    "マジック・ザ・ギャザリング": "mtg",
    "magic: the gathering": "mtg",
    "magic the gathering": "mtg",
    "mtg": "mtg",
}
for _item in _CATEGORIES:
    _LABEL_ALIASES[_item.display_name.lower()] = _item.key
    _LABEL_ALIASES[_item.short_name.lower()] = _item.key


def categories(*, enabled_only: bool = False) -> tuple[TcgCategory, ...]:
    values = tuple(item for item in _CATEGORIES if item.enabled or not enabled_only)
    return tuple(sorted(values, key=lambda item: item.display_order))


def category_for_key(key: object) -> TcgCategory | None:
    return CATEGORY_REGISTRY.get(str(key or "").strip().lower())


def key_from_label(label: object) -> str | None:
    clean = unicodedata.normalize("NFKC", str(label or "")).strip().casefold()
    direct = _LABEL_ALIASES.get(clean)
    if direct:
        return direct
    compact = re.sub(r"[\s_\-‐―!！]+", "", clean)
    for alias, key in _LABEL_ALIASES.items():
        if re.sub(r"[\s_\-‐―!！]+", "", alias.casefold()) == compact:
            return key
    return None


def normalize_key(key: object, label: object = "") -> tuple[str, bool]:
    clean = str(key or "").strip().lower()
    if clean in CATEGORY_REGISTRY:
        return clean, False
    if clean:
        alias = key_from_label(clean) or key_from_label(label)
        return alias or "other", True
    return key_from_label(label) or "other", False


def display_name(key: object, fallback: object = "") -> str:
    item = category_for_key(key)
    return item.display_name if item else str(fallback or "").strip() or "その他"


def normalize_record(record: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    value = dict(record)
    key, unknown = normalize_key(
        value.get("tcg_key"), value.get("tcg") or value.get("category")
    )
    value["tcg_key"] = key
    value["tcg"] = display_name(key, value.get("tcg"))
    return value, key if unknown else None


def normalize_keys(values: Iterable[object]) -> tuple[list[str], list[str]]:
    output: list[str] = []
    unknown: list[str] = []
    for value in values:
        key, is_unknown = normalize_key(value)
        if key not in output:
            output.append(key)
        if is_unknown and key not in unknown:
            unknown.append(key)
    return output or ["other"], unknown
