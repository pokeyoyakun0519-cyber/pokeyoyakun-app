from __future__ import annotations

from collections import Counter
from typing import Any, Callable

from core.candidate_manager import CandidateManager
from core.candidate_auto_search import CandidateAutoSearch
from core.auto_monitor_manager import AutoMonitorManager
from core.config_manager import ConfigManager
from core.product_store import ProductStore
from core.source_manager import SourceManager
from core.tcg_categories import normalize_key


class InitialDataBootstrap:
    """空のユーザーデータへ公式商品情報を一度だけ取得する。"""

    def __init__(
        self,
        *,
        config_manager: ConfigManager | None = None,
        product_store: ProductStore | None = None,
        candidate_manager: CandidateManager | None = None,
        source_manager: SourceManager | None = None,
        candidate_auto_search: CandidateAutoSearch | None = None,
    ) -> None:
        self.config_manager = config_manager or ConfigManager()
        self.product_store = product_store or ProductStore()
        self.candidate_manager = candidate_manager or CandidateManager()
        self.source_manager = source_manager or SourceManager()
        self.candidate_auto_search = candidate_auto_search or CandidateAutoSearch()

    def should_run(self) -> bool:
        general = self.config_manager.load().get("general", {})
        if not bool(general.get("setup_completed", False)):
            return False
        if not bool(general.get("new_product_auto_fetch", True)):
            return False
        if self.product_store._load_product_file():
            return False
        return not bool(self.candidate_manager.load_candidates())

    def run(
        self,
        on_official_loaded: Callable[[dict[str, Any]], None] | None = None,
        on_retail_progress: Callable[[dict[str, Any]], None] | None = None,
        cancel_requested: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        if not self.should_run():
            return {"started": False, "reason": "not_empty_or_disabled"}
        if cancel_requested is not None and cancel_requested():
            return {"started": True, "cancelled": True, "phase": "cancelled"}

        if cancel_requested is None:
            sources, changed = self.source_manager.check_all()
        else:
            sources, changed = self.source_manager.check_all(
                cancel_requested=cancel_requested
            )
        candidates = self.candidate_manager.load_candidates()
        monitored_keys = {
            AutoMonitorManager.product_key(item)
            for item in self.product_store._load_product_file()
            if item.get("auto_monitored")
        }
        candidate_ids = {
            str(item.get("id", ""))
            for item in candidates
            if AutoMonitorManager.product_key(item) in monitored_keys
        }
        products = self.product_store.load_products()
        official_result = self._result(
            sources=sources,
            changed=changed,
            candidates=candidates,
            products=products,
            candidate_ids=candidate_ids,
            retail_searched_count=0,
        )
        official_result["phase"] = "official"
        official_result["cancelled"] = bool(
            cancel_requested is not None and cancel_requested()
        )
        if on_official_loaded is not None and not official_result["cancelled"]:
            on_official_loaded(dict(official_result))
        if official_result["cancelled"]:
            official_result["phase"] = "cancelled"
            return official_result

        retail_result = (
            self.candidate_auto_search.run_due(
                candidate_ids=candidate_ids,
                progress_callback=(
                    lambda candidate, searched: on_retail_progress({
                        "searched": searched,
                        "total": len(candidate_ids),
                        "candidate_id": str(candidate.get("id", "")),
                        "candidate_name": str(candidate.get("name", "")),
                    })
                    if on_retail_progress is not None
                    else None
                ),
                cancel_requested=cancel_requested,
            )
            if candidate_ids
            else {"searched_count": 0, "new_hit_candidates": []}
        )
        products = self.product_store.load_products()
        result = self._result(
            sources=sources,
            changed=changed,
            candidates=candidates,
            products=products,
            candidate_ids=candidate_ids,
            retail_searched_count=int(retail_result.get("searched_count", 0)),
        )
        result["cancelled"] = bool(
            retail_result.get("cancelled")
            or (cancel_requested is not None and cancel_requested())
        )
        result["phase"] = "cancelled" if result["cancelled"] else "completed"
        return result

    @staticmethod
    def _result(
        *,
        sources: list[dict[str, Any]],
        changed: list[Any],
        candidates: list[dict[str, Any]],
        products: list[dict[str, Any]],
        candidate_ids: set[str],
        retail_searched_count: int,
    ) -> dict[str, Any]:
        per_tcg = Counter(
            normalize_key(item.get("tcg_key"), item.get("tcg"))[0]
            for item in products
        )
        return {
            "started": True,
            "source_count": len(sources),
            "changed_source_count": len(changed),
            "candidate_count": len(candidates),
            "product_count": len(products),
            "retail_candidate_count": len(candidate_ids),
            "retail_searched_count": retail_searched_count,
            "per_tcg": dict(per_tcg),
        }
