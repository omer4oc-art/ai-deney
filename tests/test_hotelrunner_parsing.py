import csv
from pathlib import Path

import pytest

from ai_deney.parsing.hotelrunner_sales import (
    normalize_report_files,
    parse_daily_sales_csv,
    validate_requested_years_exist,
)


def test_hotelrunner_csv_parsing_and_normalization(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    fixture_root = repo_root / "fixtures" / "hotelrunner"
    normalized_root = tmp_path / "normalized"

    paths = [fixture_root / "daily_sales_2025.csv", fixture_root / "daily_sales_2026.csv"]
    out_paths = normalize_report_files(paths, normalized_root)

    assert sorted(p.name for p in out_paths) == ["hotelrunner_sales_2025.csv", "hotelrunner_sales_2026.csv"]
    for year in (2025, 2026):
        path = normalized_root / f"hotelrunner_sales_{year}.csv"
        assert path.exists()
        with path.open("r", encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
        assert len(rows) >= 30
        assert all(float(r["gross_sales"]) >= 0 for r in rows)
        assert {
            "date",
            "year",
            "booking_id",
            "agency_id",
            "agency_name",
            "channel",
            "gross_sales",
            "net_sales",
            "currency",
        } <= set(rows[0].keys())

    parsed = parse_daily_sales_csv(paths[0])
    assert len(parsed) >= 30
    assert parsed[0]["booking_id"].startswith("HR2025")
    assert parsed[0]["agency_id"] in {"AG001", "AG002", "AG003", "AG004", "AG005", "DIRECT"}


def test_hotelrunner_parser_rejects_missing_required_columns(tmp_path: Path) -> None:
    bad_csv = tmp_path / "missing_cols.csv"
    bad_csv.write_text(
        "date,booking_id,gross_sales,net_sales,currency\n2025-01-01,HR1,10.00,9.10,USD\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="required columns missing"):
        parse_daily_sales_csv(bad_csv)


def test_hotelrunner_parser_accepts_agency_dimension_without_channel(tmp_path: Path) -> None:
    csv_path = tmp_path / "agency_dim.csv"
    csv_path.write_text(
        (
            "date,booking_id,agency_id,agency_name,gross_sales,net_sales,currency\n"
            "2025-01-01,HR1,AG900,Agency Nine,10.00,9.10,USD\n"
        ),
        encoding="utf-8",
    )
    rows = parse_daily_sales_csv(csv_path)
    assert len(rows) == 1
    assert rows[0]["agency_id"] == "AG900"
    assert rows[0]["agency_name"] == "Agency Nine"
    assert rows[0]["channel"] == "Agency Nine"


def test_hotelrunner_parser_rejects_negative_gross(tmp_path: Path) -> None:
    bad_csv = tmp_path / "negative.csv"
    bad_csv.write_text(
        "date,booking_id,channel,gross_sales,net_sales,currency\n2025-01-01,HR1,Direct,-10.00,9.10,USD\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="negative gross_sales"):
        parse_daily_sales_csv(bad_csv)


def test_hotelrunner_validate_requested_years_exist(tmp_path: Path) -> None:
    (tmp_path / "hotelrunner_sales_2025.csv").write_text(
        "date,year,booking_id,channel,gross_sales,net_sales,currency\n",
        encoding="utf-8",
    )
    validate_requested_years_exist([2025], tmp_path)
    with pytest.raises(ValueError, match="normalized data missing for years"):
        validate_requested_years_exist([2026], tmp_path)
