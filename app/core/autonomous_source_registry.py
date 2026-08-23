from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from core.runtime_paths import app_root, bundled_root, is_frozen


SOURCE_STATES = {
    "KNOWN_ACTIVE", "KNOWN_INACTIVE", "DISCOVERED_CANDIDATE", "VERIFYING",
    "VERIFIED_OFFICIAL", "MONITORABLE", "BLOCKED_ROBOTS", "APP_REQUIRED",
    "SNS_ONLY", "TERMS_RESTRICTED", "UNSUPPORTED", "REJECTED", "TEMPORARILY_FAILED",
}
TRUST_TIERS = {"TIER_A_OFFICIAL", "TIER_B_DISCOVERY", "TIER_C_REFERENCE"}
SEED_TYPES = {
    "MANUFACTURER", "RETAILER", "CARD_SHOP", "MALL", "OFFICIAL_SHOP",
    "OFFICIAL_EC", "DISCOVERY", "FORM_PROVIDER",
}


def seed_path() -> Path:
    if is_frozen():
        return bundled_root() / "resources" / "autonomous_web_seeds.json"
    return Path(__file__).resolve().parents[1] / "resources" / "autonomous_web_seeds.json"


def canonical_host(url: object) -> str:
    try:
        return (urlsplit(str(url or "")).hostname or "").casefold().removeprefix("www.")
    except ValueError:
        return ""


def canonical_domain(value: object) -> str:
    text = str(value or "").strip().casefold()
    return canonical_host(text) if "://" in text else text.removeprefix("www.").strip(".")


