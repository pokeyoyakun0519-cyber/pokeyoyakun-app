from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from html import unescape
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

from core.application_filters import canonical_application_url
from core.application_status import evaluate_application_period
from core.chain_application_extractors import SafeChainApplicationExtractor
from core.runtime_paths import app_root
from core.web_application_sources import PRIORITY_TCG, WebApplicationSourceRegistry


JST = timezone(timedelta(hours=9))
MONITORABLE_CLASSES = {"WEB_DIRECT", "WEB_FORM", "WEB_TO_STORE", "STORE_DIRECT"}
SKIPPED_CLASSES = {"APP_REQUIRED", "SNS_ONLY", "UNSUPPORTED"}
EXTERNAL_MONITORS = {
    "card_labo", "hobby_station", "pokemon_center_online",
    "bandai", "bandai_official_shop",
}
TCG_PATTERNS = {
    "pokemon": re.compile(r"ポケモンカード|ポケカ|pokemon", re.IGNORECASE),
    "onepiece": re.compile(r"ワンピースカード|ONE\s*PIECE\s*CARD|(?:OP|EB|PRB)-\d+", re.IGNORECASE),
    "dragon_ball_fusion_world": re.compile(
        r"FUSION\s*WORLD|DBSCG\s*FW|ドラゴンボール.*フュージョン", re.IGNORECASE
    ),
}


def source_url(record: dict[str, Any]) -> str:
    for key in (
        "lottery_url", "reservation_url", "index_url", "search_url",
        "official_url", "evidence_url", "url",
    ):
        value = str(record.get(key) or "").strip()
        if value:
            return value
    return ""


def branch_units(record: dict[str, Any]) -> int:
    return max(1, int(record.get("branch_count") or 0))


class _OfficialHostExtractor(SafeChainApplicationExtractor):
    def __init__(self, chain: str, url: str) -> None:
        self.chain = chain
        host = (urlsplit(url).hostname or "").casefold()
        self.allowed_hosts = tuple(dict.fromkeys((host, host.removeprefix("www."), f"www.{host}")))


