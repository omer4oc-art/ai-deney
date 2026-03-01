"""Intent parsing + strict validation for toy portal natural-language questions."""

from __future__ import annotations

import calendar
import json
import os
import re
from dataclasses import dataclass
from datetime import date
from typing import Callable, Literal, Mapping

ReportType = Literal[
    "sales_range",
    "sales_month",
    "sales_by_channel",
    "sales_day",
    "sales_for_dates",
    "occupancy_range",
    "reservations_list",
    "export_reservations",
]
GroupBy = Literal["day", "channel"]
FormatType = Literal["md", "html"]
IntentMode = Literal["deterministic", "llm"]

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
_YEAR_MONTH_RE = re.compile(r"\b(20\d{2})-(0[1-9]|1[0-2])\b(?!-\d{2})")
_DATE_RANGE_RE = re.compile(
    r"\b(20\d{2}-\d{2}-\d{2})\b\s*(?:to|through|thru|until|-)\s*\b(20\d{2}-\d{2}-\d{2})\b",
    re.IGNORECASE,
)
_ISO_DATE_RE = re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b")
_MONTH_DAY_RE = re.compile(
    rf"\b({_MONTH_NAMES_REGEX})\s+([0-3]?\d)(?:st|nd|rd|th)?(?:\s*,?\s*(?:\(?\s*(20\d{{2}})\s*\)?))?\b",
    re.IGNORECASE,
)
_COMPARE_RE = re.compile(r"\b(compare|vs|versus|difference|delta)\b", re.IGNORECASE)

_ALLOWED_KEYS = {
    "report_type",
    "start_date",
    "end_date",
    "year",
    "month",
    "group_by",
    "dates",
    "spans",
    "compare",
    "redact_pii",
    "format",
}
_RANGE_REQUIRED_REPORTS = {
    "sales_range",
    "sales_by_channel",
    "occupancy_range",
    "reservations_list",
    "export_reservations",
}

_EXAMPLES = [
    "sales by channel for March 2025",
    "sales from 2025-03-01 to 2025-03-31",
    "total sales on March 1st 2025 and June 3rd 2025",
    "compare March 2025 vs June 2025 sales",
    "sales from 2025-03-01 to 2025-03-07 and 2025-06-01 to 2025-06-07",
    "compare March 1 vs June 3",
    "occupancy for March 2025",
    "list reservations from 2025-03-01 to 2025-03-15",
    "export reservations for March 2025",
]


@dataclass(frozen=True)
class QuerySpan:
    start_date: str
    end_date: str
    label: str

    def to_dict(self) -> dict[str, str]:
        return {
            "start_date": self.start_date,
            "end_date": self.end_date,
            "label": self.label,
        }


@dataclass(frozen=True)
class QuerySpec:
    report_type: ReportType
    start_date: str | None = None
    end_date: str | None = None
    year: int | None = None
    month: int | None = None
    group_by: GroupBy | None = None
    dates: tuple[str, ...] = ()
    spans: tuple[QuerySpan, ...] = ()
    compare: bool = False
    redact_pii: bool = True
    format: FormatType = "md"

    def resolved_range(self) -> tuple[date, date]:
        if self.start_date is not None and self.end_date is not None:
            return _parse_date(self.start_date), _parse_date(self.end_date)
        if self.spans:
            return _parse_date(self.spans[0].start_date), _parse_date(self.spans[-1].end_date)
        if self.report_type == "sales_for_dates" and self.dates:
            return _parse_date(self.dates[0]), _parse_date(self.dates[-1])
        raise ValueError("query spec has no resolved start_date/end_date")

    def to_dict(self) -> dict[str, object]:
        return {
            "report_type": self.report_type,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "year": self.year,
            "month": self.month,
            "group_by": self.group_by,
            "dates": list(self.dates),
            "spans": [span.to_dict() for span in self.spans],
            "compare": self.compare,
            "redact_pii": self.redact_pii,
            "format": self.format,
        }


ToyQuerySpec = QuerySpec


@dataclass(frozen=True)
class ToyParseResult:
    spec: QuerySpec
    raw_llm_json: dict[str, object] | None
    intent_mode: IntentMode
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class ToyPlanResult:
    spec: QuerySpec | None
    plan: tuple[QuerySpec, ...]
    compare: bool
    raw_llm_json: dict[str, object] | None
    intent_mode: IntentMode
    warnings: tuple[str, ...] = ()


