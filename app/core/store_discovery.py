from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from core.builtin_store_catalog import load_builtin_store_catalog, match_builtin_store
from core.store_candidate_manager import StoreCandidateManager


class StoreDiscovery:
    """公開ページ上の店舗リンクを既存店舗照合または審査候補へ振り分ける。"""

    def __init__(self, candidate_manager: StoreCandidateManager | None = None):
        self.candidates = candidate_manager or StoreCandidateManager()
        self.catalog = load_builtin_store_catalog()["stores"]
        self.reset()

    def reset(self) -> None:
        self.diagnostics: dict[str, Any] = {
            "searched_source_count": 0,
            "discovered_store_name_count": 0,
            "existing_store_match_count": 0,
            "new_candidate_count": 0,
            "duplicate_excluded_count": 0,
            "url_safety_rejected_count": 0,
            "insufficient_evidence_count": 0,
            "save_failure_count": 0,
            "monitoring_unsupported_count": 0,
            "failure_reasons": [],
            "checked_at": datetime.now().isoformat(timespec="seconds"),
        }

    def inspect_links(
        self,
        links: list[dict[str, str]],
        *,
        source_url: str,
        product_name: str = "",
        tcg_key: str = "unknown",
        discovery_type: str = "unknown",
    ) -> dict[str, Any]:
        self.diagnostics["searched_source_count"] += 1
        seen: set[tuple[str, str]] = set()
        for link in links:
            name = str(link.get("text", "")).strip()
            url = str(link.get("url", "")).strip()
            if not name:
                self.diagnostics["insufficient_evidence_count"] += 1
                continue
            key = (name.casefold(), url)
            if key in seen:
                self.diagnostics["duplicate_excluded_count"] += 1
                continue
            seen.add(key)
            self.diagnostics["discovered_store_name_count"] += 1

            known = match_builtin_store(self.catalog, name=name, url=url)
            if known:
                self.diagnostics["existing_store_match_count"] += 1
                continue

            host = (urlparse(url).hostname or "").casefold()
            saved = self.candidates.add_candidate({
                "name": name,
                "host": host,
                "url": url,
                "source_url": source_url,
                "product_name": product_name,
                "tcg_key": tcg_key or "unknown",
                "discovery_type": discovery_type,
                "evidence_text": name,
                "confidence": 0.65,
            })
            result = dict(self.candidates.last_result)
            if saved:
                self.diagnostics["new_candidate_count"] += 1
                if result.get("status") == "monitoring_unsupported":
                    self.diagnostics["monitoring_unsupported_count"] += 1
                continue
            status = str(result.get("status", ""))
            reason = str(result.get("reason", "候補に保存できませんでした"))
            if status == "duplicate":
                self.diagnostics["duplicate_excluded_count"] += 1
            elif status == "insufficient_evidence":
                self.diagnostics["insufficient_evidence_count"] += 1
            elif "保存失敗" in reason or "更新失敗" in reason:
                self.diagnostics["save_failure_count"] += 1
            else:
                self.diagnostics["url_safety_rejected_count"] += 1
            if reason not in self.diagnostics["failure_reasons"]:
                self.diagnostics["failure_reasons"].append(reason)
        self.diagnostics["checked_at"] = datetime.now().isoformat(timespec="seconds")
        return dict(self.diagnostics)
