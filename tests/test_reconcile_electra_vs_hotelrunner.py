import csv
from pathlib import Path
import shutil

import pytest

from ai_deney.connectors.electra_mock import ElectraMockConnector
from ai_deney.connectors.hotelrunner_mock import HotelRunnerMockConnector
from ai_deney.parsing.electra_sales import normalize_report_files as normalize_electra_report_files
from ai_deney.parsing.hotelrunner_sales import normalize_report_files as normalize_hotelrunner_report_files
from ai_deney.reconcile.electra_vs_hotelrunner import (
    compute_year_rollups,
    detect_anomalies_daily_by_dim,
    reconcile_by_dim_daily,
    reconcile_by_dim_monthly,
    reconcile_daily,
    reconcile_monthly,
)


def _normalize_sources(tmp_path: Path, years: list[int]) -> Path:
    repo_root = Path(__file__).resolve().parents[1]
    normalized_root = tmp_path / "normalized"
    raw_root = repo_root / "tests" / "_tmp_tasks" / "reconcile" / "raw"
    shutil.rmtree(raw_root.parent, ignore_errors=True)
    raw_root.mkdir(parents=True, exist_ok=True)

    electra_conn = ElectraMockConnector(repo_root=repo_root, raw_root=raw_root / "electra")
    electra_paths = electra_conn.fetch_report("sales_summary", {"years": years})
    normalize_electra_report_files(electra_paths, "sales_summary", normalized_root)

    hotelrunner_conn = HotelRunnerMockConnector(repo_root=repo_root, raw_root=raw_root / "hotelrunner")
    hotelrunner_paths = hotelrunner_conn.fetch_report("daily_sales", {"years": years})
    normalize_hotelrunner_report_files(hotelrunner_paths, normalized_root)

    return normalized_root


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_custom_reconcile_fixture(normalized_root: Path) -> None:
    electra_rows = [
        {
            "date": "2030-01-01",
            "year": 2030,
            "agency_id": "TOTAL",
            "agency_name": "Overall Total",
            "gross_sales": "100.00",
            "net_sales": "90.00",
            "currency": "USD",
        },
        {
            "date": "2030-01-02",
            "year": 2030,
            "agency_id": "TOTAL",
            "agency_name": "Overall Total",
            "gross_sales": "200.00",
            "net_sales": "180.00",
            "currency": "USD",
        },
        {
            "date": "2030-01-03",
            "year": 2030,
            "agency_id": "TOTAL",
            "agency_name": "Overall Total",
            "gross_sales": "150.00",
            "net_sales": "130.00",
            "currency": "USD",
        },
        {
            "date": "2030-01-04",
            "year": 2030,
            "agency_id": "TOTAL",
            "agency_name": "Overall Total",
            "gross_sales": "103.00",
            "net_sales": "95.00",
            "currency": "USD",
        },
        {
            "date": "2030-01-05",
            "year": 2030,
            "agency_id": "TOTAL",
            "agency_name": "Overall Total",
            "gross_sales": "120.00",
            "net_sales": "110.00",
            "currency": "USD",
        },
    ]
    hotelrunner_rows = [
        {
            "date": "2030-01-01",
            "year": 2030,
            "booking_id": "B-001",
            "agency_id": "DIRECT",
            "agency_name": "Direct Channel",
            "channel": "DIRECT",
            "gross_sales": "99.50",
            "net_sales": "89.50",
            "currency": "USD",
        },
        {
            "date": "2030-01-02",
            "year": 2030,
            "booking_id": "B-002",
            "agency_id": "DIRECT",
            "agency_name": "Direct Channel",
            "channel": "DIRECT",
            "gross_sales": "150.00",
            "net_sales": "140.00",
            "currency": "USD",
        },
        {
            "date": "2030-01-03",
            "year": 2030,
            "booking_id": "B-003",
            "agency_id": "DIRECT",
            "agency_name": "Direct Channel",
            "channel": "DIRECT",
            "gross_sales": "200.00",
            "net_sales": "180.00",
            "currency": "USD",
        },
        {
            "date": "2030-01-04",
            "year": 2030,
            "booking_id": "B-004",
            "agency_id": "DIRECT",
            "agency_name": "Direct Channel",
            "channel": "DIRECT",
            "gross_sales": "100.00",
            "net_sales": "90.00",
            "currency": "USD",
        },
        {
            "date": "2030-01-05",
            "year": 2030,
            "booking_id": "B-005",
            "agency_id": "DIRECT",
            "agency_name": "Direct Channel",
            "channel": "DIRECT",
            "gross_sales": "113.00",
            "net_sales": "104.00",
            "currency": "USD",
        },
    ]
    _write_csv(
        normalized_root / "electra_sales_2030.csv",
        ["date", "year", "agency_id", "agency_name", "gross_sales", "net_sales", "currency"],
        electra_rows,
    )
    _write_csv(
        normalized_root / "hotelrunner_sales_2030.csv",
        [
            "date",
            "year",
            "booking_id",
            "agency_id",
            "agency_name",
            "channel",
            "gross_sales",
            "net_sales",
            "currency",
        ],
        hotelrunner_rows,
    )


