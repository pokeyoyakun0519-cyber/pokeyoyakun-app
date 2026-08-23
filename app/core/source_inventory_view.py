from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from core.application_filters import region_for_prefecture
from core.runtime_paths import app_root
from core.safe_product_url import can_open_product_url
from core.tcg_categories import display_name


STATUS_LABELS = {
    "CURRENT_APPLICATION": "応募受付中",
    "RECENTLY_ENDED": "最近終了",
    "NO_CURRENT_APPLICATION": "現在応募なし",
    "VERIFYING": "公式情報を確認中",
    "DISCOVERED_CANDIDATE": "新規候補",
    "DISCOVERED": "新規候補",
    "OFFICIAL_VERIFIED": "公式情報を確認済み",
    "MONITORABLE": "監視中",
    "APP_REQUIRED": "公式アプリ必須",
    "SNS_ONLY": "SNS情報のみ",
    "ROBOTS_BLOCKED": "自動確認に制限あり",
    "PARSER_NEEDED": "情報解析対応待ち",
    "HTTP_ERROR": "一時的に確認失敗",
    "UNSUPPORTED": "現在自動監視未対応",
    "TEMPORARILY_FAILED": "一時的に確認失敗",
}

STATUS_REASONS = {
    "CURRENT_APPLICATION": "公式情報で受付中の応募を確認しています",
    "RECENTLY_ENDED": "応募受付は終了しましたが、終了後14日以内の情報です",
    "NO_CURRENT_APPLICATION": "現在受付中の応募を確認できていません",
    "VERIFYING": "公式情報を確認中です",
    "DISCOVERED_CANDIDATE": "新しい店舗候補を発見し、公式情報を確認しています",
    "DISCOVERED": "新しい店舗候補を発見し、公式情報を確認しています",
    "OFFICIAL_VERIFIED": "公式店舗・公式サイトであることを確認済みです",
    "MONITORABLE": "保存済みの公式情報を定期的に確認しています",
    "APP_REQUIRED": "応募には公式アプリが必要です",
    "SNS_ONLY": "SNSのみで告知されています。公式Web情報も確認しています",
    "ROBOTS_BLOCKED": "このサイトは自動取得に制限があるため、別の公式情報源を探索中です",
    "PARSER_NEEDED": "公式ページの情報解析に対応中です",
    "HTTP_ERROR": "一時的に公式ページを確認できませんでした。次回再確認します",
    "UNSUPPORTED": "現在は自動監視に対応していません",
    "TEMPORARILY_FAILED": "一時的に確認できませんでした。次回再確認します",
}

FILTER_STATES = {
    "all": None,
    "current": {"CURRENT_APPLICATION"},
    "recent": {"RECENTLY_ENDED"},
    "none": {"NO_CURRENT_APPLICATION", "MONITORABLE", "OFFICIAL_VERIFIED"},
    "verifying": {"VERIFYING", "DISCOVERED_CANDIDATE", "DISCOVERED"},
    "app": {"APP_REQUIRED"},
    "sns": {"SNS_ONLY"},
    "restricted": {"ROBOTS_BLOCKED", "HTTP_ERROR", "TEMPORARILY_FAILED", "PARSER_NEEDED"},
    "unsupported": {"UNSUPPORTED"},
}

MONITORING_LABELS = {
    "WEB_DIRECT": "公式Webを確認", "WEB_FORM": "公式応募フォームを確認",
    "WEB_TO_STORE": "公式Webから店舗情報を確認", "STORE_DIRECT": "公式店舗情報を確認",
    "APP_REQUIRED": "公式アプリ案内を確認", "SNS_ONLY": "公式Web情報を探索中",
    "MANUFACTURER": "メーカー公式情報を確認", "RETAILER": "公式店舗情報を確認",
    "CARD_SHOP": "カードショップ公式情報を確認", "OFFICIAL_SHOP": "公式店舗情報を確認",
    "OFFICIAL_EC": "公式通販情報を確認", "DISCOVERY": "公開情報から公式ページを確認",
}


def coverage_path() -> Path:
    return app_root() / "data" / "production_coverage.json"


