from __future__ import annotations

import logging
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Any


JST = timezone(timedelta(hours=9), name="JST")
LOGGER = logging.getLogger(__name__)

_END_FLAGS = (
    "application_ended",
    "reception_ended",
    "period_ended",
    "is_ended",
    "is_closed",
    "ended",
)
_STATUS_FIELDS = ("status", "application_status", "reception_status")
_SOURCE_STATUS_FIELDS = (
    "source_status",
    "latest_source_status",
    "status_history",
    "application_status_history",
)
_END_STATUSES = {
    "終了済み",
    "受付終了",
    "応募終了",
    "予約終了",
    "抽選終了",
    "販売終了",
    "closed",
    "ended",
    "expired",
    "中止",
    "キャンセル",
    "受付中止",
    "抽選中止",
    "予約中止",
}
_PLANNED_END = re.compile(r"終了(?:する)?(?:予定|見込|見込み|予告)")
_END_PHRASE = re.compile(
    r"(?:応募受付|申込受付|申し込み受付|受付|応募|予約|抽選(?:販売)?|販売)"
    r"(?:は|が|を)?(?:終了済み|終了しました|終了いたしました|終了しております|"
    r"終了しています|終了となりました|終了となっています)"
)


def parse_jst_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=JST)
    return parsed.astimezone(JST)


def evaluate_application_period(
    site: dict[str, Any], *, now: datetime | None = None
) -> dict[str, Any]:
    current = now or datetime.now(JST)
    if current.tzinfo is None:
        current = current.replace(tzinfo=JST)
    else:
        current = current.astimezone(JST)

    start = parse_jst_datetime(site.get("application_start_at"))
    end = _application_end(site, current)
    explicit_end = _explicit_end_source(site)
    if explicit_end:
        if end and current <= end:
            LOGGER.warning(
                "明示的終了状態を未来の応募締切より優先します: %s end=%s",
                explicit_end,
                end.isoformat(),
            )
        return {
            "period_status": "終了済み",
            "period_ended": True,
            "remaining_text": "受付終了",
            "end_reason": f"明示的な終了状態: {explicit_end}",
        }
    if end and current > end:
        return {
            "period_status": "終了済み",
            "period_ended": True,
            "remaining_text": "受付終了",
            "end_reason": "応募締切日時を過ぎました",
        }
    if start and current < start:
        return {
            "period_status": "受付前",
            "period_ended": False,
            "remaining_text": f"{start:%m/%d %H:%M}受付開始",
            "end_reason": "",
        }
    if not end:
        explicit_open = _explicit_open_status(site)
        return {
            "period_status": explicit_open or ("受付中" if start else "締切日時不明"),
            "period_ended": False,
            "remaining_text": "締切日時を確認できません",
            "end_reason": "",
        }
    remaining = end - current
    if end.date() == current.date():
        text = f"本日{end:%H:%M}締切"
        status = "本日締切"
    elif remaining < timedelta(days=1):
        hours = max(1, int(remaining.total_seconds() // 3600))
        text = f"あと{hours}時間"
        status = "受付中"
    else:
        text = f"あと{max(1, remaining.days)}日"
        status = "受付中"
    return {
        "period_status": status,
        "period_ended": False,
        "remaining_text": text,
        "end_reason": "",
    }


def _application_end(site: dict[str, Any], current: datetime) -> datetime | None:
    raw_at = str(site.get("application_end_at") or "").strip()
    if raw_at and re.search(r"(?:T|\s)\d{1,2}(?::|時)\d{0,2}", raw_at):
        return parse_jst_datetime(raw_at)
    raw = raw_at or str(site.get("application_end") or "").strip()
    if not raw:
        return None
    # application_end is already a semantic deadline field.  Parsing it does
    # not permit unrelated release dates to become deadlines.
    from core.application_period import ApplicationPeriodParser

    parsed = ApplicationPeriodParser.parse(
        "応募締切 " + raw,
        now=current,
        release_date=str(site.get("release_date") or ""),
    )
    return parse_jst_datetime(parsed.get("application_end_at"))


def _explicit_end_source(site: dict[str, Any]) -> str:
    for field in _END_FLAGS:
        if site.get(field) is True:
            return f"{field}=true"
    for field in (*_STATUS_FIELDS, *_SOURCE_STATUS_FIELDS):
        for value in _status_values(site.get(field)):
            if _is_ended_status(value):
                return f"{field}={value}"
    return ""


def _explicit_open_status(site: dict[str, Any]) -> str:
    for field in _STATUS_FIELDS:
        for value in _status_values(site.get(field)):
            text = _normalize_status(value)
            if re.search(r"受付前|受付予定|開始前", text):
                return "受付前"
            if re.search(r"受付中|応募中|予約受付中|抽選受付中", text):
                return "受付中"
    return ""


def _is_ended_status(value: object) -> bool:
    text = _normalize_status(value)
    if not text or _PLANNED_END.search(text):
        return False
    compact = re.sub(r"^[※*＊・:：\-\s]+|[。.!！\s]+$", "", text)
    return compact in _END_STATUSES or bool(_END_PHRASE.search(compact))


def _normalize_status(value: object) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).strip().casefold()


def _status_values(value: object):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key in (*_STATUS_FIELDS, "source_status"):
            yield from _status_values(value.get(key))
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _status_values(item)