def _write_monthly_reconcile_fixture(normalized_root: Path) -> None:
    electra_rows = [
        {
            "date": "2040-01-03",
            "year": 2040,
            "agency_id": "TOTAL",
            "agency_name": "Overall Total",
            "gross_sales": "100.00",
            "net_sales": "90.00",
            "currency": "USD",
        },
        {
            "date": "2040-01-17",
            "year": 2040,
            "agency_id": "TOTAL",
            "agency_name": "Overall Total",
            "gross_sales": "120.00",
            "net_sales": "108.00",
            "currency": "USD",
        },
        {
            "date": "2040-02-05",
            "year": 2040,
            "agency_id": "TOTAL",
            "agency_name": "Overall Total",
            "gross_sales": "80.00",
            "net_sales": "72.00",
            "currency": "USD",
        },
        {
            "date": "2040-02-20",
            "year": 2040,
            "agency_id": "TOTAL",
            "agency_name": "Overall Total",
            "gross_sales": "20.00",
            "net_sales": "18.00",
            "currency": "USD",
        },
    ]
    hotelrunner_rows = [
        {
            "date": "2040-01-03",
            "year": 2040,
            "booking_id": "B-100",
            "agency_id": "DIRECT",
            "agency_name": "Direct Channel",
            "channel": "DIRECT",
            "gross_sales": "90.00",
            "net_sales": "81.00",
            "currency": "USD",
        },
        {
            "date": "2040-01-17",
            "year": 2040,
            "booking_id": "B-101",
            "agency_id": "DIRECT",
            "agency_name": "Direct Channel",
            "channel": "DIRECT",
            "gross_sales": "120.00",
            "net_sales": "108.00",
            "currency": "USD",
        },
        {
            "date": "2040-02-05",
            "year": 2040,
            "booking_id": "B-102",
            "agency_id": "DIRECT",
            "agency_name": "Direct Channel",
            "channel": "DIRECT",
            "gross_sales": "79.60",
            "net_sales": "72.00",
            "currency": "USD",
        },
        {
            "date": "2040-02-20",
            "year": 2040,
            "booking_id": "B-103",
            "agency_id": "DIRECT",
            "agency_name": "Direct Channel",
            "channel": "DIRECT",
            "gross_sales": "20.00",
            "net_sales": "18.00",
            "currency": "USD",
        },
    ]
    _write_csv(
        normalized_root / "electra_sales_2040.csv",
        ["date", "year", "agency_id", "agency_name", "gross_sales", "net_sales", "currency"],
        electra_rows,
    )
    _write_csv(
        normalized_root / "hotelrunner_sales_2040.csv",
        [
            "date",
            "year",
            "booking_id",
            "agency_id",
            "agency_name",
            "channel",
            "gross_sales",
            "net_sales",
            "currency",
        ],
        hotelrunner_rows,
    )


