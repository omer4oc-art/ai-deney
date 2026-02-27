"""Validation gates for normalized Electra sales rows."""

from __future__ import annotations

import csv
from pathlib import Path

from ai_deney.parsing.electra_sales import TOTAL_AGENCY_ID


def validate_requested_years_exist(years: list[int], normalized_root: Path) -> None:
    """Raise if any requested year does not have a normalized CSV."""
    missing: list[int] = []
    for year in years:
        p = normalized_root / f"electra_sales_{int(year)}.csv"
        if not p.exists():
            missing.append(int(year))
    if missing:
        raise ValueError(f"normalized data missing for years: {missing}")


def validate_no_negative_gross_sales(rows: list[dict]) -> None:
    """Raise if any row has negative gross_sales."""
    bad = [r for r in rows if float(r["gross_sales"]) < 0]
    if bad:
        raise ValueError(f"negative gross_sales rows found: {len(bad)}")


def validate_agency_totals_match_summary(rows: list[dict], tolerance: float = 1e-6) -> None:
    """
    Validate per-year integrity:
    sum(non-TOTAL agencies) == TOTAL row.

    This cross-check runs only when both sides exist in a year:
    - at least one TOTAL row
    - at least one non-TOTAL row

    If only one side exists (summary-only or agency-only dataset), the check is
    skipped for that year.
    """
    years = sorted({int(r["year"]) for r in rows})
    for year in years:
        year_rows = [r for r in rows if int(r["year"]) == year]
        summary_rows = [r for r in year_rows if r["agency_id"] == TOTAL_AGENCY_ID]
        agency_rows = [r for r in year_rows if r["agency_id"] != TOTAL_AGENCY_ID]
        if not summary_rows or not agency_rows:
            continue
        total_gross = sum(float(r["gross_sales"]) for r in summary_rows)
        agency_gross = sum(float(r["gross_sales"]) for r in agency_rows)
        if abs(total_gross - agency_gross) > tolerance:
            raise ValueError(
                f"agency totals mismatch for year={year}: agencies={agency_gross:.6f} total={total_gross:.6f}"
            )


def read_normalized_rows(years: list[int], normalized_root: Path) -> list[dict]:
    """Load normalized rows for years from CSV files."""
    rows: list[dict] = []
    for year in sorted(set(int(y) for y in years)):
        path = normalized_root / f"electra_sales_{year}.csv"
        with path.open("r", encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                rows.append(
                    {
                        "date": row["date"],
                        "year": int(row["year"]),
                        "agency_id": row["agency_id"],
                        "agency_name": row["agency_name"],
                        "gross_sales": float(row["gross_sales"]),
                        "net_sales": float(row.get("net_sales", "") or 0.0),
                        "currency": row.get("currency", "USD") or "USD",
                    }
                )
    return rows
