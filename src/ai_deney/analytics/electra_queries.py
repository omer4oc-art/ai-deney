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