def _write_dim_fixture(normalized_root: Path) -> None:
    electra_rows = [
        {
            "date": "2050-01-01",
            "year": 2050,
            "agency_id": "AG001",
            "agency_name": "Atlas Partners",
            "gross_sales": "100.00",
            "net_sales": "91.00",
            "currency": "USD",
        },
        {
            "date": "2050-01-01",
            "year": 2050,
            "agency_id": "DIRECT",
            "agency_name": "Direct Channel",
            "gross_sales": "50.00",
            "net_sales": "45.50",
            "currency": "USD",
        },
        {
            "date": "2050-01-02",
            "year": 2050,
            "agency_id": "AG001",
            "agency_name": "Atlas Partners",
            "gross_sales": "120.00",
            "net_sales": "109.20",
            "currency": "USD",
        },
        {
            "date": "2050-01-02",
            "year": 2050,
            "agency_id": "DIRECT",
            "agency_name": "Direct Channel",
            "gross_sales": "60.00",
            "net_sales": "54.60",
            "currency": "USD",
        },
    ]
    hotelrunner_rows = [
        {
            "date": "2050-01-01",
            "year": 2050,
            "booking_id": "HR20500101",
            "agency_id": "AG001",
            "agency_name": "Atlas Partners",
            "channel": "Booking.com",
            "gross_sales": "99.00",
            "net_sales": "90.09",
            "currency": "USD",
        },
        {
            "date": "2050-01-01",
            "year": 2050,
            "booking_id": "HR20500102",
            "agency_id": "DIRECT",
            "agency_name": "Direct Channel",
            "channel": "Direct",
            "gross_sales": "70.00",
            "net_sales": "63.70",
            "currency": "USD",
        },
        {
            "date": "2050-01-02",
            "year": 2050,
            "booking_id": "HR20500103",
            "agency_id": "AG001",
            "agency_name": "Atlas Partners",
            "channel": "Booking.com",
            "gross_sales": "100.00",
            "net_sales": "91.00",
            "currency": "USD",
        },
        {
            "date": "2050-01-02",
            "year": 2050,
            "booking_id": "HR20500104",
            "agency_id": "DIRECT",
            "agency_name": "Direct Channel",
            "channel": "Direct",
            "gross_sales": "50.00",
            "net_sales": "45.50",
            "currency": "USD",
        },
    ]
    _write_csv(
        normalized_root / "electra_sales_2050.csv",
        ["date", "year", "agency_id", "agency_name", "gross_sales", "net_sales", "currency"],
        electra_rows,
    )
    _write_csv(
        normalized_root / "hotelrunner_sales_2050.csv",
        ["date", "year", "booking_id", "agency_id", "agency_name", "channel", "gross_sales", "net_sales", "currency"],
        hotelrunner_rows,
    )


def _write_anomaly_fixture(normalized_root: Path) -> None:
    electra_rows: list[dict] = []
    hotelrunner_rows: list[dict] = []
    dates = ["2051-01-01", "2051-01-02", "2051-01-03", "2051-01-04"]
    for idx, date in enumerate(dates, start=1):
        electra_rows.extend(
            [
                {
                    "date": date,
                    "year": 2051,
                    "agency_id": "AG001",
                    "agency_name": "Atlas Partners",
                    "gross_sales": "100.00",
                    "net_sales": "91.00",
                    "currency": "USD",
                },
                {
                    "date": date,
                    "year": 2051,
                    "agency_id": "AG002",
                    "agency_name": "Beacon Agency",
                    "gross_sales": "50.00",
                    "net_sales": "45.50",
                    "currency": "USD",
                },
            ]
        )
        ag001_hr_gross = "100.00" if idx < 4 else "40.00"
        ag001_hr_net = "91.00" if idx < 4 else "36.40"
        hotelrunner_rows.extend(
            [
                {
                    "date": date,
                    "year": 2051,
                    "booking_id": f"HR2051{idx:04d}01",
                    "agency_id": "AG001",
                    "agency_name": "Atlas Partners",
                    "channel": "Booking.com",
                    "gross_sales": ag001_hr_gross,
                    "net_sales": ag001_hr_net,
                    "currency": "USD",
                },
                {
                    "date": date,
                    "year": 2051,
                    "booking_id": f"HR2051{idx:04d}02",
                    "agency_id": "AG002",
                    "agency_name": "Beacon Agency",
                    "channel": "Expedia",
                    "gross_sales": "50.00",
                    "net_sales": "45.50",
                    "currency": "USD",
                },
            ]
        )
    hotelrunner_rows.append(
        {
            "date": "2051-01-04",
            "year": 2051,
            "booking_id": "HR20519999",
            "agency_id": "AGNEW",
            "agency_name": "Nova Ventures",
            "channel": "Nova Channel",
            "gross_sales": "20.00",
            "net_sales": "18.20",
            "currency": "USD",
        }
    )
    _write_csv(
        normalized_root / "electra_sales_2051.csv",
        ["date", "year", "agency_id", "agency_name", "gross_sales", "net_sales", "currency"],
        electra_rows,
    )
    _write_csv(
        normalized_root / "hotelrunner_sales_2051.csv",
        ["date", "year", "booking_id", "agency_id", "agency_name", "channel", "gross_sales", "net_sales", "currency"],
        hotelrunner_rows,
    )


