"""Deterministic analytics queries over normalized Electra sales data."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ai_deney.analytics.electra_validations import (
    read_normalized_rows,
    validate_agency_totals_match_summary,
    validate_no_negative_gross_sales,
    validate_requested_years_exist,
)
from ai_deney.parsing.electra_sales import TOTAL_AGENCY_ID

try:  # pragma: no cover - optional dependency
    import pandas as pd  # type: ignore
except Exception:  # pragma: no cover - deterministic fallback used in tests
    pd = None


@dataclass
class _MiniDataFrame:
    """
    Minimal DataFrame-compatible object for environments without pandas.
    """

    rows: list[dict]

    def to_dict(self, orient: str = "records") -> list[dict]:
        if orient != "records":
            raise ValueError("mini dataframe only supports orient='records'")
        return [dict(r) for r in self.rows]

    def __len__(self) -> int:
        return len(self.rows)


def _to_dataframe(rows: list[dict]):
    if pd is not None:
        return pd.DataFrame(rows)
    return _MiniDataFrame(rows)


def _normalized_root(normalized_root: Path | None) -> Path:
    if normalized_root is not None:
        return normalized_root
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / "data" / "normalized"


def _validated_rows(years: list[int], normalized_root: Path | None = None) -> list[dict]:
    root = _normalized_root(normalized_root)
    years_i = sorted(set(int(y) for y in years))
    validate_requested_years_exist(years_i, root)
    rows = read_normalized_rows(years_i, root)
    validate_no_negative_gross_sales(rows)
    validate_agency_totals_match_summary(rows)
    return rows


def get_sales_years(years: list[int], normalized_root: Path | None = None):
    """
    Return per-year summary totals from normalized data.
    """
    rows = _validated_rows(years, normalized_root=normalized_root)
    summary = [r for r in rows if r["agency_id"] == TOTAL_AGENCY_ID]
    summary_rows: list[dict] = []
    for year in sorted(set(int(r["year"]) for r in summary)):
        year_rows = [r for r in summary if int(r["year"]) == year]
        summary_rows.append(
            {
                "year": year,
                "gross_sales": round(sum(float(r["gross_sales"]) for r in year_rows), 2),
                "net_sales": round(sum(float(r["net_sales"]) for r in year_rows), 2),
                "currency": year_rows[0]["currency"] if year_rows else "USD",
            }
        )
    return _to_dataframe(summary_rows)


def get_sales_by_agency(years: list[int], normalized_root: Path | None = None):
    """
    Return grouped per-agency totals for requested years.
    """
    rows = _validated_rows(years, normalized_root=normalized_root)
    agency_rows = [r for r in rows if r["agency_id"] != TOTAL_AGENCY_ID]
    grouped: dict[tuple, dict] = {}
    for row in agency_rows:
        key = (int(row["year"]), row["agency_id"], row["agency_name"], row["currency"])
        if key not in grouped:
            grouped[key] = {
                "year": int(row["year"]),
                "agency_id": row["agency_id"],
                "agency_name": row["agency_name"],
                "gross_sales": 0.0,
                "net_sales": 0.0,
                "currency": row["currency"],
            }
        grouped[key]["gross_sales"] += float(row["gross_sales"])
        grouped[key]["net_sales"] += float(row["net_sales"])

    out = list(grouped.values())
    out.sort(key=lambda r: (r["year"], r["agency_id"]))
    for r in out:
        r["gross_sales"] = round(r["gross_sales"], 2)
        r["net_sales"] = round(r["net_sales"], 2)
    return _to_dataframe(out)


def get_sales_by_month(years: list[int], normalized_root: Path | None = None):
    """
    Return monthly totals using summary TOTAL rows.
    """
    rows = _validated_rows(years, normalized_root=normalized_root)
    summary_rows = [r for r in rows if r["agency_id"] == TOTAL_AGENCY_ID]
    grouped: dict[tuple[int, int, str], dict] = {}
    for row in summary_rows:
        year = int(row["year"])
        month = int(str(row["date"]).split("-")[1])
        key = (year, month, row["currency"])
        if key not in grouped:
            grouped[key] = {
                "year": year,
                "month": month,
                "gross_sales": 0.0,
                "net_sales": 0.0,
                "currency": row["currency"],
            }
        grouped[key]["gross_sales"] += float(row["gross_sales"])
        grouped[key]["net_sales"] += float(row["net_sales"])
    out = list(grouped.values())
    out.sort(key=lambda r: (r["year"], r["month"]))
    for row in out:
        row["gross_sales"] = round(row["gross_sales"], 2)
        row["net_sales"] = round(row["net_sales"], 2)
    return _to_dataframe(out)


def get_top_agencies(years: list[int], top_n: int = 5, normalized_root: Path | None = None):
    """
    Return top agencies by yearly gross_sales.
    """
    rows = _validated_rows(years, normalized_root=normalized_root)
    agency_rows = [r for r in rows if r["agency_id"] not in {TOTAL_AGENCY_ID}]
    grouped: dict[tuple[int, str, str, str], dict] = {}
    for row in agency_rows:
        key = (int(row["year"]), row["agency_id"], row["agency_name"], row["currency"])
        if key not in grouped:
            grouped[key] = {
                "year": int(row["year"]),
                "agency_id": row["agency_id"],
                "agency_name": row["agency_name"],
                "gross_sales": 0.0,
                "net_sales": 0.0,
                "currency": row["currency"],
            }
        grouped[key]["gross_sales"] += float(row["gross_sales"])
        grouped[key]["net_sales"] += float(row["net_sales"])

    by_year: dict[int, list[dict]] = {}
    for row in grouped.values():
        by_year.setdefault(int(row["year"]), []).append(row)

    out: list[dict] = []
    for year in sorted(by_year):
        ranked = sorted(
            by_year[year],
            key=lambda r: (-float(r["gross_sales"]), r["agency_id"]),
        )[: max(1, int(top_n))]
        for idx, row in enumerate(ranked, start=1):
            out.append(
                {
                    "year": year,
                    "rank": idx,
                    "agency_id": row["agency_id"],
                    "agency_name": row["agency_name"],
                    "gross_sales": round(float(row["gross_sales"]), 2),
                    "net_sales": round(float(row["net_sales"]), 2),
                    "currency": row["currency"],
                }
            )
    return _to_dataframe(out)


def get_direct_share(years: list[int], normalized_root: Path | None = None):
    """
    Return direct-vs-agencies gross share (%) by year.
    """
    rows = _validated_rows(years, normalized_root=normalized_root)
    agency_rows = [r for r in rows if r["agency_id"] not in {TOTAL_AGENCY_ID}]
    year_totals: dict[int, dict] = {}
    for row in agency_rows:
        year = int(row["year"])
        if year not in year_totals:
            year_totals[year] = {
                "year": year,
                "direct_gross_sales": 0.0,
                "agency_gross_sales": 0.0,
                "currency": row["currency"],
            }
        if row["agency_id"] == "DIRECT":
            year_totals[year]["direct_gross_sales"] += float(row["gross_sales"])
        else:
            year_totals[year]["agency_gross_sales"] += float(row["gross_sales"])

    out: list[dict] = []
    for year in sorted(year_totals):
        direct_gross = float(year_totals[year]["direct_gross_sales"])
        agency_gross = float(year_totals[year]["agency_gross_sales"])
        total = direct_gross + agency_gross
        direct_pct = (direct_gross / total * 100.0) if total else 0.0
        agency_pct = (agency_gross / total * 100.0) if total else 0.0
        out.append(
            {
                "year": year,
                "direct_gross_sales": round(direct_gross, 2),
                "agency_gross_sales": round(agency_gross, 2),
                "direct_share_pct": round(direct_pct, 2),
                "agency_share_pct": round(agency_pct, 2),
                "currency": year_totals[year]["currency"],
            }
        )
    return _to_dataframe(out)
