from datetime import date
from pathlib import Path

import pytest

from ai_deney.adapters.electra_adapter import ElectraAdapterError, parse_electra_export
from ai_deney.adapters.hotelrunner_adapter import HotelRunnerAdapterError, parse_hotelrunner_export
from ai_deney.inbox.scan import SelectedInboxFile
from ai_deney.inbox.validate import validate_file


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_electra_adapter_accepts_aliases_and_ignores_extra_columns() -> None:
    root = _repo_root() / "tests" / "fixtures" / "exports" / "electra"

    summary_rows = parse_electra_export(root / "sales_summary_aliases.csv", report_type="sales_summary")
    assert len(summary_rows) == 2
    assert set(summary_rows[0].keys()) == {"date", "gross_sales", "net_sales", "currency"}
    assert summary_rows[0]["gross_sales"] == "100.00"

    agency_rows = parse_electra_export(root / "sales_by_agency_aliases.csv", report_type="sales_by_agency")
    assert len(agency_rows) == 2
    assert set(agency_rows[0].keys()) == {
        "date",
        "agency_id",
        "agency_name",
        "gross_sales",
        "net_sales",
        "currency",
    }
    assert agency_rows[0]["agency_id"] == "AG001"


def test_electra_adapter_errors_on_missing_required_columns() -> None:
    root = _repo_root() / "tests" / "fixtures" / "exports" / "electra"
    with pytest.raises(ElectraAdapterError, match="header mismatch"):
        parse_electra_export(root / "sales_summary_missing_required.csv", report_type="sales_summary")


def test_hotelrunner_adapter_accepts_aliases_and_ignores_extra_columns() -> None:
    root = _repo_root() / "tests" / "fixtures" / "exports" / "hotelrunner"
    rows = parse_hotelrunner_export(root / "daily_sales_aliases.csv")
    assert len(rows) == 2
    assert set(rows[0].keys()) == {
        "date",
        "booking_id",
        "channel",
        "agency_id",
        "agency_name",
        "gross_sales",
        "net_sales",
        "currency",
    }
    assert rows[0]["booking_id"] == "HR1"
    assert rows[0]["channel"] == "Booking.com"


def test_hotelrunner_adapter_errors_on_missing_required_columns() -> None:
    root = _repo_root() / "tests" / "fixtures" / "exports" / "hotelrunner"
    with pytest.raises(HotelRunnerAdapterError, match="header mismatch"):
        parse_hotelrunner_export(root / "daily_sales_missing_required.csv")


def test_inbox_validator_uses_adapter_alias_mapping() -> None:
    path = _repo_root() / "tests" / "fixtures" / "exports" / "electra" / "sales_summary_aliases.csv"
    selected = SelectedInboxFile(
        source="electra",
        report_type="sales_summary",
        report_date=date(2025, 1, 1),
        year=2025,
        path=path,
        mtime_ns=1,
        size_bytes=int(path.stat().st_size),
    )
    validate_file(selected)