def test_reconcile_daily_flags_rounding_timing_and_unknown(tmp_path: Path) -> None:
    normalized_root = _normalize_sources(tmp_path, [2025, 2026])
    df = reconcile_daily([2025, 2026], normalized_root, normalized_root)
    rows = df.to_dict("records")
    assert len(rows) >= 60

    by_key = {(int(r["year"]), str(r["date"])): r for r in rows}

    rounding_2025 = by_key[(2025, "2025-02-19")]
    assert rounding_2025["status"] == "MATCH"
    assert rounding_2025["reason_code"] == "ROUNDING"
    assert float(rounding_2025["delta"]) == pytest.approx(-0.75, abs=1e-6)

    timing_a = by_key[(2025, "2025-03-13")]
    timing_b = by_key[(2025, "2025-03-19")]
    assert timing_a["status"] == "MISMATCH"
    assert timing_b["status"] == "MISMATCH"
    assert timing_a["reason_code"] == "TIMING"
    assert timing_b["reason_code"] == "TIMING"
    assert float(timing_a["delta"]) == pytest.approx(50.0, abs=1e-6)
    assert float(timing_b["delta"]) == pytest.approx(-50.0, abs=1e-6)

    unknown_2025 = by_key[(2025, "2025-05-25")]
    assert unknown_2025["status"] == "MISMATCH"
    assert unknown_2025["reason_code"] == "UNKNOWN"
    assert float(unknown_2025["delta"]) == pytest.approx(-7.0, abs=1e-6)

    unknown_2026 = by_key[(2026, "2026-06-19")]
    assert unknown_2026["status"] == "MISMATCH"
    assert unknown_2026["reason_code"] == "UNKNOWN"
    assert float(unknown_2026["delta"]) == pytest.approx(6.0, abs=1e-6)


def test_reconcile_daily_detects_fee_and_rollups_with_custom_fixture(tmp_path: Path) -> None:
    normalized_root = tmp_path / "normalized"
    _write_custom_reconcile_fixture(normalized_root)
    df = reconcile_daily([2030], normalized_root, normalized_root)
    rows = df.to_dict("records")
    by_date = {str(r["date"]): r for r in rows}

    assert by_date["2030-01-01"]["reason_code"] == "ROUNDING"
    assert by_date["2030-01-02"]["reason_code"] == "TIMING"
    assert by_date["2030-01-03"]["reason_code"] == "TIMING"
    assert by_date["2030-01-04"]["reason_code"] == "FEE"
    assert by_date["2030-01-05"]["reason_code"] == "UNKNOWN"

    rollups = compute_year_rollups(df)
    assert rollups == [
        {
            "year": 2030,
            "match_count": 1,
            "mismatch_count": 4,
            "mismatch_abs_total": 110.0,
        }
    ]
    if hasattr(df, "attrs"):
        assert df.attrs.get("year_rollups") == rollups
    else:
        assert getattr(df, "year_rollups", None) == rollups


def test_reconcile_daily_requires_year_files(tmp_path: Path) -> None:
    normalized_root = tmp_path / "normalized"
    normalized_root.mkdir(parents=True, exist_ok=True)
    with pytest.raises(ValueError, match="normalized data missing for years"):
        reconcile_daily([2025], normalized_root, normalized_root)


