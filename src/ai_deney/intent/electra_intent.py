"""Deterministic intent parser from user text to Electra QuerySpec."""

from __future__ import annotations

import re

from ai_deney.intent.query_spec import QuerySpec

_YEAR_RE = re.compile(r"\b(20\d{2})\b")
_SUPPORTED_EXAMPLES = [
    "get me the sales data of 2026 and 2025",
    "get me the sales categorized by agencies for 2025",
    "compare 2025 vs 2026 by agency",
    "sales by month for 2025",
    "top agencies in 2026",
    "share of direct vs agencies in 2025",
]


def _extract_years(text: str) -> list[int]:
    years = sorted({int(y) for y in _YEAR_RE.findall(text)})
    if not years:
        raise ValueError(
            "No years found in query. Please include explicit years, e.g. "
            + "; ".join(f"'{s}'" for s in _SUPPORTED_EXAMPLES[:3])
            + "."
        )
    return years


def parse_electra_query(text: str) -> QuerySpec:
    """
    Deterministically parse a user question into a QuerySpec.

    Rules:
    - "sales by month" -> sales_by_month
    - "top agencies" -> top_agencies
    - "share of direct vs agencies" -> direct_share
    - "agency"/"agencies"/"categorized by ... agency" -> sales_by_agency
    - "sales data"/"sales summary" -> sales_summary
    - otherwise raise with supported examples
    """

    cleaned = (text or "").strip()
    if not cleaned:
        raise ValueError("query text cannot be empty")

    lowered = cleaned.lower()
    years = _extract_years(cleaned)
    has_agency = ("agency" in lowered) or ("agencies" in lowered)
    categorized_agency = ("categorized by" in lowered) and has_agency
    compare = "compare" in lowered
    is_by_month = ("sales by month" in lowered) or ("monthly sales" in lowered) or ("by month" in lowered)
    is_top_agencies = ("top agencies" in lowered) or ("top agency" in lowered)
    is_direct_share = ("share" in lowered) and ("direct" in lowered) and has_agency

    if is_by_month:
        report = "sales_summary"
        group_by = "month"
        analysis = "sales_by_month"
    elif is_top_agencies:
        report = "sales_by_agency"
        group_by = "agency"
        analysis = "top_agencies"
    elif is_direct_share:
        report = "sales_by_agency"
        group_by = "agency"
        analysis = "direct_share"
    elif categorized_agency or has_agency:
        report = "sales_by_agency"
        group_by = "agency"
        analysis = "sales_by_agency"
    elif ("sales data" in lowered) or ("sales summary" in lowered):
        report = "sales_summary"
        group_by = None
        analysis = "sales_summary"
    else:
        supported = "\n".join(f"- {s}" for s in _SUPPORTED_EXAMPLES)
        raise ValueError(f"Unsupported query. Supported examples:\n{supported}")

    return QuerySpec(
        report=report,
        years=years,
        group_by=group_by,
        output_format="markdown",
        compare=compare,
        analysis=analysis,
        original_text=cleaned,
    )