ToyLLMRouter = Callable[[str], Mapping[str, object] | str]


def resolve_intent_mode(intent_mode: str | None = None) -> IntentMode:
    raw = (intent_mode or os.getenv("AI_DENEY_TOY_INTENT_MODE", "deterministic")).strip().lower()
    if raw in {"", "deterministic"}:
        return "deterministic"
    if raw == "llm":
        return "llm"
    raise ValueError("AI_DENEY_TOY_INTENT_MODE must be 'deterministic' or 'llm'")


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except Exception as exc:
        raise ValueError(f"invalid date: {value!r}, expected YYYY-MM-DD") from exc


def _month_range(year: int, month: int) -> tuple[str, str]:
    first = date(year, month, 1)
    last_day = calendar.monthrange(year, month)[1]
    last = date(year, month, last_day)
    return first.isoformat(), last.isoformat()


def _extract_month_year(text: str) -> tuple[int | None, int | None]:
    month_match = _MONTH_YEAR_RE.search(text)
    if month_match:
        token = month_match.group(1).strip().lower()
        month = _MONTH_TOKEN_TO_NUMBER.get(token)
        if month is None:
            raise ValueError(f"unsupported month token: {token!r}")
        return int(month_match.group(2)), month

    year_month_match = _YEAR_MONTH_RE.search(text)
    if year_month_match:
        return int(year_month_match.group(1)), int(year_month_match.group(2))

    return None, None


def _extract_group_by(lowered: str) -> GroupBy | None:
    if "by channel" in lowered or "by source channel" in lowered or "channel breakdown" in lowered:
        return "channel"
    if "by day" in lowered or "daily" in lowered:
        return "day"
    return None


def _extract_redact(lowered: str) -> bool:
    if "without redaction" in lowered or "unredacted" in lowered or "redact off" in lowered:
        return False
    if "redact" in lowered:
        return True
    return True


def _extract_format(lowered: str) -> FormatType:
    if " html" in f" {lowered}" or lowered.endswith("html"):
        return "html"
    return "md"


def _extract_compare(lowered: str) -> bool:
    return bool(_COMPARE_RE.search(lowered))


def _default_span_label(start_date: str, end_date: str) -> str:
    if start_date == end_date:
        return start_date
    return f"{start_date}..{end_date}"


def _extract_date_points_in_order(text: str) -> tuple[list[str], list[str]]:
    warnings: list[str] = []
    collected: list[tuple[int, str]] = []

    for match in _ISO_DATE_RE.finditer(text):
        iso = match.group(1)
        parsed = _parse_date(iso)
        collected.append((int(match.start()), parsed.isoformat()))

    month_day_tokens: list[tuple[int, int, int | None, int]] = []
    explicit_years: set[int] = set()
    for match in _MONTH_DAY_RE.finditer(text):
        token = str(match.group(1)).strip().lower()
        month = _MONTH_TOKEN_TO_NUMBER.get(token)
        if month is None:
            continue
        day = int(match.group(2))
        year_val = int(match.group(3)) if match.group(3) else None
        if year_val is not None:
            explicit_years.add(year_val)
        month_day_tokens.append((month, day, year_val, int(match.start())))

    inferred_year: int | None = next(iter(explicit_years)) if len(explicit_years) == 1 else None
    used_default_year = False
    for month, day, year_val, start_pos in month_day_tokens:
        year = year_val
        if year is None:
            if inferred_year is not None:
                year = inferred_year
            else:
                year = 2025
                used_default_year = True
        try:
            parsed = date(year, month, day)
        except Exception as exc:
            raise ValueError(f"invalid month/day date: {month:02d}-{day:02d} ({year})") from exc
        collected.append((start_pos, parsed.isoformat()))

    if used_default_year:
        warnings.append("Year omitted for one or more month/day dates; defaulted to 2025.")

    collected.sort(key=lambda item: item[0])
    ordered_unique: list[str] = []
    seen: set[str] = set()
    for _pos, iso in collected:
        if iso in seen:
            continue
        ordered_unique.append(iso)
        seen.add(iso)
    return ordered_unique, warnings


def _extract_date_points(text: str) -> tuple[list[str], list[str]]:
    points, warnings = _extract_date_points_in_order(text)
    return sorted(points), warnings


