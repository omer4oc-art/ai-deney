"""Deterministic intent parser from user text to Electra QuerySpec."""

from __future__ import annotations

import re

from ai_deney.intent.query_spec import QuerySpec

_YEAR_RE = re.compile(r"\b(20\d{2})\b")


def _extract_years(text: str) -> list[int]:
    years = sorted({int(y) for y in _YEAR_RE.findall(text)})
    if not years:
        raise ValueError(
            "No years found in query. Please include explicit years, e.g. "
            "'get me the sales data of 2026 and 2025' or "
            "'get me the sales categorized by agencies for 2025'."
        )
    return years


def parse_electra_query(text: str) -> QuerySpec:
    """
    Deterministically parse a user question into a QuerySpec.

    Rules:
    - If text contains 'agency' or 'agencies' -> sales_by_agency
    - If text contains 'categorized by' + 'agency' -> sales_by_agency
    - Else if text contains 'sales data' or 'sales summary' -> sales_summary
    - Else fallback to sales_summary
    """

    cleaned = (text or "").strip()
    if not cleaned:
        raise ValueError("query text cannot be empty")

    # Scaffold-only hook: still deterministic and non-networked.

    lowered = cleaned.lower()
    years = _extract_years(cleaned)
    has_agency = ("agency" in lowered) or ("agencies" in lowered)
    categorized_agency = ("categorized by" in lowered) and has_agency
    compare = "compare" in lowered

    if categorized_agency or has_agency:
        report = "sales_by_agency"
        group_by = "agency"
    elif ("sales data" in lowered) or ("sales summary" in lowered):
        report = "sales_summary"
        group_by = None
    else:
        report = "sales_summary"
        group_by = None

    return QuerySpec(
        report=report,
        years=years,
        group_by=group_by,
        output_format="markdown",
        compare=compare,
        original_text=cleaned,
    )

