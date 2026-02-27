import pytest

from ai_deney.intent.electra_intent import parse_electra_query


def test_parse_sales_summary_years() -> None:
    spec = parse_electra_query("get me the sales data of 2026 and 2025")
    assert spec.report == "sales_summary"
    assert spec.years == [2025, 2026]
    assert spec.group_by is None
    assert spec.output_format == "markdown"
    assert spec.compare is False


def test_parse_agency_sales_and_compare() -> None:
    spec = parse_electra_query("compare 2025 vs 2026 by agency")
    assert spec.report == "sales_by_agency"
    assert spec.group_by == "agency"
    assert spec.years == [2025, 2026]
    assert spec.compare is True


def test_parse_requires_explicit_years() -> None:
    with pytest.raises(ValueError, match="No years found in query"):
        parse_electra_query("get me sales data")