def _extract_multi_range_spans(text: str) -> list[dict[str, str]]:
    spans: list[dict[str, str]] = []
    for match in _DATE_RANGE_RE.finditer(text):
        parsed_start = _parse_date(match.group(1))
        parsed_end = _parse_date(match.group(2))
        if parsed_end < parsed_start:
            raise ValueError("date range end must be >= start")
        start_iso = parsed_start.isoformat()
        end_iso = parsed_end.isoformat()
        spans.append(
            {
                "start_date": start_iso,
                "end_date": end_iso,
                "label": _default_span_label(start_iso, end_iso),
            }
        )
    return spans


def _extract_month_spans(text: str) -> list[dict[str, str]]:
    matches: list[tuple[int, str, str, str]] = []
    for match in _MONTH_YEAR_RE.finditer(text):
        token = str(match.group(1)).strip().lower()
        month = _MONTH_TOKEN_TO_NUMBER.get(token)
        if month is None:
            continue
        year = int(match.group(2))
        start_iso, end_iso = _month_range(year, month)
        label = date(year, month, 1).strftime("%B %Y")
        matches.append((int(match.start()), start_iso, end_iso, label))

    for match in _YEAR_MONTH_RE.finditer(text):
        year = int(match.group(1))
        month = int(match.group(2))
        start_iso, end_iso = _month_range(year, month)
        label = date(year, month, 1).strftime("%B %Y")
        matches.append((int(match.start()), start_iso, end_iso, label))

    matches.sort(key=lambda item: item[0])
    spans: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for _pos, start_iso, end_iso, label in matches:
        key = (start_iso, end_iso)
        if key in seen:
            continue
        spans.append(
            {
                "start_date": start_iso,
                "end_date": end_iso,
                "label": label,
            }
        )
        seen.add(key)
    return spans


def _supported_multi_span_patterns_message() -> str:
    return (
        "Unable to parse multi-span sales request. Supported patterns: "
        "'total sales on March 1st 2025 and June 3rd 2025'; "
        "'compare March 2025 vs June 2025 sales'; "
        "'sales from 2025-03-01 to 2025-03-07 and 2025-06-01 to 2025-06-07'."
    )


