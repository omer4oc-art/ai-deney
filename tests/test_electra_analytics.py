import pytest
from pathlib import Path
import shutil

from ai_deney.analytics.electra_queries import get_sales_by_agency, get_sales_years
from ai_deney.analytics.electra_validations import (
    read_normalized_rows,
    validate_agency_totals_match_summary,
    validate_no_negative_gross_sales,
    validate_requested_years_exist,
)
from ai_deney.connectors.electra_mock import ElectraMockConnector
from ai_deney.parsing.electra_sales import normalize_report_files


def _rows_from_df(df) -> list[dict]:
    # Works for pandas.DataFrame and local mini dataframe fallback.
    return df.to_dict("records")


def _prepare_normalized(tmp_path: Path) -> Path:
    repo_root = Path(__file__).resolve().parents[1]
    raw_root = repo_root / "tests" / "_tmp_tasks" / "electra_analytics" / "raw"
    shutil.rmtree(raw_root, ignore_errors=True)
    raw_root.mkdir(parents=True, exist_ok=True)
    conn = ElectraMockConnector(repo_root=repo_root, raw_root=raw_root)
    normalized_root = tmp_path / "normalized"

    summary = conn.fetch_report("sales_summary", {"years": [2025, 2026]})
    by_agency = conn.fetch_report("sales_by_agency", {"years": [2025, 2026]})
    normalize_report_files(summary, "sales_summary", normalized_root)
    normalize_report_files(by_agency, "sales_by_agency", normalized_root)
    return normalized_root


def test_analytics_queries_return_expected_totals(tmp_path: Path) -> None:
    normalized_root = _prepare_normalized(tmp_path)

    yearly = _rows_from_df(get_sales_years([2025, 2026], normalized_root=normalized_root))
    assert yearly == [
        {"year": 2025, "gross_sales": 1000.0, "net_sales": 900.0, "currency": "USD"},
        {"year": 2026, "gross_sales": 1300.0, "net_sales": 1170.0, "currency": "USD"},
    ]

    agency = _rows_from_df(get_sales_by_agency([2025], normalized_root=normalized_root))
    assert agency == [
        {
            "year": 2025,
            "agency_id": "AG001",
            "agency_name": "Atlas Partners",
            "gross_sales": 400.0,
            "net_sales": 360.0,
            "currency": "USD",
        },
        {
            "year": 2025,
            "agency_id": "AG002",
            "agency_name": "Beacon Agency",
            "gross_sales": 350.0,
            "net_sales": 315.0,
            "currency": "USD",
        },
        {
            "year": 2025,
            "agency_id": "DIRECT",
            "agency_name": "Direct Channel",
            "gross_sales": 250.0,
            "net_sales": 225.0,
            "currency": "USD",
        },
    ]


def test_validation_checks_and_failure_modes(tmp_path: Path) -> None:
    normalized_root = _prepare_normalized(tmp_path)
    validate_requested_years_exist([2025, 2026], normalized_root)
    rows = read_normalized_rows([2025, 2026], normalized_root)
    validate_no_negative_gross_sales(rows)
    validate_agency_totals_match_summary(rows)

    with pytest.raises(ValueError, match="normalized data missing for years"):
        validate_requested_years_exist([2024], normalized_root)

    bad_negative = [dict(r) for r in rows]
    bad_negative[0]["gross_sales"] = -1.0
    with pytest.raises(ValueError, match="negative gross_sales"):
        validate_no_negative_gross_sales(bad_negative)

    bad_totals = [dict(r) for r in rows if int(r["year"]) == 2025]
    for row in bad_totals:
        if row["agency_id"] == "AG001":
            row["gross_sales"] = float(row["gross_sales"]) + 1.0
            break
    with pytest.raises(ValueError, match="agency totals mismatch"):
        validate_agency_totals_match_summary(bad_totals)
