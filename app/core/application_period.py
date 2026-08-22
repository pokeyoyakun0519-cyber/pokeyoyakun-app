from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Any


JST = timezone(timedelta(hours=9), "JST")
PERIOD_KEYWORDS = (
    "応募", "抽選", "予約", "受付", "申込", "申し込み", "締切", "結果発表", "当選発表"
)
DATE_TOKEN = (
    r"(?:(?P<{p}year>20\d{{2}})年\s*)?"
    r"(?P<{p}month>\d{{1,2}})月\s*(?P<{p}day>\d{{1,2}})日"
    r"(?:\s*\([^)]*\))?"
    r"(?:\s*(?P<{p}hour>\d{{1,2}}):(?P<{p}minute>\d{{2}}))?"
)
RANGE_RE = re.compile(
    DATE_TOKEN.format(p="start")
    + r"\s*(?:から|～|〜|~|－|―|-)\s*"
    + DATE_TOKEN.format(p="end"),
    re.IGNORECASE,
)
SINGLE_DATE_RE = re.compile(DATE_TOKEN.format(p="single"), re.IGNORECASE)


class ApplicationPeriodParser:
    """公開ページの応募・予約期間を日本時間へ正規化する。"""

    @classmethod
    def parse(
        cls,
        text: str,
        *,
        now: datetime | None = None,
        release_date: str = "",
    ) -> dict[str, Any]:
        current = cls._as_jst(now or datetime.now(JST))
        release = cls._parse_release_date(release_date)
        normalized = cls._normalize_notation(str(text or ""))
        relevant = cls._relevant_text(normalized)
        result: dict[str, Any] = {
            "application_start_at": "",
            "application_end_at": "",
            "result_announcement_at": "",
            "application_method": cls._method(relevant),
            "application_conditions": cls._label_value(relevant, ("応募条件", "申込条件", "受付条件")),
            "target_store": cls._label_value(relevant, ("対象店舗", "受付店舗", "実施店舗")),
            "period_evidence": "",
            "period_unknown": bool(re.search(r"(?:受付|応募|申込)期間\s*[:：]?\s*未定", relevant)),
            "application_end_time_confirmed": False,
        }

        range_match = RANGE_RE.search(relevant)
        if range_match:
            start = cls._match_datetime(range_match, "start", current.date(), release, is_end=False)
            end = cls._match_datetime(range_match, "end", current.date(), release, is_end=True)
            if start and end and end < start and range_match.group("endyear") is None:
                try:
                    end = end.replace(year=end.year + 1)
                except ValueError:
                    end = None
            if start and end:
                result["application_start_at"] = start.isoformat()
                result["application_end_at"] = end.isoformat()
                result["application_end_time_confirmed"] = bool(
                    range_match.group("endhour")
                )
                result["period_evidence"] = cls._sanitize(range_match.group(0))

        if not result["application_end_at"]:
            end_match = cls._find_labeled_date(
                relevant,
                r"(?:応募|抽選|予約|申込|受付)?\s*(?:締切|終了)(?:日時)?|(?:応募|抽選|予約|申込|受付)[^。\n]{0,16}?まで",
            )
            if end_match:
                end = cls._match_datetime(end_match, "single", current.date(), release, is_end=True)
                if end:
                    result["application_end_at"] = end.isoformat()
                    result["application_end_time_confirmed"] = bool(
                        end_match.group("singlehour")
                    )
                    result["period_evidence"] = cls._sanitize(end_match.group(0))

        if not result["application_start_at"]:
            start_match = cls._find_labeled_date(
                relevant,
                r"(?:応募|抽選|予約|申込|受付)(?:開始|開始日時|開始日|受付開始)",
            )
            if start_match:
                start = cls._match_datetime(start_match, "single", current.date(), release, is_end=False)
                if start:
                    result["application_start_at"] = start.isoformat()
                    result["period_evidence"] = result["period_evidence"] or cls._sanitize(start_match.group(0))

        result_match = cls._find_labeled_date(
            relevant,
            r"(?:結果発表予定|抽選結果発表|結果発表|当選発表)(?:日時|日)?",
        )
        if result_match:
            announcement = cls._match_datetime(
                result_match, "single", current.date(), release, is_end=True
            )
            if announcement:
                result["result_announcement_at"] = announcement.isoformat()

        return result

    @classmethod
    def enrich_site(
        cls,
        site: dict[str, Any],
        text: str,
        *,
        now: datetime | None = None,
        release_date: str = "",
    ) -> dict[str, Any]:
        enriched = dict(site)
        evidence_text = str(text or "")
        explicit_end = str(
            site.get("application_end_at") or site.get("application_end") or ""
        ).strip()
        if explicit_end and cls._has_time(explicit_end):
            enriched.setdefault("application_end_time_confirmed", True)
        if explicit_end and not cls._has_time(explicit_end):
            evidence_text += "\n応募締切 " + explicit_end
        parsed = cls.parse(evidence_text, now=now, release_date=release_date)
        for key, value in parsed.items():
            if value not in ("", False):
                enriched[key] = value
            elif key not in enriched:
                enriched[key] = value
        enriched.setdefault("period_source", str(site.get("name", "")))
        enriched.setdefault("period_checked_at", (now or datetime.now(JST)).astimezone(JST).isoformat(timespec="seconds"))
        return enriched

    @staticmethod
    def _has_time(value: str) -> bool:
        return bool(re.search(r"(?:T|\s)\d{1,2}(?::|時)\d{0,2}", str(value)))

    @staticmethod
    def _normalize_notation(text: str) -> str:
        text = re.sub(
            r"(\d{1,2})時\s*(\d{1,2})分",
            lambda match: f"{match.group(1)}:{int(match.group(2)):02d}",
            text,
        )
        text = re.sub(
            r"(?:(20\d{2})[./-])?(\d{1,2})[./-](\d{1,2})(?:\s*\([^)]*\))?",
            lambda match: (
                (match.group(1) + "年" if match.group(1) else "")
                + match.group(2) + "月" + match.group(3) + "日"
            ),
            text,
        )
        return re.sub(r"[\t\r ]+", " ", text)

    @staticmethod
    def _relevant_text(text: str) -> str:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        selected = [line for line in lines if any(keyword in line for keyword in PERIOD_KEYWORDS)]
        if selected:
            return "\n".join(selected[:80])
        return ""

    @classmethod
    def _find_labeled_date(cls, text: str, label_pattern: str):
        after = re.compile(
            rf"(?:{label_pattern})\s*[:：]?\s*(?:は\s*)?" + DATE_TOKEN.format(p="single"),
            re.IGNORECASE,
        ).search(text)
        if after:
            return after
        return re.compile(
            DATE_TOKEN.format(p="single") + rf"\s*(?:まで)?[^。\n]{{0,12}}(?:{label_pattern})",
            re.IGNORECASE,
        ).search(text)

    @classmethod
    def _match_datetime(
        cls,
        match,
        prefix: str,
        current: date,
        release: date | None,
        *,
        is_end: bool,
    ) -> datetime | None:
        try:
            month = int(match.group(prefix + "month"))
            day = int(match.group(prefix + "day"))
            explicit_year = match.group(prefix + "year")
            year = int(explicit_year) if explicit_year else cls._infer_year(month, day, current, release)
            if year is None:
                return None
            hour_text = match.group(prefix + "hour")
            minute_text = match.group(prefix + "minute")
            if hour_text is None:
                clock = time(23, 59, 59) if is_end else time(0, 0)
            else:
                clock = time(int(hour_text), int(minute_text or 0), 59 if is_end else 0)
            return datetime.combine(date(year, month, day), clock, JST)
        except (TypeError, ValueError, IndexError):
            return None

    @staticmethod
    def _infer_year(month: int, day: int, current: date, release: date | None) -> int | None:
        candidates = []
        for year in {current.year - 1, current.year, current.year + 1, release.year if release else current.year}:
            try:
                candidate = date(year, month, day)
            except ValueError:
                continue
            if release:
                distance = abs((release - candidate).days)
                if candidate > release + timedelta(days=45) or candidate < release - timedelta(days=400):
                    distance += 1000
            else:
                distance = abs((candidate - current).days)
                if candidate < current - timedelta(days=120):
                    distance += 365
            candidates.append((distance, year))
        return min(candidates)[1] if candidates else None

    @staticmethod
    def _parse_release_date(value: str) -> date | None:
        try:
            return date.fromisoformat(str(value).strip())
        except ValueError:
            return None

    @staticmethod
    def _as_jst(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=JST)
        return value.astimezone(JST)

    @staticmethod
    def _method(text: str) -> str:
        if re.search(r"(?:公式)?アプリ", text):
            return "アプリ受付"
        if "店頭" in text:
            return "店頭受付"
        if "抽選" in text:
            return "抽選"
        if "予約" in text:
            return "予約"
        if "先着" in text:
            return "先着"
        return ""

    @classmethod
    def _label_value(cls, text: str, labels: tuple[str, ...]) -> str:
        for label in labels:
            match = re.search(re.escape(label) + r"\s*[:：]?\s*([^\n。]{2,200})", text)
            if match:
                return cls._sanitize(match.group(1))
        return ""

    @staticmethod
    def _sanitize(value: str) -> str:
        clean = re.sub(r"[\w.+-]+@[\w.-]+", "[メール非保存]", value)
        clean = re.sub(r"\b[A-Za-z0-9_-]{24,}\b", "[識別情報非保存]", clean)
        clean = re.sub(r"\s+", " ", clean).strip()
        return clean[:300]
