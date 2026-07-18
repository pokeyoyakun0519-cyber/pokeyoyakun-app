from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


JST = timezone(timedelta(hours=9), name="JST")


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
    end = parse_jst_datetime(site.get("application_end_at"))
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
        return {
            "period_status": "受付中" if start else "締切日時不明",
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
