import pytest

from ai_deney.intent.electra_intent import parse_electra_query


def test_parse_sales_summary_years() -> None:
    spec = parse_electra_query("get me the sales data of 2026 and 2025")
    assert spec.report == "sales_summary"
    assert spec.years == [2025, 2026]
    assert spec.group_by is None
    assert spec.output_format == "markdown"
    assert spec.compare is False
    assert spec.analysis == "sales_summary"


def test_parse_agency_sales_and_compare() -> None:
    spec = parse_electra_query("compare 2025 vs 2026 by agency")
    assert spec.report == "sales_by_agency"
    assert spec.group_by == "agency"
    assert spec.years == [2025, 2026]
    assert spec.compare is True
    assert spec.analysis == "sales_by_agency"


def test_parse_requires_explicit_years() -> None:
    with pytest.raises(ValueError, match="No years found in query"):
        parse_electra_query("get me sales data")


def test_parse_sales_by_month_pattern() -> None:
    spec = parse_electra_query("sales by month for 2025")
    assert spec.report == "sales_summary"
    assert spec.analysis == "sales_by_month"
    assert spec.group_by == "month"
    assert spec.years == [2025]


def test_parse_top_agencies_pattern() -> None:
    spec = parse_electra_query("top agencies in 2026")
    assert spec.report == "sales_by_agency"
    assert spec.analysis == "top_agencies"
    assert spec.group_by == "agency"
    assert spec.years == [2026]


def test_parse_direct_share_pattern() -> None:
    spec = parse_electra_query("share of direct vs agencies in 2025")
    assert spec.report == "sales_by_agency"
    assert spec.analysis == "direct_share"
    assert spec.group_by == "agency"
    assert spec.years == [2025]


def test_parse_unsupported_query_lists_examples() -> None:
    with pytest.raises(ValueError, match="Unsupported query. Supported examples"):
        parse_electra_query("show me operational metrics for 2025")