def _deterministic_candidate(text: str) -> tuple[dict[str, object], list[str]]:
    cleaned = str(text or "").strip()
    if not cleaned:
        raise ValueError("query text cannot be empty")

    lowered = cleaned.lower()
    date_range_match = _DATE_RANGE_RE.search(cleaned)
    date_range_spans = _extract_multi_range_spans(cleaned)
    month_spans = _extract_month_spans(cleaned)
    year, month = _extract_month_year(cleaned)
    group_by = _extract_group_by(lowered)
    compare = _extract_compare(lowered)
    date_points, warnings = _extract_date_points_in_order(cleaned)
    has_multi_hint = bool(compare or " vs " in f" {lowered} " or " and " in f" {lowered} ")
    spans_for_date_points = [
        {
            "start_date": day,
            "end_date": day,
            "label": day,
        }
        for day in date_points
    ]

    candidate: dict[str, object] = {
        "report_type": "sales_range",
        "start_date": None,
        "end_date": None,
        "year": year,
        "month": month,
        "group_by": group_by,
        "dates": [],
        "spans": [],
        "compare": compare,
        "redact_pii": _extract_redact(lowered),
        "format": _extract_format(lowered),
    }

    if date_range_match:
        candidate["start_date"] = date_range_match.group(1)
        candidate["end_date"] = date_range_match.group(2)

    if "occupancy" in lowered:
        candidate["report_type"] = "occupancy_range"
        if candidate["group_by"] is None:
            candidate["group_by"] = "day"
        return candidate, warnings

    if "export" in lowered and "reservation" in lowered:
        candidate["report_type"] = "export_reservations"
        return candidate, warnings

    if ("list reservation" in lowered) or ("reservations list" in lowered) or lowered.startswith("reservations"):
        candidate["report_type"] = "reservations_list"
        return candidate, warnings

    if compare:
        if len(month_spans) >= 2:
            candidate["report_type"] = "sales_month"
            candidate["spans"] = month_spans
            candidate["start_date"] = month_spans[0]["start_date"]
            candidate["end_date"] = month_spans[-1]["end_date"]
            candidate["group_by"] = "day"
            candidate["compare"] = True
            return candidate, warnings
        if len(date_range_spans) >= 2:
            candidate["report_type"] = "sales_range"
            candidate["spans"] = date_range_spans
            candidate["start_date"] = date_range_spans[0]["start_date"]
            candidate["end_date"] = date_range_spans[-1]["end_date"]
            if candidate["group_by"] is None:
                candidate["group_by"] = "day"
            candidate["compare"] = True
            return candidate, warnings
        if len(spans_for_date_points) >= 2:
            candidate["report_type"] = "sales_day"
            candidate["spans"] = spans_for_date_points
            candidate["start_date"] = spans_for_date_points[0]["start_date"]
            candidate["end_date"] = spans_for_date_points[-1]["end_date"]
            candidate["group_by"] = None
            candidate["compare"] = True
            return candidate, warnings

    if "sales" in lowered:
        if "by channel" in lowered or "by source channel" in lowered or "channel breakdown" in lowered:
            candidate["report_type"] = "sales_by_channel"
            candidate["group_by"] = "channel"
            if len(date_range_spans) >= 2:
                candidate["spans"] = date_range_spans
                candidate["start_date"] = date_range_spans[0]["start_date"]
                candidate["end_date"] = date_range_spans[-1]["end_date"]
                candidate["compare"] = True
                return candidate, warnings
            if len(month_spans) >= 2:
                candidate["spans"] = month_spans
                candidate["start_date"] = month_spans[0]["start_date"]
                candidate["end_date"] = month_spans[-1]["end_date"]
                candidate["compare"] = True
                return candidate, warnings
            if len(spans_for_date_points) >= 2 and has_multi_hint:
                candidate["spans"] = spans_for_date_points
                candidate["start_date"] = spans_for_date_points[0]["start_date"]
                candidate["end_date"] = spans_for_date_points[-1]["end_date"]
                candidate["compare"] = True
                return candidate, warnings
            return candidate, warnings

        if len(date_range_spans) >= 2:
            candidate["report_type"] = "sales_range"
            candidate["spans"] = date_range_spans
            candidate["start_date"] = date_range_spans[0]["start_date"]
            candidate["end_date"] = date_range_spans[-1]["end_date"]
            if candidate["group_by"] is None:
                candidate["group_by"] = "day"
            candidate["compare"] = True
            return candidate, warnings

        if len(month_spans) >= 2 and has_multi_hint:
            candidate["report_type"] = "sales_month"
            candidate["spans"] = month_spans
            candidate["start_date"] = month_spans[0]["start_date"]
            candidate["end_date"] = month_spans[-1]["end_date"]
            if candidate["group_by"] is None:
                candidate["group_by"] = "day"
            candidate["compare"] = True
            return candidate, warnings

        if len(spans_for_date_points) >= 2 and (has_multi_hint or " on " in f" {lowered}"):
            candidate["report_type"] = "sales_day"
            candidate["spans"] = spans_for_date_points
            candidate["start_date"] = spans_for_date_points[0]["start_date"]
            candidate["end_date"] = spans_for_date_points[-1]["end_date"]
            candidate["group_by"] = None
            candidate["compare"] = True
            return candidate, warnings

        if date_range_match:
            candidate["report_type"] = "sales_range"
            if candidate["group_by"] is None:
                candidate["group_by"] = "day"
            return candidate, warnings

        if date_points and (" on " in f" {lowered}"):
            candidate["report_type"] = "sales_day"
            candidate["start_date"] = date_points[0]
            candidate["end_date"] = date_points[0]
            candidate["group_by"] = None
            return candidate, warnings

        if compare and has_multi_hint:
            raise ValueError(_supported_multi_span_patterns_message())

        if year is not None and month is not None:
            candidate["report_type"] = "sales_month"
            if candidate["group_by"] is None:
                candidate["group_by"] = "day"
            return candidate, warnings

        if has_multi_hint:
            raise ValueError(_supported_multi_span_patterns_message())

        raise ValueError(
            "Ambiguous sales question. Provide a date range (YYYY-MM-DD to YYYY-MM-DD), "
            "specific dates (for example March 1 and June 3), or a month like March 2025."
        )

    if has_multi_hint and (
        len(month_spans) == 1
        or len(date_range_spans) == 1
        or len(spans_for_date_points) == 1
    ):
        raise ValueError(_supported_multi_span_patterns_message())

    raise ValueError("Unsupported toy query. Try one of: " + "; ".join(f"'{s}'" for s in _EXAMPLES))


def _default_llm_router(question: str) -> Mapping[str, object] | str:
    from ai_deney.llm.router import route_toy_query_spec

    return route_toy_query_spec(question)


