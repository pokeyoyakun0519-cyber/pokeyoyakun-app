from __future__ import annotations

from collections import Counter
from typing import Any

from core.builtin_store_catalog import load_builtin_store_catalog
from core.retail_plugin_registry import BUILTIN_RETAIL_PLUGINS


SOURCE_CLASSES = (
    "WEB_DIRECT", "WEB_FORM", "WEB_TO_STORE", "STORE_DIRECT",
    "APP_REQUIRED", "SNS_ONLY", "UNSUPPORTED",
)
PRIORITY_TCG = ("pokemon", "onepiece", "dragon_ball_fusion_world")

# Official pages checked during the WebMonitor v2 audit.  These entries are
# deliberately conservative: an official store list alone does not make an
# application feed automatically monitorable.
AUDIT_CANDIDATES: tuple[dict[str, Any], ...] = (
    {"canonical_store_id": "batoroco", "store_group_id": "batoroco", "display_name": "バトロコ",
     "official_url": "https://bato-loco.com/all/", "evidence_url": "https://bato-loco.com/all/",
     "source_class": "SNS_ONLY", "tcg": list(PRIORITY_TCG), "branch_count": 41},
    {"canonical_store_id": "plays", "store_group_id": "plays", "display_name": "プレイズ",
     "official_url": "https://www.preyz.com/", "evidence_url": "https://www.preyz.com/",
     "source_class": "SNS_ONLY", "tcg": list(PRIORITY_TCG), "branch_count": 14},
    {"canonical_store_id": "otakarasouko", "store_group_id": "otakarasouko", "display_name": "お宝創庫",
     "official_url": "https://www.otakarasouko.com/", "evidence_url": "https://www.otakarasouko.com/",
     "source_class": "APP_REQUIRED", "tcg": list(PRIORITY_TCG)},
    {"canonical_store_id": "magi", "store_group_id": "magi", "display_name": "magi",
     "official_url": "https://magi.camp/news/", "evidence_url": "https://magi.camp/news/",
     "source_class": "WEB_FORM", "tcg": ["pokemon", "onepiece"]},
    {"canonical_store_id": "seagull", "store_group_id": "seagull", "display_name": "シーガル",
     "official_url": "https://seagullonline.jp/category/予約情報/",
     "evidence_url": "https://seagullonline.jp/category/予約情報/", "source_class": "STORE_DIRECT",
     "tcg": list(PRIORITY_TCG)},
    {"canonical_store_id": "toycomp", "store_group_id": "toycomp", "display_name": "トイコンプ",
     "official_url": "https://www.toy-comp.com/", "evidence_url": "https://www.toy-comp.com/",
     "source_class": "SNS_ONLY", "tcg": list(PRIORITY_TCG)},
    {"canonical_store_id": "girafull", "store_group_id": "girafull", "display_name": "GIRAFULL",
     "official_url": "https://ec.girafull.co.jp/", "evidence_url": "https://ec.girafull.co.jp/",
     "source_class": "UNSUPPORTED", "tcg": list(PRIORITY_TCG)},
    {"canonical_store_id": "hmv", "store_group_id": "hmv", "display_name": "HMV&BOOKS",
     "official_url": "https://www.hmv.co.jp/", "evidence_url": "https://www.hmv.co.jp/",
     "source_class": "UNSUPPORTED", "tcg": ["pokemon", "onepiece"]},
    {"canonical_store_id": "pokemon_center_stores", "store_group_id": "pokemon_center",
     "display_name": "ポケモンセンター／ポケモンストア",
     "official_url": "https://shop.pokemon.co.jp/ja/", "evidence_url": "https://shop.pokemon.co.jp/ja/",
     "source_class": "WEB_TO_STORE", "tcg": ["pokemon"]},
    {"canonical_store_id": "onepiece_official_shop", "store_group_id": "bandai_official_shop",
     "display_name": "ONE PIECEカードゲーム公式ショップ",
     "official_url": "https://bandainamco-am.co.jp/official_shop/onepiece-cardgame/index.html",
     "evidence_url": "https://bandainamco-am.co.jp/official_shop/onepiece-cardgame/index.html",
     "source_class": "STORE_DIRECT", "tcg": ["onepiece"], "branch_count": 20},
    {"canonical_store_id": "bandai_cross_store", "store_group_id": "bandai_official_shop",
     "display_name": "BANDAI CARD GAMES関連公式店舗",
     "official_url": "https://bandainamco-am.co.jp/crossstore/shop/",
     "evidence_url": "https://bandainamco-am.co.jp/crossstore/shop/",
     "source_class": "STORE_DIRECT", "tcg": ["onepiece", "dragon_ball_fusion_world"]},
    {"canonical_store_id": "dbfw_official_store", "store_group_id": "bandai_official_shop",
     "display_name": "Fusion Worldオフィシャルストア",
     "official_url": "https://bandainamco-am.co.jp/official_shop/dbs-cardgame/index.html",
     "evidence_url": "https://bandainamco-am.co.jp/official_shop/dbs-cardgame/index.html",
     "source_class": "STORE_DIRECT", "tcg": ["dragon_ball_fusion_world"], "branch_count": 2},
)


