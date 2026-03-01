"""Deterministic intent parser for toy portal natural-language sales questions."""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date
from typing import Literal

ToyQueryType = Literal["sales_month", "sales_range"]
ToyGroupBy = Literal["source_channel", "agency"]

_MONTH_TOKEN_TO_NUMBER = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}
_MONTH_NAMES_REGEX = (
    r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?"
)
_MONTH_YEAR_RE = re.compile(rf"\b({_MONTH_NAMES_REGEX})\b[\s,/-]*(20\d{{2}})\b", re.IGNORECASE)
_YEAR_MONTH_RE = re.compile(r"\b(20\d{2})-(0[1-9]|1[0-2])\b")
_DATE_RANGE_RE = re.compile(
    r"\b(20\d{2}-\d{2}-\d{2})\b\s*(?:to|through|thru|until|-)\s*\b(20\d{2}-\d{2}-\d{2})\b",
    re.IGNORECASE,
)
_EXAMPLES = [
    "march 2025 sales data",
    "sales for March 2025",
    "sales by source channel for March 2025",
    "export March 2025 sales redacted",
    "sales from 2025-03-01 to 2025-03-31",
]


@dataclass(frozen=True)
class ToyQuerySpec:
    query_type: ToyQueryType
    year: int | None = None
    month: int | None = None
    start: date | None = None
    end: date | None = None
    group_by: ToyGroupBy | None = None
    redact_pii: bool = False
    original_text: str = ""

    def resolved_range(self) -> tuple[date, date]:
        if self.query_type == "sales_range":
            if self.start is None or self.end is None:
                raise ValueError("sales_range requires start and end")
            return self.start, self.end
        if self.year is None or self.month is None:
            raise ValueError("sales_month requires year and month")
        first = date(self.year, self.month, 1)
        last_day = calendar.monthrange(self.year, self.month)[1]
        last = date(self.year, self.month, last_day)
        return first, last

    def to_dict(self) -> dict[str, object]:
        start, end = self.resolved_range()
        return {
            "query_type": self.query_type,
            "year": self.year,
            "month": self.month,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "group_by": self.group_by,
            "redact_pii": self.redact_pii,
            "original_text": self.original_text,
        }


def _parse_date(text: str) -> date:
    try:
        return date.fromisoformat(str(text))
    except Exception as exc:
        raise ValueError(f"invalid date: {text!r}, expected YYYY-MM-DD") from exc


def _extract_group_by(lowered: str) -> ToyGroupBy | None:
    if "source channel" in lowered or "by source" in lowered or "by channel" in lowered:
        return "source_channel"
    if "by agency" in lowered or "by agencies" in lowered:
        return "agency"
    return None


def _extract_redact(lowered: str) -> bool:
    return ("redact" in lowered) or ("redacted" in lowered)


def parse_toy_query(text: str) -> ToyQuerySpec:
    """Deterministically parse toy sales questions into a structured ToyQuerySpec."""

    cleaned = str(text or "").strip()
    if not cleaned:
        raise ValueError("query text cannot be empty")

    lowered = cleaned.lower()
    if "sales" not in lowered:
        raise ValueError(
            "Unsupported query. This interface only supports sales questions. "
            f"Examples: {', '.join(_EXAMPLES)}"
        )

    group_by = _extract_group_by(lowered)
    redact_pii = _extract_redact(lowered)

    range_match = _DATE_RANGE_RE.search(cleaned)
    if range_match:
        start = _parse_date(range_match.group(1))
        end = _parse_date(range_match.group(2))
        if end < start:
            raise ValueError("date range end must be >= start")
        return ToyQuerySpec(
            query_type="sales_range",
            start=start,
            end=end,
            group_by=group_by,
            redact_pii=redact_pii,
            original_text=cleaned,
        )

    month_match = _MONTH_YEAR_RE.search(cleaned)
    if month_match:
        token = month_match.group(1).strip().lower()
        year = int(month_match.group(2))
        month = _MONTH_TOKEN_TO_NUMBER.get(token)
        if month is None:
            raise ValueError(f"unsupported month token: {token!r}")
        return ToyQuerySpec(
            query_type="sales_month",
            year=year,
            month=month,
            group_by=group_by,
            redact_pii=redact_pii,
            original_text=cleaned,
        )

    year_month_match = _YEAR_MONTH_RE.search(cleaned)
    if year_month_match:
        year = int(year_month_match.group(1))
        month = int(year_month_match.group(2))
        return ToyQuerySpec(
            query_type="sales_month",
            year=year,
            month=month,
            group_by=group_by,
            redact_pii=redact_pii,
            original_text=cleaned,
        )

    raise ValueError("Unsupported toy sales query. Try one of: " + "; ".join(f"'{s}'" for s in _EXAMPLES))