def _llm_stub_source() -> str:
    if str(os.getenv("AI_DENEY_TOY_LLM_STUB_JSON", "")).strip():
        return "env_json"
    if str(os.getenv("AI_DENEY_TOY_LLM_STUB_FILE", "")).strip():
        return "env_file"
    return "router_default"


def _deterministic_rule_trace(text: str, candidate: Mapping[str, object]) -> tuple[str, list[str]]:
    lowered = text.lower()
    matched: list[str] = []
    date_range_matches = list(_DATE_RANGE_RE.finditer(text))
    if date_range_matches:
        matched.append("date_range")
    if len(date_range_matches) >= 2:
        matched.append("multi_date_range")
    if _MONTH_YEAR_RE.search(text) or _YEAR_MONTH_RE.search(text):
        matched.append("month_year")
    if _ISO_DATE_RE.search(text):
        matched.append("iso_date")
    if _MONTH_DAY_RE.search(text):
        matched.append("month_day")
    if _COMPARE_RE.search(text):
        matched.append("compare")
    if "by channel" in lowered or "by source channel" in lowered or "channel breakdown" in lowered:
        matched.append("group_by_channel")
    if "occupancy" in lowered:
        matched.append("occupancy_keyword")
    if "export" in lowered and "reservation" in lowered:
        matched.append("export_keyword")
    if "reservation" in lowered:
        matched.append("reservation_keyword")
    if "sales" in lowered:
        matched.append("sales_keyword")

    report_type = str(candidate.get("report_type") or "")
    spans_count = len(list(candidate.get("spans") or []))
    rule_path = "fallback"
    if report_type == "occupancy_range":
        rule_path = "deterministic.occupancy_keyword"
    elif report_type == "export_reservations":
        rule_path = "deterministic.export_keyword"
    elif report_type == "reservations_list":
        rule_path = "deterministic.reservations_keyword"
    elif report_type == "sales_by_channel":
        rule_path = "deterministic.sales.channel"
    elif report_type == "sales_for_dates":
        rule_path = "deterministic.sales.compare_dates" if _COMPARE_RE.search(text) else "deterministic.sales.date_points"
    elif report_type == "sales_month":
        rule_path = "deterministic.sales.multi_month" if spans_count >= 2 else "deterministic.sales.month"
    elif report_type == "sales_range":
        if spans_count >= 2:
            rule_path = "deterministic.sales.multi_range"
        else:
            rule_path = "deterministic.sales.date_range" if _DATE_RANGE_RE.search(text) else "deterministic.sales.range"
    elif report_type == "sales_day":
        rule_path = "deterministic.sales.multi_day" if spans_count >= 2 else "deterministic.sales.day"
    if spans_count >= 2:
        matched.append("multi_span")

    return rule_path, matched


def _resolved_range_fields(spec: QuerySpec) -> tuple[str | None, str | None]:
    if spec.start_date and spec.end_date:
        return spec.start_date, spec.end_date
    if spec.spans:
        return str(spec.spans[0].start_date), str(spec.spans[-1].end_date)
    if spec.report_type == "sales_for_dates" and spec.dates:
        return str(spec.dates[0]), str(spec.dates[-1])
    return None, None


def _coerce_router_output(raw: Mapping[str, object] | str) -> dict[str, object]:
    if isinstance(raw, Mapping):
        return dict(raw)
    if isinstance(raw, str):
        text = raw.strip()
        try:
            parsed = json.loads(text)
        except Exception as exc:
            raise ValueError("LLM router output must be valid JSON object") from exc
        if not isinstance(parsed, dict):
            raise ValueError("LLM router output must be a JSON object")
        return {str(k): v for k, v in parsed.items()}
    raise ValueError("LLM router output must be dict or JSON string")


