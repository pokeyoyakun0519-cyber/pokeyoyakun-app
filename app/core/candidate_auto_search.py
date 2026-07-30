from datetime import datetime, timedelta
from typing import Any, Callable

from core.candidate_manager import CandidateManager
from core.retail_search_manager import RetailSearchManager


class CandidateAutoSearch:
    def __init__(self):
        self.candidates = CandidateManager()
        self.searcher = RetailSearchManager()

    def run_due(
        self,
        interval_minutes: int = 30,
        candidate_ids: set[str] | None = None,
        progress_callback: Callable[[dict[str, Any], int], None] | None = None,
        cancel_requested: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        items = self.candidates.load_candidates()
        searched = 0
        new_hit_candidates = []

        cancelled = False
        for candidate in items:
            if cancel_requested is not None and cancel_requested():
                cancelled = True
                break
            if (
                candidate_ids is not None
                and str(candidate.get("id", "")) not in candidate_ids
            ):
                continue
            if not self._is_due(
                str(candidate.get("last_searched", "")),
                interval_minutes,
            ):
                continue

            old_keys = {
                (
                    str(hit.get("site_key", "")),
                    str(hit.get("url", "")),
                )
                for hit in candidate.get("retail_hits", [])
                if isinstance(hit, dict)
            }

            hits, messages = self.searcher.search_candidate(
                candidate
            )
            updated = self.candidates.update_search_result(
                str(candidate.get("id", "")),
                hits=hits,
                messages=messages,
            )
            searched += 1
            if progress_callback is not None:
                progress_callback(candidate, searched)
            if cancel_requested is not None and cancel_requested():
                cancelled = True
                break

            new_hits = [
                hit
                for hit in hits
                if (
                    str(hit.get("site_key", "")),
                    str(hit.get("url", "")),
                )
                not in old_keys
            ]
            if new_hits and updated is not None:
                new_hit_candidates.append(
                    {
                        "candidate": updated,
                        "new_hits": new_hits,
                    }
                )

        return {
            "searched_count": searched,
            "new_hit_candidates": new_hit_candidates,
            "cancelled": cancelled,
        }

    @staticmethod
    def _is_due(
        last_searched: str,
        interval_minutes: int,
    ) -> bool:
        if not last_searched.strip():
            return True
        try:
            last = datetime.fromisoformat(last_searched)
        except ValueError:
            return True
        return (
            datetime.now() - last
            >= timedelta(minutes=max(5, interval_minutes))
        )
