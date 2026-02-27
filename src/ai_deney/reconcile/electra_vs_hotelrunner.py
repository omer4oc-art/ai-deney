"""Deterministic Electra vs HotelRunner reconciliation logic."""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

from ai_deney.parsing.hotelrunner_sales import validate_requested_years_exist as validate_hr_years_exist

try:  # pragma: no cover - optional dependency
    import pandas as pd  # type: ignore
except Exception:  # pragma: no cover
    pd = None


_ROUNDING_TOLERANCE = 1.0
_TIMING_TOLERANCE = 1.0
_FEE_TARGET_RATIO = 0.03
_FEE_RATIO_TOLERANCE = 0.0025
_FEE_MIN_BASE = 20.0


@dataclass
class _MiniDataFrame:
    """Minimal DataFrame-compatible object for environments without pandas."""

    rows: list[dict]
    year_rollups: list[dict] = field(default_factory=list)

    def to_dict(self, orient: str = "records") -> list[dict]:
        if orient != "records":
            raise ValueError("mini dataframe only supports orient='records'")
        return [dict(r) for r in self.rows]

    def __len__(self) -> int:
        return len(self.rows)


def _to_dataframe(rows: list[dict], year_rollups: list[dict] | None = None):
    rollups = [dict(r) for r in (year_rollups or [])]
    if pd is not None:
        df = pd.DataFrame(rows)
        try:
            df.attrs["year_rollups"] = rollups
        except Exception:
            pass
        return df
    return _MiniDataFrame(rows=rows, year_rollups=rollups)


def _validate_electra_years_exist(years: list[int], normalized_root: Path) -> None:
    missing: list[int] = []
    for year in years:
        path = normalized_root / f"electra_sales_{int(year)}.csv"
        if not path.exists():
            missing.append(int(year))
    if missing:
        raise ValueError(f"normalized data missing for years: {missing}")