def validate_query_spec(spec: Mapping[str, object] | QuerySpec, *, question_text: str = "") -> QuerySpec:
    if isinstance(spec, QuerySpec):
        raw: dict[str, object] = spec.to_dict()
    else:
        raw = dict(spec)

    unknown = sorted(set(raw.keys()) - _ALLOWED_KEYS)
    if unknown:
        raise ValueError(f"QuerySpec contains unsupported fields: {', '.join(unknown)}")

    report_type = str(raw.get("report_type", "")).strip()
    if report_type not in {
        "sales_range",
        "sales_month",
        "sales_by_channel",
        "sales_day",
        "sales_for_dates",
        "occupancy_range",
        "reservations_list",
        "export_reservations",
    }:
        raise ValueError(
            "report_type must be one of sales_range, sales_month, sales_by_channel, sales_day, sales_for_dates, "
            "occupancy_range, reservations_list, export_reservations"
        )

    group_by_value = raw.get("group_by")
    if group_by_value in ("", None):
        group_by: GroupBy | None = None
    elif group_by_value in {"day", "channel"}:
        group_by = str(group_by_value)  # type: ignore[assignment]
    else:
        raise ValueError("group_by must be one of: day, channel")

    format_value = raw.get("format", "md")
    if format_value in (None, ""):
        format_value = "md"
    if format_value not in {"md", "html"}:
        raise ValueError("format must be 'md' or 'html'")
    fmt: FormatType = str(format_value)  # type: ignore[assignment]

    redact_raw = raw.get("redact_pii", True)
    if isinstance(redact_raw, bool):
        redact_pii = redact_raw
    else:
        raise ValueError("redact_pii must be a boolean")

    compare_provided = "compare" in raw
    compare_raw = raw.get("compare", False)
    if isinstance(compare_raw, bool):
        compare = compare_raw
    else:
        raise ValueError("compare must be a boolean")

    dates_raw = raw.get("dates", [])
    if dates_raw in (None, ""):
        dates_raw = []
    if not isinstance(dates_raw, (list, tuple)):
        raise ValueError("dates must be a list of YYYY-MM-DD strings")
    dates_list: list[str] = []
    for item in dates_raw:
        if not isinstance(item, str):
            raise ValueError("dates must contain only YYYY-MM-DD strings")
        parsed_date = _parse_date(item)
        dates_list.append(parsed_date.isoformat())
    dates_list = sorted(set(dates_list))

    spans_raw = raw.get("spans", [])
    if spans_raw in (None, ""):
        spans_raw = []
    if not isinstance(spans_raw, (list, tuple)):
        raise ValueError("spans must be a list of {start_date,end_date,label} objects")
    spans_list: list[QuerySpan] = []
    for idx, item in enumerate(spans_raw):
        if not isinstance(item, Mapping):
            raise ValueError(f"spans[{idx}] must be an object")
        span_dict = dict(item)
        unknown_span_keys = sorted(set(span_dict.keys()) - {"start_date", "end_date", "label"})
        if unknown_span_keys:
            raise ValueError(f"spans[{idx}] has unsupported fields: {', '.join(str(k) for k in unknown_span_keys)}")
        start_raw_span = span_dict.get("start_date")
        end_raw_span = span_dict.get("end_date")
        if start_raw_span in (None, "") or end_raw_span in (None, ""):
            raise ValueError(f"spans[{idx}] requires start_date and end_date")
        parsed_start_span = _parse_date(str(start_raw_span))
        parsed_end_span = _parse_date(str(end_raw_span))
        if parsed_end_span < parsed_start_span:
            raise ValueError(f"spans[{idx}] end_date must be >= start_date")
        start_iso = parsed_start_span.isoformat()
        end_iso = parsed_end_span.isoformat()
        raw_label = str(span_dict.get("label", "") or "").strip()
        label = raw_label or _default_span_label(start_iso, end_iso)
        spans_list.append(QuerySpan(start_date=start_iso, end_date=end_iso, label=label))

    start_raw = raw.get("start_date")
    end_raw = raw.get("end_date")
    year_raw = raw.get("year")
    month_raw = raw.get("month")

    start_date: str | None = None
    end_date: str | None = None
    year: int | None = None
    month: int | None = None

    if year_raw not in (None, ""):
        try:
            year = int(year_raw)
        except Exception as exc:
            raise ValueError("year must be an integer") from exc
    if month_raw not in (None, ""):
        try:
            month = int(month_raw)
        except Exception as exc:
            raise ValueError("month must be an integer") from exc

    if year is not None and not (2000 <= year <= 2100):
        raise ValueError("year must be in range 2000..2100")
    if month is not None and not (1 <= month <= 12):
        raise ValueError("month must be in range 1..12")
    if (year is None) ^ (month is None):
        raise ValueError("year and month must be provided together")

    if start_raw in (None, "") and end_raw in (None, ""):
        start_date = None
        end_date = None
    elif start_raw in (None, "") or end_raw in (None, ""):
        raise ValueError("start_date and end_date must be provided together")
    else:
        parsed_start = _parse_date(str(start_raw))
        parsed_end = _parse_date(str(end_raw))
        if parsed_end < parsed_start:
            raise ValueError("date range end must be >= start")
        start_date = parsed_start.isoformat()
        end_date = parsed_end.isoformat()

    if spans_list and report_type not in {"sales_day", "sales_range", "sales_month", "sales_by_channel"}:
        raise ValueError("spans is only supported for sales_day, sales_range, sales_month, sales_by_channel")

    if spans_list and dates_list:
        raise ValueError("spans and dates cannot be used together")

    if spans_list and len(spans_list) >= 2 and not compare_provided:
        compare = True

    if report_type == "sales_for_dates":
        if spans_list:
            raise ValueError("sales_for_dates does not support spans")
        if not dates_list:
            raise ValueError("sales_for_dates requires at least one date in dates[]")
        if compare and len(dates_list) < 2:
            raise ValueError("sales_for_dates compare=true requires at least 2 dates")
        if group_by is not None:
            raise ValueError("sales_for_dates does not support group_by")
    elif report_type == "sales_day":
        if dates_list:
            raise ValueError("sales_day does not support dates[]; use start_date/end_date for the day")
        if spans_list:
            for idx, span in enumerate(spans_list):
                if span.start_date != span.end_date:
                    raise ValueError(f"sales_day spans[{idx}] requires start_date == end_date")
            if start_date is None:
                start_date = spans_list[0].start_date
            if end_date is None:
                end_date = spans_list[-1].end_date
        else:
            if start_date is None or end_date is None:
                raise ValueError("sales_day requires start_date and end_date")
            if start_date != end_date:
                raise ValueError("sales_day requires start_date == end_date")
        if group_by is not None:
            raise ValueError("sales_day does not support group_by")
    elif dates_list:
        raise ValueError("dates is only supported for report_type=sales_for_dates")

    if report_type == "sales_month":
        if spans_list:
            for idx, span in enumerate(spans_list):
                span_start = _parse_date(span.start_date)
                span_month_start, span_month_end = _month_range(span_start.year, span_start.month)
                if span.start_date != span_month_start or span.end_date != span_month_end:
                    raise ValueError("sales_month spans must each match an exact full-month date range")
            if start_date is None:
                start_date = spans_list[0].start_date
            if end_date is None:
                end_date = spans_list[-1].end_date
            if group_by is None:
                group_by = "day"
        else:
            if year is None or month is None:
                if start_date and end_date:
                    start_d = _parse_date(start_date)
                    end_d = _parse_date(end_date)
                    expected_start, expected_end = _month_range(start_d.year, start_d.month)
                    if start_date != expected_start or end_date != expected_end:
                        raise ValueError("sales_month requires year/month or an exact full-month date range")
                    year = start_d.year
                    month = start_d.month
                else:
                    raise ValueError("sales_month requires year and month")
            month_start, month_end = _month_range(year, month)
            if start_date is None:
                start_date = month_start
                end_date = month_end
            elif start_date != month_start or end_date != month_end:
                raise ValueError("sales_month start_date/end_date must match the provided year/month")
            if group_by is None:
                group_by = "day"

    if report_type in _RANGE_REQUIRED_REPORTS:
        if spans_list:
            if start_date is None:
                start_date = spans_list[0].start_date
            if end_date is None:
                end_date = spans_list[-1].end_date
        if start_date is None or end_date is None:
            if year is not None and month is not None:
                start_date, end_date = _month_range(year, month)
            else:
                ctx = f" for query: {question_text!r}" if question_text else ""
                raise ValueError(
                    "Ambiguous date range. Provide start_date/end_date or a specific month like March 2025"
                    + ctx
                )
        if report_type == "sales_by_channel":
            group_by = "channel"
        elif report_type in {"sales_range", "occupancy_range"} and group_by is None:
            group_by = "day"

    return QuerySpec(
        report_type=report_type,  # type: ignore[arg-type]
        start_date=start_date,
        end_date=end_date,
        year=year,
        month=month,
        group_by=group_by,
        dates=tuple(dates_list),
        spans=tuple(spans_list),
        compare=compare,
        redact_pii=redact_pii,
        format=fmt,
    )


