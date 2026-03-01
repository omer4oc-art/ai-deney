from __future__ import annotations

import pytest

from ai_deney.intent.toy_intent import parse_toy_query


def test_parse_sales_month_basic_phrase() -> None:
    spec = parse_toy_query("march 2025 sales data")
    assert spec.query_type == "sales_month"
    assert spec.year == 2025
    assert spec.month == 3
    assert spec.group_by is None
    assert spec.redact_pii is False
    assert spec.resolved_range()[0].isoformat() == "2025-03-01"
    assert spec.resolved_range()[1].isoformat() == "2025-03-31"


def test_parse_sales_month_with_group_by_channel() -> None:
    spec = parse_toy_query("sales by source channel for March 2025")
    assert spec.query_type == "sales_month"
    assert spec.group_by == "source_channel"
    assert spec.year == 2025
    assert spec.month == 3


def test_parse_sales_for_month_phrase() -> None:
    spec = parse_toy_query("sales for March 2025")
    assert spec.query_type == "sales_month"
    assert spec.year == 2025
    assert spec.month == 3


def test_parse_sales_month_with_redaction_phrase() -> None:
    spec = parse_toy_query("export March 2025 sales redacted")
    assert spec.query_type == "sales_month"
    assert spec.redact_pii is True


def test_parse_sales_range_dates() -> None:
    spec = parse_toy_query("sales from 2025-03-01 to 2025-03-15 by agency")
    assert spec.query_type == "sales_range"
    assert spec.group_by == "agency"
    assert spec.start is not None and spec.start.isoformat() == "2025-03-01"
    assert spec.end is not None and spec.end.isoformat() == "2025-03-15"


def test_parse_requires_sales_keyword() -> None:
    with pytest.raises(ValueError, match="only supports sales questions"):
        parse_toy_query("occupancy for march 2025")
