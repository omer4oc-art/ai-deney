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


def test_parse_reconciliation_patterns() -> None:
    spec = parse_electra_query("compare electra vs hotelrunner for 2025")
    assert spec.source == "reconcile"
    assert spec.analysis == "reconcile_daily"
    assert spec.registry_key == "reconcile.daily"
    assert spec.years == [2025]

    spec2 = parse_electra_query("where do electra and hotelrunner differ in 2026")
    assert spec2.source == "reconcile"
    assert spec2.analysis == "reconcile_daily"
    assert spec2.registry_key == "reconcile.daily"
    assert spec2.years == [2026]


def test_parse_reconciliation_monthly_patterns() -> None:
    spec = parse_electra_query("electra vs hotelrunner monthly reconciliation for 2025")
    assert spec.source == "reconcile"
    assert spec.analysis == "reconcile_monthly"
    assert spec.registry_key == "reconcile.monthly"
    assert spec.years == [2025]

    spec2 = parse_electra_query("monthly reconciliation 2026 electra hotelrunner")
    assert spec2.source == "reconcile"
    assert spec2.analysis == "reconcile_monthly"
    assert spec2.registry_key == "reconcile.monthly"
    assert spec2.years == [2026]


def test_parse_reconciliation_by_agency_patterns() -> None:
    spec = parse_electra_query("where do electra and hotelrunner differ by agency in 2025")
    assert spec.source == "reconcile"
    assert spec.analysis == "reconcile_daily_by_agency"
    assert spec.group_by == "agency"
    assert spec.registry_key == "reconcile.daily_by_agency"
    assert spec.years == [2025]

    spec2 = parse_electra_query("monthly reconciliation by agency 2026 electra hotelrunner")
    assert spec2.source == "reconcile"
    assert spec2.analysis == "reconcile_monthly_by_agency"
    assert spec2.group_by == "agency"
    assert spec2.registry_key == "reconcile.monthly_by_agency"
    assert spec2.years == [2026]


def test_parse_reconciliation_anomaly_by_agency_patterns() -> None:
    spec = parse_electra_query("any anomalies by agency in 2025")
    assert spec.source == "reconcile"
    assert spec.analysis == "reconcile_anomalies_agency"
    assert spec.group_by == "agency"
    assert spec.registry_key == "reconcile.anomalies_agency"
    assert spec.years == [2025]


def test_parse_mapping_health_agency_pattern() -> None:
    spec = parse_electra_query("mapping health report 2025")
    assert spec.source == "mapping"
    assert spec.analysis == "mapping_health_agency"
    assert spec.registry_key == "mapping.health_agency"
    assert spec.years == [2025]


def test_parse_mapping_unmapped_agencies_pattern() -> None:
    spec = parse_electra_query("which agencies are unmapped in 2026")
    assert spec.source == "mapping"
    assert spec.analysis == "mapping_unmapped_agency"
    assert spec.registry_key == "mapping.health_agency"
    assert spec.years == [2026]


def test_parse_mapping_drift_pattern() -> None:
    spec = parse_electra_query("agency drift electra vs hotelrunner 2025")
    assert spec.source == "mapping"
    assert spec.analysis == "mapping_drift_agency"
    assert spec.registry_key == "mapping.health_agency"
    assert spec.years == [2025]
