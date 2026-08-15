from __future__ import annotations

from typing import Any

from core.tcg_categories import normalize_key


PRIORITY_TCG_KEYS = frozenset({"pokemon", "onepiece"})
OTHER_TCG_KEYS = frozenset({"union_arena", "duelmasters", "weiss", "mtg", "other"})


def enabled_tcg_keys(config: dict[str, Any]) -> set[str]:
    games = config.get("games", {})
    enabled = {
        normalize_key(key)[0]
        for key, value in games.items()
        if bool(value)
    }
    if bool(games.get("other", False)):
        enabled.update(OTHER_TCG_KEYS)
    if config.get("general", {}).get("priority_monitoring_only", False):
        enabled &= PRIORITY_TCG_KEYS
    return enabled