class OfficialSourceCandidateStore:
    """Persist only bounded source metadata; never persist fetched HTML."""

    def __init__(self, root: Path | None = None, seeds_file: Path | None = None) -> None:
        self.root = Path(root) if root is not None else app_root()
        self.path = self.root / "data" / "autonomous_source_registry.json"
        self.seeds_file = seeds_file or seed_path()
        self.records = self._merge_records(self._load_seeds(), self._load_learned())

    def sources(self, *, enabled_tcg: set[str] | None = None) -> list[dict[str, Any]]:
        output = []
        for record in self.records:
            tcgs = set(record.get("supported_tcg", []))
            if enabled_tcg and not tcgs.intersection(enabled_tcg):
                continue
            output.append(dict(record))
        return output

    def discover(
        self,
        *,
        name: str,
        url: str,
        source_url: str,
        provenance: str,
        trust_tier: str = "TIER_C_REFERENCE",
        supported_tcg: list[str] | None = None,
        seed_type: str = "RETAILER",
    ) -> dict[str, Any]:
        host = canonical_host(url)
        if not host or not source_url or trust_tier not in TRUST_TIERS:
            raise ValueError("source candidate needs a host, provenance, and trust tier")
        existing = self._by_host(host)
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        evidence = {
            "source_url": str(source_url),
            "provenance": str(provenance),
            "observed_at": now,
        }
        if existing:
            values = list(existing.get("official_evidence", []))
            if (evidence["source_url"], evidence["provenance"]) not in {
                (str(item.get("source_url")), str(item.get("provenance")))
                for item in values if isinstance(item, dict)
            }:
                values.append(evidence)
            existing["official_evidence"] = values[-20:]
            existing["last_checked"] = now
            existing["supported_tcg"] = sorted(set(existing.get("supported_tcg", [])) | set(supported_tcg or []))
            self.save()
            return dict(existing)
        digest = hashlib.sha256(f"{host}|{url}".encode()).hexdigest()[:16]
        record = {
            "id": f"discovered_{digest}",
            "name": str(name or host),
            "base_url": str(url),
            "official_domains": [host],
            "seed_type": seed_type if seed_type in SEED_TYPES else "RETAILER",
            "trust_tier": trust_tier,
            "supported_tcg": sorted(set(supported_tcg or [])),
            "discovery_paths": [],
            "source_state": "DISCOVERED_CANDIDATE",
            "enabled": False,
            "robots_status": "unknown",
            "last_checked": "",
            "last_success": "",
            "failure_count": 0,
            "parser_empty_count": 0,
            "learned_patterns": [],
            "official_evidence": [evidence],
            "created_at": now,
        }
        self.records.append(record)
        self.save()
        return dict(record)

    def begin_verification(self, source_id: str) -> dict[str, Any]:
        record = self._by_id(source_id)
        if record["source_state"] not in {"DISCOVERED_CANDIDATE", "TEMPORARILY_FAILED"}:
            return dict(record)
        record["source_state"] = "VERIFYING"
        self.save()
        return dict(record)

    def complete_verification(self, source_id: str, checks: dict[str, Any]) -> dict[str, Any]:
        record = self._by_id(source_id)
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        record["last_checked"] = now
        if checks.get("robots_allowed") is False:
            record.update({"source_state": "BLOCKED_ROBOTS", "enabled": False, "robots_status": "blocked"})
        elif all(bool(checks.get(name)) for name in (
            "official_provenance", "https", "robots_allowed", "fetch_success",
            "parser_success", "redirect_safe",
        )) and (
            (
                float(checks.get("tcg_confidence", 0)) >= 0.7
                and float(checks.get("application_relevance", 0)) >= 0.7
            )
            or bool(checks.get("source_monitorable"))
        ):
            record.update({
                "source_state": "MONITORABLE", "enabled": True,
                "robots_status": "allowed", "last_success": now,
                "failure_count": 0,
            })
        elif checks.get("permanent_rejection"):
            record.update({"source_state": "REJECTED", "enabled": False})
        else:
            record.update({
                "source_state": "VERIFIED_OFFICIAL" if checks.get("official_provenance") else "DISCOVERED_CANDIDATE",
                "enabled": False,
                "failure_count": int(record.get("failure_count", 0)) + 1,
            })
        record["verification_checks"] = {
            key: value for key, value in checks.items()
            if key not in {"html", "body", "content"}
        }
        self.save()
        return dict(record)

    def observe_parser(self, source_id: str, *, fetch_ok: bool, application_count: int) -> str:
        record = self._by_id(source_id)
        if fetch_ok and application_count == 0 and int(record.get("successful_application_pages", 0)):
            record["parser_empty_count"] = int(record.get("parser_empty_count", 0)) + 1
        elif application_count:
            record["parser_empty_count"] = 0
            record["successful_application_pages"] = int(record.get("successful_application_pages", 0)) + application_count
        if int(record.get("parser_empty_count", 0)) >= 2:
            record["health"] = "PARSER_OUTDATED"
        elif fetch_ok:
            record["health"] = "HEALTHY" if application_count else "NO_CURRENT_APPLICATION"
        else:
            record["health"] = "HTTP_ERROR"
        self.save()
        return str(record["health"])

    def learn_pattern(self, source_id: str, pattern: str) -> None:
        if not pattern or "*" in pattern:
            return
        record = self._by_id(source_id)
        patterns = list(record.get("learned_patterns", []))
        if pattern not in patterns:
            patterns.append(pattern[:200])
            record["learned_patterns"] = patterns[-20:]
            self.save()

    def diagnostics(self) -> dict[str, Any]:
        states = Counter(str(item.get("source_state")) for item in self.records)
        tiers = Counter(str(item.get("trust_tier")) for item in self.records)
        return {
            "seed_count": sum(not str(item.get("id", "")).startswith("discovered_") for item in self.records),
            "active_source_count": sum(bool(item.get("enabled")) for item in self.records),
            "discovered_candidate_count": states["DISCOVERED_CANDIDATE"],
            "verified_official_count": states["VERIFIED_OFFICIAL"] + states["MONITORABLE"],
            "monitorable_count": sum(
                bool(item.get("enabled"))
                and item.get("trust_tier") == "TIER_A_OFFICIAL"
                and item.get("source_state") in {"KNOWN_ACTIVE", "MONITORABLE"}
                for item in self.records
            ),
            "newly_learned_monitorable_count": states["MONITORABLE"],
            "by_state": {name: states[name] for name in sorted(SOURCE_STATES)},
            "by_trust_tier": {name: tiers[name] for name in sorted(TRUST_TIERS)},
        }

    def save(self) -> None:
        learned = [item for item in self.records if str(item.get("id", "")).startswith("discovered_") or item.get("learned_patterns") or item.get("verification_checks")]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary_name = tempfile.mkstemp(prefix="autonomous_sources_", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump({"schema_version": 1, "sources": learned}, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            Path(temporary_name).replace(self.path)
        finally:
            Path(temporary_name).unlink(missing_ok=True)

    def _load_seeds(self) -> list[dict[str, Any]]:
        try:
            payload = json.loads(self.seeds_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        output = []
        for raw in payload.get("seeds", []):
            if not isinstance(raw, dict):
                continue
            record = dict(raw)
            state = str(record.get("source_state") or ("KNOWN_ACTIVE" if record.get("enabled") else "KNOWN_INACTIVE"))
            record["source_state"] = state if state in SOURCE_STATES else "KNOWN_INACTIVE"
            record.setdefault("robots_status", "unknown")
            record.setdefault("last_checked", "")
            record.setdefault("last_success", "")
            record.setdefault("failure_count", 0)
            record.setdefault("parser_empty_count", 0)
            record.setdefault("learned_patterns", [])
            record.setdefault("official_evidence", [{"source_url": record.get("base_url", ""), "provenance": "bundled_registry"}])
            output.append(record)
        return output

    def _load_learned(self) -> list[dict[str, Any]]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        return [dict(item) for item in payload.get("sources", []) if isinstance(item, dict)]

    @staticmethod
    def _merge_records(seeds: list[dict[str, Any]], learned: list[dict[str, Any]]) -> list[dict[str, Any]]:
        output = [dict(item) for item in seeds]
        by_id = {str(item.get("id")): item for item in output}
        for item in learned:
            source_id = str(item.get("id"))
            if source_id in by_id:
                by_id[source_id].update(item)
            elif source_id:
                output.append(dict(item))
        return output

    def _by_host(self, host: str) -> dict[str, Any] | None:
        return next((item for item in self.records if host in {canonical_domain(value) for value in item.get("official_domains", [])} or canonical_host(item.get("base_url")) == host), None)

    def _by_id(self, source_id: str) -> dict[str, Any]:
        record = next((item for item in self.records if item.get("id") == source_id), None)
        if record is None:
            raise KeyError(source_id)
        return record