class NationwideWebApplicationMonitor:
    """Run the registry as a real, low-frequency, evidence-first Web monitor.

    One canonical parent URL is fetched once even when it represents multiple
    TCGs or branches. App-only, SNS-only and unsupported entries are diagnostic
    rows only and are never fetched.
    """

    def __init__(
        self,
        fetch: Callable[[str], dict[str, Any]],
        *,
        registry: WebApplicationSourceRegistry | None = None,
        robots_allowed: Callable[[str], bool] | None = None,
        state_path: Path | None = None,
        ttl_minutes: int = 30,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.fetch = fetch
        self.registry = registry or WebApplicationSourceRegistry()
        self.robots_allowed = robots_allowed or (lambda _url: True)
        self.state_path = state_path or app_root() / "data" / "web_application_monitor_state.json"
        self.ttl = timedelta(minutes=max(5, ttl_minutes))
        self.now = now or (lambda: datetime.now(JST))
        self.diagnostics: dict[str, Any] = {}

    def scan(
        self,
        enabled_tcg_keys: set[str] | None = None,
        *,
        external_results: dict[str, dict[str, Any]] | None = None,
        force: bool = False,
    ) -> list[dict[str, Any]]:
        enabled = set(enabled_tcg_keys or PRIORITY_TCG) & set(PRIORITY_TCG)
        external = external_results or {}
        cached = self._load_state()
        if not force and self._cache_valid(cached, enabled):
            self.diagnostics = dict(cached.get("diagnostics") or {})
            self.diagnostics["cache_hit"] = True
            return [dict(item) for item in cached.get("discoveries", []) if isinstance(item, dict)]

        checked_at = self.now().astimezone(JST).isoformat(timespec="seconds")
        grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        inventory_rows: list[dict[str, Any]] = []
        for tcg in sorted(enabled):
            for raw in self.registry.sources(tcg):
                item = dict(raw, tcg_key=tcg)
                grouped[(str(item.get("chain") or ""), source_url(item))].append(item)

        discoveries: list[dict[str, Any]] = []
        fetched_urls: set[str] = set()
        external_seen: set[tuple[str, str]] = set()
        for (chain, url), records in grouped.items():
            source_class = str(records[0].get("source_class") or "UNSUPPORTED")
            extractor_name = str(records[0].get("extractor") or "none")
            tcgs = sorted({str(item.get("tcg_key")) for item in records})
            target_branches = max(branch_units(item) for item in records)
            base = {
                "source": url,
                "chain": chain,
                "branch": "parent",
                "tcg": tcgs,
                "monitor_type": source_class,
                "declared_branches": max(int(item.get("branch_count") or 0) for item in records),
                "target_branches": target_branches,
                "actual_checked_branches": 0,
                "parent_urls_checked": 0,
                "last_check": checked_at,
                "last_success": "",
                "last_http": "",
                "cache_hit": False,
                "parser_result": "not_run",
                "candidate": 0,
                "candidate_by_tcg": {},
                "official_verified": 0,
                "official_verified_by_tcg": {},
                "confirmed": 0,
                "confirmed_by_tcg": {},
                "ended": 0,
                "ended_by_tcg": {},
                "duplicate": 0,
                "status": "UNSUPPORTED",
                "error_code": "",
                "error_message": "",
            }
            if source_class in SKIPPED_CLASSES:
                base["status"] = source_class
                base["error_code"] = source_class
                inventory_rows.append(base)
                continue
            if source_class not in MONITORABLE_CLASSES or not url:
                base["status"] = "UNSUPPORTED"
                base["error_code"] = "SOURCE_URL_MISSING" if not url else "UNSUPPORTED"
                inventory_rows.append(base)
                continue

            external_key = extractor_name if extractor_name in EXTERNAL_MONITORS else chain
            outcome = external.get(external_key)
            if outcome is not None:
                external_discoveries = []
                for item in outcome.get("discoveries", []):
                    if not isinstance(item, dict):
                        continue
                    tcg = str(item.get("record", {}).get("tcg_key", ""))
                    if chain == "bandai_official_shop":
                        if tcg == "onepiece" and "onepiece-cardgame" not in url:
                            continue
                        if tcg == "dragon_ball_fusion_world" and "dbs-cardgame" not in url:
                            continue
                    key = (
                        str(item.get("record", {}).get("article_url", "")),
                        str(item.get("hit", {}).get("site_key", "")),
                    )
                    if tcg not in tcgs or key in external_seen:
                        continue
                    external_seen.add(key)
                    external_discoveries.append(dict(item))
                scoped_outcome = dict(outcome)
                scoped_outcome["discoveries"] = external_discoveries
                scoped_outcome["candidate"] = len(external_discoveries)
                scoped_outcome["confirmed"] = sum(
                    str(item.get("hit", {}).get("verification_status")) == "confirmed"
                    for item in external_discoveries
                )
                scoped_outcome["official_verified"] = scoped_outcome["confirmed"]
                scoped_outcome["ended"] = sum(
                    self._discovery_ended(item)
                    for item in external_discoveries
                )
                base.update(self._external_status(scoped_outcome, target_branches, checked_at))
                for tcg in tcgs:
                    selected = [
                        item for item in external_discoveries
                        if str(item.get("record", {}).get("tcg_key")) == tcg
                    ]
                    base["candidate_by_tcg"][tcg] = len(selected)
                    base["confirmed_by_tcg"][tcg] = sum(
                        str(item.get("hit", {}).get("verification_status")) == "confirmed"
                        for item in selected
                    )
                    base["official_verified_by_tcg"][tcg] = base["confirmed_by_tcg"][tcg]
                    base["ended_by_tcg"][tcg] = sum(self._discovery_ended(item) for item in selected)
                discoveries.extend(external_discoveries)
                inventory_rows.append(base)
                continue

            if not self.robots_allowed(url):
                base.update({
                    "status": "ACCESS_RESTRICTED", "error_code": "ROBOTS_DISALLOWED",
                    "error_message": "robots policyで自動取得不可",
                })
                inventory_rows.append(base)
                continue

            canonical_parent = canonical_application_url(url) or url
            base["parent_urls_checked"] = 1
            fetched_urls.add(canonical_parent)
            response = self.fetch(url)
            base["last_http"] = str(response.get("status") or "")
            if not response.get("ok"):
                status_text = str(response.get("status") or "HTTP error")
                status = "ACCESS_RESTRICTED" if any(code in status_text for code in ("401", "403", "429")) else "HTTP_ERROR"
                base.update({"status": status, "error_code": status, "error_message": status_text})
                inventory_rows.append(base)
                continue

            base["actual_checked_branches"] = target_branches
            base["last_success"] = checked_at
            html = str(response.get("html") or "")
            if not html.strip():
                base.update({"status": "PARSE_EMPTY", "parser_result": "empty_document"})
                inventory_rows.append(base)
                continue
            try:
                extractor = _OfficialHostExtractor(chain, url)
                parsed = extractor.extract_index(html, url)
            except Exception as error:
                base.update({
                    "status": "PARSER_OUTDATED", "parser_result": "error",
                    "error_code": "PARSER_OUTDATED", "error_message": str(error)[:300],
                })
                inventory_rows.append(base)
                continue
            rows = [dict(item) for item in parsed.get("rows", []) if isinstance(item, dict)]
            base["parser_result"] = "success"
            seen_urls: set[str] = set()
            accepted = 0
            for row in rows:
                application_url = canonical_application_url(row.get("application_url", ""))
                if not application_url or application_url in seen_urls:
                    base["duplicate"] += 1
                    continue
                seen_urls.add(application_url)
                text = unescape(str(row.get("text") or ""))
                detected = [tcg for tcg in tcgs if TCG_PATTERNS[tcg].search(text)]
                if len(detected) != 1:
                    continue
                tcg = detected[0]
                record = {
                    "source_id": f"nationwide_{chain}",
                    "source_name": str(records[0].get("display_name") or chain),
                    "article_url": application_url,
                    "product_name": text[:160],
                    "tcg_key": tcg,
                    "application_evidence": True,
                }
                hit = {
                    "site_key": chain,
                    "name": record["source_name"],
                    "url": application_url,
                    "application_url": application_url,
                    "status": "公式応募ページ候補",
                    "confidence": 0.82,
                    "verification_status": "candidate",
                    "confirmed": False,
                    "source_type": "OFFICIAL_STORE_PAGE",
                    "source_evidence": list(row.get("evidence") or []),
                    "tcg_key": tcg,
                }
                discoveries.append({"record": record, "hit": hit})
                accepted += 1
                base["candidate_by_tcg"][tcg] = int(base["candidate_by_tcg"].get(tcg, 0)) + 1
            base["candidate"] = accepted
            base["status"] = "OK" if accepted else "NO_CURRENT_APPLICATION"
            inventory_rows.append(base)

        self.diagnostics = self._summarize(inventory_rows, enabled, checked_at, len(fetched_urls))
        self._save_state({
            "checked_at": checked_at,
            "enabled_tcg_keys": sorted(enabled),
            "diagnostics": self.diagnostics,
            "discoveries": discoveries,
        })
        return discoveries

    @staticmethod
    def _external_status(outcome: dict[str, Any], branches: int, checked_at: str) -> dict[str, Any]:
        checked = bool(outcome.get("checked", True))
        success = bool(outcome.get("success", False))
        candidates = int(outcome.get("candidate", 0))
        confirmed = int(outcome.get("confirmed", 0))
        status = str(outcome.get("status") or ("OK" if candidates else "NO_CURRENT_APPLICATION"))
        return {
            "actual_checked_branches": branches if checked else 0,
            "parent_urls_checked": int(outcome.get("parent_urls_checked", 1 if checked else 0)),
            "last_success": checked_at if success else "",
            "last_http": str(outcome.get("last_http") or ("adapter success" if success else "adapter error")),
            "parser_result": "success" if success else "error",
            "candidate": candidates,
            "official_verified": int(outcome.get("official_verified", confirmed)),
            "confirmed": confirmed,
            "ended": int(outcome.get("ended", 0)),
            "duplicate": int(outcome.get("duplicate", 0)),
            "status": status,
            "error_code": str(outcome.get("error_code") or ""),
            "error_message": str(outcome.get("error_message") or "")[:300],
        }

    @staticmethod
    def _discovery_ended(item: dict[str, Any]) -> bool:
        record = item.get("record", {})
        if str(record.get("status") or "") == "終了済み":
            return True
        hit = item.get("hit", {})
        return bool(evaluate_application_period(hit)["period_ended"])

    def _summarize(
        self, rows: list[dict[str, Any]], enabled: set[str], checked_at: str, checked_urls: int
    ) -> dict[str, Any]:
        statuses = Counter(str(row.get("status")) for row in rows)
        by_tcg: dict[str, dict[str, Any]] = {}
        for tcg in sorted(enabled):
            selected = [row for row in rows if tcg in row.get("tcg", [])]
            monitorable = [row for row in selected if row.get("monitor_type") in MONITORABLE_CLASSES]
            candidate_branches = sum(int(row.get("declared_branches", 0)) for row in selected)
            monitorable_branches = sum(int(row.get("target_branches", 0)) for row in monitorable)
            checked_branches = sum(int(row.get("actual_checked_branches", 0)) for row in monitorable)
            by_tcg[tcg] = {
                "chain_candidate_count": len({str(row.get("chain")) for row in selected}),
                "branch_candidate_count": candidate_branches,
                "monitorable_branch_count": monitorable_branches,
                "actual_checked_chain_count": len({str(row.get("chain")) for row in monitorable if row.get("actual_checked_branches")}),
                "actual_checked_branch_count": checked_branches,
                "checked_source_url_count": sum(int(row.get("parent_urls_checked", 0)) for row in monitorable),
                "successful_fetch_count": sum(bool(row.get("last_success")) for row in monitorable),
                "parser_success_count": sum(row.get("parser_result") == "success" for row in monitorable),
                "candidate_count": sum(int(row.get("candidate_by_tcg", {}).get(tcg, 0)) for row in monitorable),
                "confirmed_count": sum(int(row.get("confirmed_by_tcg", {}).get(tcg, 0)) for row in monitorable),
                "active_count": sum(
                    max(0, int(row.get("confirmed_by_tcg", {}).get(tcg, 0)) - int(row.get("ended_by_tcg", {}).get(tcg, 0)))
                    for row in monitorable
                ),
                "ended_count": sum(int(row.get("ended_by_tcg", {}).get(tcg, 0)) for row in monitorable),
                "dashboard_rows": sum(int(row.get("confirmed_by_tcg", {}).get(tcg, 0)) for row in monitorable),
                "coverage_percent": round(100 * checked_branches / monitorable_branches, 1) if monitorable_branches else 0.0,
            }
        monitorable_rows = [row for row in rows if row.get("monitor_type") in MONITORABLE_CLASSES]
        monitorable_branches = sum(int(row.get("target_branches", 0)) for row in monitorable_rows)
        checked_branches = sum(int(row.get("actual_checked_branches", 0)) for row in monitorable_rows)
        return {
            "checked_at": checked_at,
            "last_success": max((str(row.get("last_success")) for row in rows), default=""),
            "cache_hit": False,
            "total_candidates": len(rows),
            "registry_source_rows": sum(len(self.registry.sources(tcg)) for tcg in enabled),
            "enabled_monitor_sources": len(monitorable_rows),
            "checked_sources": sum(bool(row.get("parent_urls_checked")) for row in monitorable_rows),
            "checked_source_urls": sum(bool(row.get("parent_urls_checked")) for row in monitorable_rows),
            "generic_fetch_url_count": checked_urls,
            "check_success": sum(bool(row.get("last_success")) for row in monitorable_rows),
            "http_cache_success": sum(bool(row.get("last_success")) for row in monitorable_rows),
            "parse_success": sum(row.get("parser_result") == "success" for row in monitorable_rows),
            "parse_empty": statuses["PARSE_EMPTY"],
            "application_candidates": sum(int(row.get("candidate", 0)) for row in monitorable_rows),
            "official_verified": sum(int(row.get("official_verified", 0)) for row in monitorable_rows),
            "confirmed": sum(int(row.get("confirmed", 0)) for row in monitorable_rows),
            "ended": sum(int(row.get("ended", 0)) for row in monitorable_rows),
            "duplicate": sum(int(row.get("duplicate", 0)) for row in monitorable_rows),
            "skipped": sum(statuses[name] for name in SKIPPED_CLASSES),
            "unsupported": statuses["UNSUPPORTED"],
            "error": sum(statuses[name] for name in ("HTTP_ERROR", "ACCESS_RESTRICTED", "PARSER_OUTDATED", "VERIFICATION_FAILED")),
            "status_counts": dict(statuses),
            "monitorable_branch_count": monitorable_branches,
            "actual_checked_branch_count": checked_branches,
            "coverage_percent": round(100 * checked_branches / monitorable_branches, 1) if monitorable_branches else 0.0,
            "by_tcg": by_tcg,
            "sources": rows,
        }

    def _cache_valid(self, state: dict[str, Any], enabled: set[str]) -> bool:
        if sorted(enabled) != state.get("enabled_tcg_keys"):
            return False
        try:
            checked = datetime.fromisoformat(str(state.get("checked_at") or ""))
            if checked.tzinfo is None:
                checked = checked.replace(tzinfo=JST)
        except ValueError:
            return False
        return self.now().astimezone(JST) - checked.astimezone(JST) < self.ttl

    def _load_state(self) -> dict[str, Any]:
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return {}
        return value if isinstance(value, dict) else {}

    def _save_state(self, state: dict[str, Any]) -> None:
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
            temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(self.state_path)
        except OSError:
            # Monitoring results must not break the primary application flow.
            return

    @classmethod
    def load_saved_diagnostics(cls, path: Path | None = None) -> dict[str, Any]:
        state_path = path or app_root() / "data" / "web_application_monitor_state.json"
        try:
            value = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return {}
        diagnostics = value.get("diagnostics") if isinstance(value, dict) else None
        return dict(diagnostics) if isinstance(diagnostics, dict) else {}