def _read_electra_daily_totals(years: list[int], normalized_root: Path) -> dict[tuple[int, str], float]:
    _validate_electra_years_exist(years, normalized_root)
    out: dict[tuple[int, str], float] = {}
    for year in sorted(set(int(y) for y in years)):
        path = normalized_root / f"electra_sales_{year}.csv"
        with path.open("r", encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
        total_rows = [r for r in rows if r.get("agency_id") == "TOTAL"]
        if not total_rows:
            raise ValueError(f"electra TOTAL rows missing for year={year}: {path}")
        for row in total_rows:
            date = str(row["date"]).strip()
            out[(year, date)] = out.get((year, date), 0.0) + float(row["gross_sales"])
    return out


def _read_hotelrunner_daily_totals(years: list[int], normalized_root: Path) -> dict[tuple[int, str], float]:
    validate_hr_years_exist(years, normalized_root)
    out: dict[tuple[int, str], float] = {}
    for year in sorted(set(int(y) for y in years)):
        path = normalized_root / f"hotelrunner_sales_{year}.csv"
        with path.open("r", encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                date = str(row["date"]).strip()
                out[(year, date)] = out.get((year, date), 0.0) + float(row["gross_sales"])
    return out


def _is_rounding(delta: float) -> bool:
    return abs(delta) <= _ROUNDING_TOLERANCE


def _is_timing_pair(delta: float, neighbor_delta: float) -> bool:
    if abs(delta) <= _ROUNDING_TOLERANCE or abs(neighbor_delta) <= _ROUNDING_TOLERANCE:
        return False
    return abs(delta + neighbor_delta) <= _TIMING_TOLERANCE


def _is_fee_like(delta: float, electra_gross: float, hr_gross: float) -> bool:
    amount = abs(delta)
    if amount <= _ROUNDING_TOLERANCE:
        return False
    for base in (abs(electra_gross), abs(hr_gross)):
        if base < _FEE_MIN_BASE:
            continue
        ratio = amount / base
        if abs(ratio - _FEE_TARGET_RATIO) <= _FEE_RATIO_TOLERANCE:
            return True
    return False


def _df_rows(df_or_rows) -> list[dict]:
    if isinstance(df_or_rows, list):
        return [dict(r) for r in df_or_rows]
    if hasattr(df_or_rows, "to_dict"):
        return [dict(r) for r in df_or_rows.to_dict("records")]
    raise TypeError("expected list[dict] or dataframe-like object")


def compute_year_rollups(df_or_rows) -> list[dict]:
    """
    Build deterministic per-year reconciliation rollups.

    Output columns:
    - year
    - match_count
    - mismatch_count
    - mismatch_abs_total
    """
    rows = _df_rows(df_or_rows)
    by_year: dict[int, dict] = {}
    for row in rows:
        year = int(row["year"])
        bucket = by_year.setdefault(
            year,
            {
                "year": year,
                "match_count": 0,
                "mismatch_count": 0,
                "mismatch_abs_total": 0.0,
            },
        )
        if str(row.get("status")) == "MATCH":
            bucket["match_count"] += 1
        else:
            bucket["mismatch_count"] += 1
            bucket["mismatch_abs_total"] += abs(float(row.get("delta", 0.0)))

    rollups = []
    for year in sorted(by_year):
        bucket = dict(by_year[year])
        bucket["mismatch_abs_total"] = round(float(bucket["mismatch_abs_total"]), 2)
        rollups.append(bucket)
    return rollups


def reconcile_daily(years: list[int], normalized_root_electra: Path, normalized_root_hr: Path):
    """
    Reconcile daily gross sales between Electra and HotelRunner.

    Output columns:
    - date
    - year
    - electra_gross
    - hr_gross
    - delta (electra_gross - hr_gross)
    - status: MATCH | MISMATCH
    - reason_code: ROUNDING | TIMING | FEE | UNKNOWN
    """

    years_i = sorted(set(int(y) for y in years))
    electra_by_day = _read_electra_daily_totals(years_i, normalized_root_electra)
    hr_by_day = _read_hotelrunner_daily_totals(years_i, normalized_root_hr)
    keys = sorted(set(electra_by_day.keys()) | set(hr_by_day.keys()), key=lambda x: (x[0], x[1]))

    rows: list[dict] = []
    for year, date in keys:
        electra_gross = round(float(electra_by_day.get((year, date), 0.0)), 2)
        hr_gross = round(float(hr_by_day.get((year, date), 0.0)), 2)
        delta = round(electra_gross - hr_gross, 2)
        if _is_rounding(delta):
            status = "MATCH"
            reason = "ROUNDING"
        else:
            status = "MISMATCH"
            reason = "UNKNOWN"
        rows.append(
            {
                "date": date,
                "year": year,
                "electra_gross": electra_gross,
                "hr_gross": hr_gross,
                "delta": delta,
                "status": status,
                "reason_code": reason,
            }
        )

    # TIMING heuristic on observed day-window=1 (previous or next row in the year).
    rows_by_year: dict[int, list[dict]] = {}
    for row in rows:
        rows_by_year.setdefault(int(row["year"]), []).append(row)

    for year in rows_by_year:
        year_rows = rows_by_year[year]
        year_rows.sort(key=lambda r: str(r["date"]))
        for idx, row in enumerate(year_rows):
            if row["status"] != "MISMATCH":
                continue
            delta = float(row["delta"])
            prev_delta = float(year_rows[idx - 1]["delta"]) if idx > 0 else None
            next_delta = float(year_rows[idx + 1]["delta"]) if idx + 1 < len(year_rows) else None
            is_timing = False
            if prev_delta is not None and _is_timing_pair(delta, prev_delta):
                is_timing = True
            if next_delta is not None and _is_timing_pair(delta, next_delta):
                is_timing = True
            if is_timing:
                row["reason_code"] = "TIMING"

    # FEE heuristic applies to remaining mismatches not explained by timing.
    for year in rows_by_year:
        year_rows = rows_by_year[year]
        for row in year_rows:
            if row["status"] != "MISMATCH" or row["reason_code"] != "UNKNOWN":
                continue
            if _is_fee_like(
                delta=float(row["delta"]),
                electra_gross=float(row["electra_gross"]),
                hr_gross=float(row["hr_gross"]),
            ):
                row["reason_code"] = "FEE"

    rows.sort(key=lambda r: (r["year"], r["date"]))
    return _to_dataframe(rows, year_rollups=compute_year_rollups(rows))
