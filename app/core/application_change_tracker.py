from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from core.runtime_paths import app_root
from core.application_period import ApplicationPeriodParser


class ApplicationChangeTracker:
    FIELDS = {
        "application_start_at": "応募開始",
        "application_end_at": "応募締切",
        "result_announcement_at": "結果発表",
        "application_method": "受付方式",
        "application_conditions": "条件",
        "application_url": "URL",
        "status": "状態",
    }
    IMPORTANT_FIELDS = {"application_end_at", "result_announcement_at", "application_url", "status"}

    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root is not None else app_root()
        self.path = self.root / "data" / "application_change_history.json"

    def compare_and_update(self, products: list[dict[str, Any]], *, now: datetime | None = None) -> list[dict[str, Any]]:
        checked_at = (now or datetime.now()).isoformat(timespec="seconds")
        state = self._load()
        snapshots = dict(state.get("snapshots", {}))
        events = list(state.get("events", []))
        changes = []
        for product in products:
            for site in product.get("sites", []):
                key = self.item_key(product, site)
                normalized_site = ApplicationPeriodParser().enrich_site(
                    dict(site),
                    "\n".join(
                        str(site.get(field, ""))
                        for field in (
                            "application_period", "order_period", "result_date",
                            "notice", "text", "description",
                        )
                        if site.get(field)
                    ),
                    now=now,
                    release_date=str(product.get("release_date", "")),
                )
                current = self._snapshot(normalized_site)
                previous = snapshots.get(key)
                changed_fields = {}
                if isinstance(previous, dict):
                    for field, label in self.FIELDS.items():
                        before = str(previous.get(field, ""))
                        after = str(current.get(field, ""))
                        if before != after:
                            changed_fields[field] = {"label": label, "before": before, "after": after}
                if changed_fields:
                    event_id = hashlib.sha256(
                        (key + "|" + json.dumps(changed_fields, ensure_ascii=False, sort_keys=True)).encode("utf-8")
                    ).hexdigest()[:24]
                    if not any(event.get("id") == event_id for event in events):
                        event = {
                            "id": event_id,
                            "item_key": key,
                            "product_id": str(product.get("id", "")),
                            "product_name": str(product.get("name", "商品名未設定")),
                            "site_key": str(site.get("site_key", "")),
                            "site_name": str(site.get("name", "店舗名未設定")),
                            "application_url": current.get("application_url", ""),
                            "changes": changed_fields,
                            "important": bool(set(changed_fields) & self.IMPORTANT_FIELDS),
                            "detected_at": checked_at,
                            "notified": False,
                        }
                        events.insert(0, event)
                        changes.append(event)
                snapshots[key] = current
        self._save({"snapshots": snapshots, "events": events[:500]})
        return changes

    def latest_by_key(self, *, max_age_days: int = 14) -> dict[str, dict[str, Any]]:
        cutoff = datetime.now() - timedelta(days=max_age_days)
        output = {}
        for event in self._load().get("events", []):
            try:
                detected = datetime.fromisoformat(str(event.get("detected_at", "")))
            except ValueError:
                continue
            if detected < cutoff:
                continue
            output.setdefault(str(event.get("item_key", "")), event)
        return output

    def pending_notifications(self, *, important_only: bool) -> list[dict[str, Any]]:
        return [
            event for event in self._load().get("events", [])
            if not event.get("notified") and (event.get("important") or not important_only)
        ]

    def mark_notified(self, event_ids: list[str]) -> None:
        if not event_ids:
            return
        state = self._load()
        ids = set(event_ids)
        for event in state.get("events", []):
            if event.get("id") in ids:
                event["notified"] = True
                event["notified_at"] = datetime.now().isoformat(timespec="seconds")
        self._save(state)

    @classmethod
    def item_key(cls, product: dict[str, Any], site: dict[str, Any]) -> str:
        return "|".join((
            str(product.get("id", "")), str(site.get("site_key", "")),
            str(site.get("url", site.get("application_url", ""))),
        ))

    @classmethod
    def _snapshot(cls, site: dict[str, Any]) -> dict[str, str]:
        value = {field: str(site.get(field, "")) for field in cls.FIELDS}
        value["application_url"] = str(site.get("application_url", site.get("url", "")))
        return value

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"snapshots": {}, "events": []}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"snapshots": {}, "events": []}
        return data if isinstance(data, dict) else {"snapshots": {}, "events": []}

    def _save(self, state: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)