def parse_toy_query_with_trace(
    text: str,
    *,
    intent_mode: str | None = None,
    llm_router: ToyLLMRouter | None = None,
) -> ToyParseResult:
    cleaned = str(text or "").strip()
    if not cleaned:
        raise ValueError("query text cannot be empty")

    mode = resolve_intent_mode(intent_mode)

    if mode == "deterministic":
        candidate, warnings = _deterministic_candidate(cleaned)
        spec = validate_query_spec(candidate, question_text=cleaned)
        return ToyParseResult(spec=spec, raw_llm_json=None, intent_mode="deterministic", warnings=tuple(warnings))

    router = llm_router or _default_llm_router
    try:
        raw = router(cleaned)
    except Exception as exc:
        raise ValueError(f"llm router failed: {exc}") from exc

    raw_llm_json = _coerce_router_output(raw)
    spec = validate_query_spec(raw_llm_json, question_text=cleaned)
    return ToyParseResult(spec=spec, raw_llm_json=raw_llm_json, intent_mode="llm", warnings=())


def parse_toy_query_debug_trace(
    text: str,
    *,
    intent_mode: str | None = None,
    llm_router: ToyLLMRouter | None = None,
) -> tuple[QuerySpec, dict[str, object]]:
    cleaned = str(text or "").strip()
    if not cleaned:
        raise ValueError("query text cannot be empty")

    mode = resolve_intent_mode(intent_mode)

    if mode == "deterministic":
        candidate, warnings = _deterministic_candidate(cleaned)
        spec = validate_query_spec(candidate, question_text=cleaned)
        start_date, end_date = _resolved_range_fields(spec)
        rule_path, matched_patterns = _deterministic_rule_trace(cleaned, candidate)
        trace = {
            "mode": "deterministic",
            "rule_path": rule_path,
            "matched_patterns": matched_patterns,
            "parsed": {
                "start_date": start_date,
                "end_date": end_date,
                "year": spec.year,
                "month": spec.month,
                "dates": list(spec.dates),
                "spans": [span.to_dict() for span in spec.spans],
            },
            "chosen": {
                "report_type": spec.report_type,
                "group_by": spec.group_by,
            },
            "validation_notes": list(warnings) + ["QuerySpec validation: pass"],
        }
        return spec, trace

    router = llm_router or _default_llm_router
    try:
        raw = router(cleaned)
    except Exception as exc:
        raise ValueError(f"llm router failed: {exc}") from exc

    raw_llm_json = _coerce_router_output(raw)
    spec = validate_query_spec(raw_llm_json, question_text=cleaned)
    start_date, end_date = _resolved_range_fields(spec)
    trace = {
        "mode": "llm",
        "stub_source": _llm_stub_source(),
        "validation": {
            "passed": True,
            "summary": "QuerySpec validation: pass",
        },
        "parsed": {
            "start_date": start_date,
            "end_date": end_date,
            "year": spec.year,
            "month": spec.month,
            "dates": list(spec.dates),
            "spans": [span.to_dict() for span in spec.spans],
        },
        "chosen": {
            "report_type": spec.report_type,
            "group_by": spec.group_by,
        },
        "validation_notes": ["QuerySpec validation: pass"],
    }
    return spec, trace