def test_reconcile_monthly_aggregates_and_sets_status(tmp_path: Path) -> None:
    normalized_root = tmp_path / "normalized"
    _write_monthly_reconcile_fixture(normalized_root)

    df = reconcile_monthly([2040], normalized_root, normalized_root)
    rows = df.to_dict("records")

    assert rows == [
        {
            "year": 2040,
            "month": "2040-01",
            "electra_gross": 220.0,
            "hr_gross": 210.0,
            "delta": 10.0,
            "status": "MISMATCH",
        },
        {
            "year": 2040,
            "month": "2040-02",
            "electra_gross": 100.0,
            "hr_gross": 99.6,
            "delta": 0.4,
            "status": "MATCH",
        },
    ]


def test_reconcile_monthly_requires_year_files(tmp_path: Path) -> None:
    normalized_root = tmp_path / "normalized"
    normalized_root.mkdir(parents=True, exist_ok=True)
    with pytest.raises(ValueError, match="normalized data missing for years"):
        reconcile_monthly([2025], normalized_root, normalized_root)


def test_reconcile_by_dim_daily_and_monthly(tmp_path: Path) -> None:
    normalized_root = tmp_path / "normalized"
    _write_dim_fixture(normalized_root)

    daily = reconcile_by_dim_daily([2050], dim="agency", normalized_root_electra=normalized_root, normalized_root_hr=normalized_root)
    daily_rows = daily.to_dict("records")
    assert daily_rows == [
        {
            "date": "2050-01-01",
            "year": 2050,
            "dim_value": "AG001",
            "electra_gross": 100.0,
            "hr_gross": 99.0,
            "delta": 1.0,
            "status": "MATCH",
            "reason_code": "ROUNDING",
        },
        {
            "date": "2050-01-01",
            "year": 2050,
            "dim_value": "DIRECT",
            "electra_gross": 50.0,
            "hr_gross": 70.0,
            "delta": -20.0,
            "status": "MISMATCH",
            "reason_code": "UNKNOWN",
        },
        {
            "date": "2050-01-02",
            "year": 2050,
            "dim_value": "AG001",
            "electra_gross": 120.0,
            "hr_gross": 100.0,
            "delta": 20.0,
            "status": "MISMATCH",
            "reason_code": "UNKNOWN",
        },
        {
            "date": "2050-01-02",
            "year": 2050,
            "dim_value": "DIRECT",
            "electra_gross": 60.0,
            "hr_gross": 50.0,
            "delta": 10.0,
            "status": "MISMATCH",
            "reason_code": "UNKNOWN",
        },
    ]

    monthly = reconcile_by_dim_monthly(
        [2050], dim="agency", normalized_root_electra=normalized_root, normalized_root_hr=normalized_root
    )
    monthly_rows = monthly.to_dict("records")
    assert monthly_rows == [
        {
            "year": 2050,
            "month": "2050-01",
            "dim_value": "AG001",
            "electra_gross": 220.0,
            "hr_gross": 199.0,
            "delta": 21.0,
            "status": "MISMATCH",
            "reason_code": "UNKNOWN",
        },
        {
            "year": 2050,
            "month": "2050-01",
            "dim_value": "DIRECT",
            "electra_gross": 110.0,
            "hr_gross": 120.0,
            "delta": -10.0,
            "status": "MISMATCH",
            "reason_code": "UNKNOWN",
        },
    ]


def test_detect_anomalies_daily_by_dim_flags_spike_drop_new_agency_and_top_contributor(tmp_path: Path) -> None:
    normalized_root = tmp_path / "normalized"
    _write_anomaly_fixture(normalized_root)

    anomalies_df = detect_anomalies_daily_by_dim(
        [2051], dim="agency", normalized_root_electra=normalized_root, normalized_root_hr=normalized_root
    )
    rows = anomalies_df.to_dict("records")
    by_type = {(str(r["period"]), str(r["dim_value"]), str(r["anomaly_type"])): r for r in rows}

    assert ("2051-01-04", "AG001", "DROP") in by_type
    assert by_type[("2051-01-04", "AG001", "DROP")]["severity_score"] > 50.0
    assert ("2051-01-04", "AGNEW", "NEW_DIM_VALUE") in by_type
    assert ("2051-01-04", "AG001", "TOP_MISMATCH_CONTRIBUTOR") in by_type
