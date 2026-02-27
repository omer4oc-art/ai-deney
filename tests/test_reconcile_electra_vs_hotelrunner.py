import csv
from pathlib import Path
import shutil

import pytest

from ai_deney.connectors.electra_mock import ElectraMockConnector
from ai_deney.connectors.hotelrunner_mock import HotelRunnerMockConnector
from ai_deney.parsing.electra_sales import normalize_report_files as normalize_electra_report_files
from ai_deney.parsing.hotelrunner_sales import normalize_report_files as normalize_hotelrunner_report_files
from ai_deney.reconcile.electra_vs_hotelrunner import compute_year_rollups, reconcile_daily


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
            "channel": "DIRECT",
            "gross_sales": "99.50",
            "net_sales": "89.50",
            "currency": "USD",
        },
        {
            "date": "2030-01-02",
            "year": 2030,
            "booking_id": "B-002",
            "channel": "DIRECT",
            "gross_sales": "150.00",
            "net_sales": "140.00",
            "currency": "USD",
        },
        {
            "date": "2030-01-03",
            "year": 2030,
            "booking_id": "B-003",
            "channel": "DIRECT",
            "gross_sales": "200.00",
            "net_sales": "180.00",
            "currency": "USD",
        },
        {
            "date": "2030-01-04",
            "year": 2030,
            "booking_id": "B-004",
            "channel": "DIRECT",
            "gross_sales": "100.00",
            "net_sales": "90.00",
            "currency": "USD",
        },
        {
            "date": "2030-01-05",
            "year": 2030,
            "booking_id": "B-005",
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
        ["date", "year", "booking_id", "channel", "gross_sales", "net_sales", "currency"],
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