def _sales_day_spec_from_date(base: QuerySpec, day: str) -> QuerySpec:
    return QuerySpec(
        report_type="sales_day",
        start_date=str(day),
        end_date=str(day),
        year=None,
        month=None,
        group_by=None,
        dates=(),
        spans=(),
        compare=False,
        redact_pii=bool(base.redact_pii),
        format=base.format,
    )


def parse_toy_query_plan_with_trace(
    text: str,
    *,
    intent_mode: str | None = None,
    llm_router: ToyLLMRouter | None = None,
) -> ToyPlanResult:
    parsed = parse_toy_query_with_trace(text, intent_mode=intent_mode, llm_router=llm_router)
    spec = parsed.spec
    if spec.report_type == "sales_for_dates" and len(spec.dates) >= 2:
        plan = tuple(_sales_day_spec_from_date(spec, day) for day in spec.dates)
        return ToyPlanResult(
            spec=None,
            plan=plan,
            compare=bool(spec.compare),
            raw_llm_json=parsed.raw_llm_json,
            intent_mode=parsed.intent_mode,
            warnings=tuple(parsed.warnings),
        )
    return ToyPlanResult(
        spec=spec,
        plan=(),
        compare=False,
        raw_llm_json=parsed.raw_llm_json,
        intent_mode=parsed.intent_mode,
        warnings=tuple(parsed.warnings),
    )


def parse_toy_query(
    text: str,
    *,
    intent_mode: str | None = None,
    llm_router: ToyLLMRouter | None = None,
) -> QuerySpec:
    return parse_toy_query_with_trace(text, intent_mode=intent_mode, llm_router=llm_router).spec