def load_saved_coverage(path: Path | None = None) -> dict[str, Any]:
    """Read the saved monitor snapshot. This function never performs Web I/O."""
    try:
        value = json.loads((path or coverage_path()).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        if path is not None:
            return {}
        try:
            from core.autonomous_source_registry import OfficialSourceCandidateStore
            from core.nationwide_web_monitor import NationwideWebApplicationMonitor
            from core.production_coverage import build_production_coverage
            from core.web_application_sources import WebApplicationSourceRegistry

            return build_production_coverage(
                [], registry=WebApplicationSourceRegistry(),
                autonomous_registry=OfficialSourceCandidateStore(),
                nationwide_diagnostics=NationwideWebApplicationMonitor.load_saved_diagnostics(),
            )
        except (OSError, TypeError, ValueError):
            return {}
    return value if isinstance(value, dict) else {}


def build_source_inventory_view(report: dict[str, Any]) -> dict[str, Any]:
    sources = [dict(row) for row in report.get("inventory", []) if isinstance(row, dict)]
    applications = [dict(row) for row in report.get("applications", []) if isinstance(row, dict)]
    apps_by_source: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for app in applications:
        apps_by_source.setdefault((str(app.get("tcg")), str(app.get("chain"))), []).append(app)

    rows: list[dict[str, Any]] = []
    covered_source_keys: set[tuple[str, str]] = set()
    for app in applications:
        key = (str(app.get("tcg")), str(app.get("chain")))
        covered_source_keys.add(key)
        source = next((item for item in sources if (str(item.get("tcg")), str(item.get("chain"))) == key), {})
        rows.append(_present_row(source, app))
    for source in sources:
        key = (str(source.get("tcg")), str(source.get("chain")))
        if key in covered_source_keys:
            continue
        rows.append(_present_row(source, None))

    unique: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for row in rows:
        key = (
            str(row.get("tcg")), str(row.get("chain")),
            str(row.get("branch")), str(row.get("official_url")),
        )
        existing = unique.get(key)
        if existing is None or _state_priority(row["state"]) > _state_priority(existing["state"]):
            unique[key] = row
    rows = sorted(unique.values(), key=lambda row: (
        -_state_priority(row["state"]), str(row["display_name"]),
        str(row["branch"]), str(row["tcg"]),
    ))
    state_counts = Counter(str(row["state"]) for row in rows)
    branch_keys = {(str(row["chain"]), str(row["branch"])) for row in rows}
    summary = {
        "chain_count": len({str(row["chain"]) for row in rows}),
        "branch_store_count": len(branch_keys),
        "source_count": len(sources),
        "current": state_counts["CURRENT_APPLICATION"],
        "recent": state_counts["RECENTLY_ENDED"],
        "no_current": sum(state_counts[name] for name in ("NO_CURRENT_APPLICATION", "MONITORABLE", "OFFICIAL_VERIFIED")),
        "verifying": sum(state_counts[name] for name in ("VERIFYING", "DISCOVERED_CANDIDATE", "DISCOVERED")),
        "app_required": state_counts["APP_REQUIRED"],
        "sns_only": state_counts["SNS_ONLY"],
        "restricted": sum(state_counts[name] for name in ("ROBOTS_BLOCKED", "HTTP_ERROR", "TEMPORARILY_FAILED")),
        "parser_needed": state_counts["PARSER_NEEDED"],
        "unsupported": state_counts["UNSUPPORTED"],
    }
    return {"rows": rows, "summary": summary, "generated_at": str(report.get("generated_at") or "")}


def filter_source_inventory(
    rows: list[dict[str, Any]], *, state_filter: str = "all", tcg: str = "all",
    region: str = "all", prefecture: str = "all", chain: str = "all", keyword: str = "",
) -> list[dict[str, Any]]:
    allowed = FILTER_STATES.get(state_filter)
    needle = str(keyword or "").strip().casefold()
    return [
        row for row in rows
        if (allowed is None or row.get("state") in allowed)
        and (tcg == "all" or row.get("tcg") == tcg)
        and (region == "all" or row.get("region") == region)
        and (prefecture == "all" or row.get("prefecture") == prefecture)
        and (chain == "all" or row.get("chain") == chain)
        and (not needle or needle in " ".join((
            str(row.get("display_name", "")), str(row.get("chain", "")),
            str(row.get("branch", "")),
        )).casefold())
    ]


def _present_row(source: dict[str, Any], application: dict[str, Any] | None) -> dict[str, Any]:
    application = application or {}
    state = str(application.get("state") or source.get("state") or "DISCOVERED_CANDIDATE")
    prefecture = str(application.get("prefecture") or "")
    if not prefecture:
        values = source.get("prefectures", [])
        prefecture = str(values[0]) if isinstance(values, list) and len(values) == 1 else "UNKNOWN"
    official_url = str(application.get("official_url") or source.get("official_url") or "")
    tcg = str(application.get("tcg") or source.get("tcg") or "other")
    chain = str(application.get("chain") or source.get("chain") or "unknown")
    branch = str(application.get("branch") or "支店情報未取得")
    is_application = state in {"CURRENT_APPLICATION", "RECENTLY_ENDED"}
    return {
        "display_name": str(source.get("display_name") or chain),
        "chain": chain, "branch": branch, "tcg": tcg,
        "tcg_label": display_name(tcg), "prefecture": prefecture,
        "region": region_for_prefecture(prefecture), "state": state,
        "status_label": STATUS_LABELS.get(state, "確認状況不明"),
        "reason": STATUS_REASONS.get(state, "保存済み情報を確認しています"),
        "last_check": str(source.get("last_check") or source.get("last_success") or "未確認"),
        "discovered_from": _discovery_label(source),
        "official_url": official_url,
        "official_url_safe": can_open_product_url(official_url),
        "dashboard_listed": is_application,
        "monitored": state in {"CURRENT_APPLICATION", "RECENTLY_ENDED", "NO_CURRENT_APPLICATION", "MONITORABLE"},
        "verified_official": state in {"CURRENT_APPLICATION", "RECENTLY_ENDED", "NO_CURRENT_APPLICATION", "MONITORABLE", "OFFICIAL_VERIFIED"},
        "current_application_count": int(state == "CURRENT_APPLICATION"),
        "recently_ended_count": int(state == "RECENTLY_ENDED"),
        "monitoring_type": _monitoring_label(
            source.get("monitoring_type") or source.get("source_class")
            or source.get("monitor_type")
        ),
        "monitoring_restriction": state == "ROBOTS_BLOCKED",
        "parser_status": "対応待ち" if state == "PARSER_NEEDED" else "確認済み" if state in {"CURRENT_APPLICATION", "RECENTLY_ENDED", "NO_CURRENT_APPLICATION"} else "確認中",
        "application_status": "掲載" if is_application else "未掲載",
    }


def _discovery_label(source: dict[str, Any]) -> str:
    value = str(source.get("discovered_from") or source.get("seed_type") or "").upper()
    if value in {"MANUFACTURER", "OFFICIAL_SHOP", "OFFICIAL_EC"}:
        return "メーカー・公式サイト"
    if value in {"RETAILER", "CARD_SHOP", "MALL"}:
        return "公式店舗情報"
    if value == "DISCOVERY":
        return "公開情報から発見"
    return "登録済み監視候補"


def _monitoring_label(value: object) -> str:
    return MONITORING_LABELS.get(str(value or "").upper(), "確認方法を整理中")


def _state_priority(state: str) -> int:
    return {
        "CURRENT_APPLICATION": 100, "RECENTLY_ENDED": 90,
        "VERIFYING": 80, "DISCOVERED_CANDIDATE": 75, "DISCOVERED": 75,
        "APP_REQUIRED": 70, "SNS_ONLY": 65, "ROBOTS_BLOCKED": 60,
        "PARSER_NEEDED": 55, "HTTP_ERROR": 50, "TEMPORARILY_FAILED": 50,
        "NO_CURRENT_APPLICATION": 40, "MONITORABLE": 35,
        "OFFICIAL_VERIFIED": 30, "UNSUPPORTED": 10,
    }.get(state, 0)