def _classify(record: dict[str, Any]) -> str:
    method = str(record.get("discovery_method") or "unsupported")
    if method == "official_app" or record.get("requires_app"):
        return "APP_REQUIRED"
    if method == "official_social":
        return "SNS_ONLY"
    if method == "unsupported" or not record.get("monitoring_supported"):
        return "UNSUPPORTED"
    if record.get("lottery_url"):
        return "WEB_FORM"
    if str(record.get("channel")) == "physical" or method == "store_only":
        return "STORE_DIRECT"
    if method in {"product_search", "category", "reservation", "official_news"}:
        return "WEB_DIRECT"
    return "UNSUPPORTED"


class WebApplicationSourceRegistry:
    """Evidence-backed, uncapped inventory of Web application sources.

    The bundled store catalog remains the source of truth.  This view adds an
    explicit acquisition classification without claiming that unsupported or
    app-only stores can be scraped.
    """

    def __init__(self) -> None:
        catalog = load_builtin_store_catalog()
        self.records = [dict(item) for item in catalog.get("stores", [])]
        self.records.extend(dict(item, audit_candidate=True) for item in AUDIT_CANDIDATES)
        self._plugins = {str(item.get("id")): item for item in BUILTIN_RETAIL_PLUGINS}

    def sources(self, tcg_key: str | None = None) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for raw in self.records:  # intentionally no item limit
            record = dict(raw)
            plugin = self._plugins.get(str(record.get("canonical_store_id")), {})
            support = str(record.get("tcg_support", {}).get(tcg_key, "unknown"))
            plugin_support = tcg_key in plugin.get("tcg", [])
            audit_support = tcg_key in record.get("tcg", [])
            if tcg_key and support not in {"supported", "partial"} and not plugin_support and not audit_support:
                continue
            locations = record.get("confirmed_locations", [])
            record.update({
                "source_class": str(record.get("source_class") or _classify(record)),
                "tcg_key": tcg_key or "all",
                "chain": str(record.get("store_group_id") or record.get("canonical_store_id")),
                "branch_count": int(record.get("branch_count") or (
                    len(locations) if isinstance(locations, list) else 0
                )),
                "extractor": (
                    str(plugin.get("id")) if plugin.get("mode") == "dedicated"
                    else "safe_public_html" if record.get("monitoring_supported")
                    else "none"
                ),
            })
            output.append(record)
        return output

    def diagnostics(self) -> dict[str, Any]:
        by_tcg: dict[str, dict[str, Any]] = {}
        all_sources = self.sources()
        classes = Counter(item["source_class"] for item in all_sources)
        for tcg in PRIORITY_TCG:
            items = self.sources(tcg)
            by_tcg[tcg] = {
                "chains": len({item["chain"] for item in items}),
                "explicit_branches": sum(int(item["branch_count"]) for item in items),
                "sources": len(items),
                "by_class": dict(Counter(item["source_class"] for item in items)),
            }
        return {
            "total_sources": len(all_sources),
            "by_class": {name: classes.get(name, 0) for name in SOURCE_CLASSES},
            "by_tcg": by_tcg,
        }
