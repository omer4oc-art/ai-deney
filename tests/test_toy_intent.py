from __future__ import annotations

from datetime import date

import pytest

from ai_deney.intent.toy_intent import parse_toy_query, parse_toy_query_with_trace, validate_query_spec


@pytest.mark.parametrize(
    ("question", "report_type", "start_date", "end_date", "group_by"),
    [
        ("sales for March 2025", "sales_month", "2025-03-01", "2025-03-31", "day"),
        ("sales from 2025-03-01 to 2025-03-31", "sales_range", "2025-03-01", "2025-03-31", "day"),
        ("sales by channel for March 2025", "sales_by_channel", "2025-03-01", "2025-03-31", "channel"),
        ("occupancy for March 2025", "occupancy_range", "2025-03-01", "2025-03-31", "day"),
        ("occupancy from 2025-03-01 to 2025-03-07", "occupancy_range", "2025-03-01", "2025-03-07", "day"),
        ("list reservations for March 2025", "reservations_list", "2025-03-01", "2025-03-31", None),
        ("export reservations for March 2025", "export_reservations", "2025-03-01", "2025-03-31", None),
        ("reservations list from 2025-03-10 to 2025-03-12", "reservations_list", "2025-03-10", "2025-03-12", None),
    ],
)
def test_parse_deterministic_examples(
    question: str,
    report_type: str,
    start_date: str,
    end_date: str,
    group_by: str | None,
) -> None:
    spec = parse_toy_query(question, intent_mode="deterministic")
    assert spec.report_type == report_type
    assert spec.start_date == start_date
    assert spec.end_date == end_date
    assert spec.group_by == group_by
    assert spec.redact_pii is True
    assert spec.format == "md"


def test_parse_month_phrase_resolves_to_full_month() -> None:
    spec = parse_toy_query("sales for March 2025", intent_mode="deterministic")
    start, end = spec.resolved_range()
    assert start == date(2025, 3, 1)
    assert end == date(2025, 3, 31)


def test_validate_query_spec_rejects_bad_specs() -> None:
    with pytest.raises(ValueError, match="month must be in range 1..12"):
        validate_query_spec({"report_type": "sales_month", "year": 2025, "month": 13})

    with pytest.raises(ValueError, match="date range end must be >= start"):
        validate_query_spec(
            {
                "report_type": "sales_range",
                "start_date": "2025-03-31",
                "end_date": "2025-03-01",
            }
        )

    with pytest.raises(ValueError, match="report_type must be one of"):
        validate_query_spec({"report_type": "sales_total"})

    with pytest.raises(ValueError, match="Ambiguous date range"):
        validate_query_spec({"report_type": "occupancy_range"})

    with pytest.raises(ValueError, match="redact_pii must be a boolean"):
        validate_query_spec(
            {
                "report_type": "sales_range",
                "start_date": "2025-03-01",
                "end_date": "2025-03-31",
                "redact_pii": 1,
            }
        )


def test_llm_mode_uses_router_json_and_validates() -> None:
    fixed = {
        "report_type": "sales_by_channel",
        "year": 2025,
        "month": 3,
        "group_by": "channel",
        "redact_pii": True,
        "format": "md",
    }

    parsed = parse_toy_query_with_trace(
        "irrelevant text in llm mode",
        intent_mode="llm",
        llm_router=lambda _q: fixed,
    )
    assert parsed.intent_mode == "llm"
    assert parsed.raw_llm_json == fixed
    assert parsed.spec.report_type == "sales_by_channel"
    assert parsed.spec.start_date == "2025-03-01"
    assert parsed.spec.end_date == "2025-03-31"


def test_llm_mode_rejects_invalid_router_output() -> None:
    with pytest.raises(ValueError, match="unsupported fields"):
        parse_toy_query_with_trace(
            "sales for march 2025",
            intent_mode="llm",
            llm_router=lambda _q: {
                "report_type": "sales_range",
                "start_date": "2025-03-01",
                "end_date": "2025-03-31",
                "foo": "bar",
            },
        )
