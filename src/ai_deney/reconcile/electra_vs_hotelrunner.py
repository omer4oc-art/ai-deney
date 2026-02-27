"""Deterministic Electra vs HotelRunner reconciliation logic."""

from __future__ import annotations

import csv
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from ai_deney.mapping.loader import MappingBundle, enrich_row, load_mapping_bundle
from ai_deney.parsing.electra_sales import TOTAL_AGENCY_ID
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
_ANOMALY_TRAILING_WINDOW = 3
_ANOMALY_PCT_THRESHOLD = 0.20
_ANOMALY_TOP_N = 3
_DIM_AGENCY = "agency"
_DIM_CHANNEL = "channel"
_VALID_DIMS = {_DIM_AGENCY, _DIM_CHANNEL}


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


def _validate_dim(dim: str) -> str:
    clean = str(dim or "").strip().lower()
    if clean not in _VALID_DIMS:
        raise ValueError(f"unsupported dim: {dim}; expected one of: {sorted(_VALID_DIMS)}")
    return clean


def _normalize_agency_id(raw: str) -> str:
    out = []
    for ch in str(raw or "").strip().upper():
        if ch.isalnum():
            out.append(ch)
        elif ch in {" ", "-", ".", "/", "&"}:
            out.append("_")
    cleaned = "".join(out).strip("_")
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return cleaned or "UNKNOWN"


def _electra_dim_value(row: dict, dim: str) -> str | None:
    agency_id = str(row.get("agency_id") or "").strip()
    if agency_id == TOTAL_AGENCY_ID:
        return None
    if dim == _DIM_AGENCY:
        canon_agency_id = str(row.get("canon_agency_id") or "").strip()
        canon_agency_name = str(row.get("canon_agency_name") or "").strip()
        if canon_agency_id:
            return canon_agency_id
        if canon_agency_name:
            return canon_agency_name
        return agency_id or str(row.get("agency_name") or "").strip() or None
    canon_channel = str(row.get("canon_channel") or "").strip()
    if canon_channel:
        return canon_channel
    agency_name = str(row.get("agency_name") or "").strip()
    return agency_name or None


def _hotelrunner_dim_value(row: dict, dim: str) -> str | None:
    if dim == _DIM_AGENCY:
        canon_agency_id = str(row.get("canon_agency_id") or "").strip()
        canon_agency_name = str(row.get("canon_agency_name") or "").strip()
        if canon_agency_id:
            return canon_agency_id
        if canon_agency_name:
            return canon_agency_name
        agency_id = str(row.get("agency_id") or "").strip()
        if agency_id:
            return agency_id
        agency_name = str(row.get("agency_name") or "").strip()
        if agency_name:
            return agency_name
        channel = str(row.get("channel") or row.get("agency") or "").strip()
        if channel:
            return _normalize_agency_id(channel)
        return None
    canon_channel = str(row.get("canon_channel") or "").strip()
    if canon_channel:
        return canon_channel
    channel = str(row.get("channel") or row.get("agency_name") or row.get("agency") or "").strip()
    if channel:
        return channel
    agency_name = str(row.get("agency_name") or "").strip()
    return agency_name or None


def _read_electra_daily_by_dim(
    years: list[int], normalized_root: Path, dim: str, mapping: MappingBundle
) -> dict[tuple[int, str, str], float]:
    _validate_electra_years_exist(years, normalized_root)
    out: dict[tuple[int, str, str], float] = {}
    for year in sorted(set(int(y) for y in years)):
        path = normalized_root / f"electra_sales_{year}.csv"
        with path.open("r", encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                enriched = enrich_row(row, source_system="electra", mapping=mapping)
                dim_value = _electra_dim_value(enriched, dim=dim)
                if not dim_value:
                    continue
                date = str(enriched["date"]).strip()
                key = (year, date, dim_value)
                out[key] = out.get(key, 0.0) + float(enriched["gross_sales"])
    return out


def _read_hotelrunner_daily_by_dim(
    years: list[int], normalized_root: Path, dim: str, mapping: MappingBundle
) -> dict[tuple[int, str, str], float]:
    validate_hr_years_exist(years, normalized_root)
    out: dict[tuple[int, str, str], float] = {}
    for year in sorted(set(int(y) for y in years)):
        path = normalized_root / f"hotelrunner_sales_{year}.csv"
        with path.open("r", encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                enriched = enrich_row(row, source_system="hotelrunner", mapping=mapping)
                dim_value = _hotelrunner_dim_value(enriched, dim=dim)
                if not dim_value:
                    continue
                date = str(enriched["date"]).strip()
                key = (year, date, dim_value)
                out[key] = out.get(key, 0.0) + float(enriched["gross_sales"])
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


def _status_from_delta(delta: float) -> str:
    return "MATCH" if abs(delta) <= _ROUNDING_TOLERANCE else "MISMATCH"


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
        status = _status_from_delta(delta)
        reason = "ROUNDING" if status == "MATCH" else "UNKNOWN"
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


def reconcile_monthly(years: list[int], normalized_root_electra: Path, normalized_root_hr: Path):
    """
    Reconcile monthly gross sales between Electra and HotelRunner.

    Output columns:
    - year
    - month (YYYY-MM)
    - electra_gross
    - hr_gross
    - delta (electra_gross - hr_gross)
    - status: MATCH | MISMATCH
    """
    years_i = sorted(set(int(y) for y in years))
    electra_by_day = _read_electra_daily_totals(years_i, normalized_root_electra)
    hr_by_day = _read_hotelrunner_daily_totals(years_i, normalized_root_hr)
    day_keys = sorted(set(electra_by_day.keys()) | set(hr_by_day.keys()), key=lambda x: (x[0], x[1]))

    by_month: dict[tuple[int, str], dict] = {}
    for year, date in day_keys:
        month = str(date)[:7]
        bucket = by_month.setdefault(
            (year, month),
            {
                "year": year,
                "month": month,
                "electra_gross": 0.0,
                "hr_gross": 0.0,
            },
        )
        bucket["electra_gross"] += float(electra_by_day.get((year, date), 0.0))
        bucket["hr_gross"] += float(hr_by_day.get((year, date), 0.0))

    rows: list[dict] = []
    for year, month in sorted(by_month.keys(), key=lambda x: (x[0], x[1])):
        bucket = by_month[(year, month)]
        electra_gross = round(float(bucket["electra_gross"]), 2)
        hr_gross = round(float(bucket["hr_gross"]), 2)
        delta = round(electra_gross - hr_gross, 2)
        rows.append(
            {
                "year": year,
                "month": month,
                "electra_gross": electra_gross,
                "hr_gross": hr_gross,
                "delta": delta,
                "status": _status_from_delta(delta),
            }
        )

    return _to_dataframe(rows, year_rollups=compute_year_rollups(rows))


def reconcile_by_dim_daily(
    years: list[int],
    dim: str,
    normalized_root_electra: Path,
    normalized_root_hr: Path,
    mapping_agencies_path: Path | None = None,
    mapping_channels_path: Path | None = None,
):
    """
    Reconcile daily gross sales by a common dimension (agency/channel).

    Output columns:
    - date
    - year
    - dim_value
    - electra_gross
    - hr_gross
    - delta
    - status
    - reason_code
    """
    dim_clean = _validate_dim(dim)
    years_i = sorted(set(int(y) for y in years))
    mapping = load_mapping_bundle(
        mapping_agencies_path=mapping_agencies_path,
        mapping_channels_path=mapping_channels_path,
    )
    electra_by_dim = _read_electra_daily_by_dim(years_i, normalized_root_electra, dim=dim_clean, mapping=mapping)
    hr_by_dim = _read_hotelrunner_daily_by_dim(years_i, normalized_root_hr, dim=dim_clean, mapping=mapping)
    keys = sorted(
        set(electra_by_dim.keys()) | set(hr_by_dim.keys()),
        key=lambda x: (x[0], x[1], x[2]),
    )

    rows: list[dict] = []
    for year, date, dim_value in keys:
        electra_gross = round(float(electra_by_dim.get((year, date, dim_value), 0.0)), 2)
        hr_gross = round(float(hr_by_dim.get((year, date, dim_value), 0.0)), 2)
        delta = round(electra_gross - hr_gross, 2)
        status = _status_from_delta(delta)
        reason = "ROUNDING" if status == "MATCH" else "UNKNOWN"
        rows.append(
            {
                "date": date,
                "year": year,
                "dim_value": dim_value,
                "electra_gross": electra_gross,
                "hr_gross": hr_gross,
                "delta": delta,
                "status": status,
                "reason_code": reason,
            }
        )

    # TIMING and FEE heuristics are applied per (year, dim_value) trajectory.
    rows_by_bucket: dict[tuple[int, str], list[dict]] = defaultdict(list)
    for row in rows:
        rows_by_bucket[(int(row["year"]), str(row["dim_value"]))].append(row)

    for bucket_key in rows_by_bucket:
        bucket_rows = rows_by_bucket[bucket_key]
        bucket_rows.sort(key=lambda r: str(r["date"]))
        for idx, row in enumerate(bucket_rows):
            if row["status"] != "MISMATCH":
                continue
            delta = float(row["delta"])
            prev_delta = float(bucket_rows[idx - 1]["delta"]) if idx > 0 else None
            next_delta = float(bucket_rows[idx + 1]["delta"]) if idx + 1 < len(bucket_rows) else None
            is_timing = False
            if prev_delta is not None and _is_timing_pair(delta, prev_delta):
                is_timing = True
            if next_delta is not None and _is_timing_pair(delta, next_delta):
                is_timing = True
            if is_timing:
                row["reason_code"] = "TIMING"

    for bucket_key in rows_by_bucket:
        for row in rows_by_bucket[bucket_key]:
            if row["status"] != "MISMATCH" or row["reason_code"] != "UNKNOWN":
                continue
            if _is_fee_like(
                delta=float(row["delta"]),
                electra_gross=float(row["electra_gross"]),
                hr_gross=float(row["hr_gross"]),
            ):
                row["reason_code"] = "FEE"

    rows.sort(key=lambda r: (r["year"], r["date"], r["dim_value"]))
    return _to_dataframe(rows, year_rollups=compute_year_rollups(rows))


def reconcile_by_dim_monthly(
    years: list[int],
    dim: str,
    normalized_root_electra: Path,
    normalized_root_hr: Path,
    mapping_agencies_path: Path | None = None,
    mapping_channels_path: Path | None = None,
):
    """
    Reconcile monthly gross sales by a common dimension (agency/channel).

    Output columns:
    - year
    - month
    - dim_value
    - electra_gross
    - hr_gross
    - delta
    - status
    - reason_code
    """
    dim_clean = _validate_dim(dim)
    daily_rows = _df_rows(
        reconcile_by_dim_daily(
            years=years,
            dim=dim_clean,
            normalized_root_electra=normalized_root_electra,
            normalized_root_hr=normalized_root_hr,
            mapping_agencies_path=mapping_agencies_path,
            mapping_channels_path=mapping_channels_path,
        )
    )
    by_month: dict[tuple[int, str, str], dict] = {}
    for row in daily_rows:
        year = int(row["year"])
        month = str(row["date"])[:7]
        dim_value = str(row["dim_value"])
        key = (year, month, dim_value)
        bucket = by_month.setdefault(
            key,
            {
                "year": year,
                "month": month,
                "dim_value": dim_value,
                "electra_gross": 0.0,
                "hr_gross": 0.0,
            },
        )
        bucket["electra_gross"] += float(row["electra_gross"])
        bucket["hr_gross"] += float(row["hr_gross"])

    rows: list[dict] = []
    for key in sorted(by_month.keys(), key=lambda x: (x[0], x[1], x[2])):
        bucket = by_month[key]
        electra_gross = round(float(bucket["electra_gross"]), 2)
        hr_gross = round(float(bucket["hr_gross"]), 2)
        delta = round(electra_gross - hr_gross, 2)
        status = _status_from_delta(delta)
        rows.append(
            {
                "year": int(bucket["year"]),
                "month": str(bucket["month"]),
                "dim_value": str(bucket["dim_value"]),
                "electra_gross": electra_gross,
                "hr_gross": hr_gross,
                "delta": delta,
                "status": status,
                "reason_code": "ROUNDING" if status == "MATCH" else "UNKNOWN",
            }
        )

    return _to_dataframe(rows, year_rollups=compute_year_rollups(rows))


def _stable_period_key(value: str) -> tuple[int, str]:
    text = str(value)
    year = int(text[:4]) if len(text) >= 4 and text[:4].isdigit() else 0
    return year, text


def _detect_anomalies_from_rows(rows: list[dict], period_field: str) -> list[dict]:
    anomalies: list[dict] = []
    rows_sorted = sorted(
        rows,
        key=lambda r: (
            int(r.get("year", 0)),
            str(r.get(period_field, "")),
            str(r.get("dim_value", "")),
        ),
    )

    history_electra: dict[str, list[float]] = defaultdict(list)
    history_hr: dict[str, list[float]] = defaultdict(list)
    first_period_by_dim: dict[str, str] = {}
    all_periods = sorted({str(r.get(period_field, "")) for r in rows_sorted}, key=_stable_period_key)
    first_global_period = all_periods[0] if all_periods else ""

    for row in rows_sorted:
        period = str(row.get(period_field, ""))
        dim_value = str(row.get("dim_value", ""))
        electra_gross = float(row.get("electra_gross", 0.0))
        hr_gross = float(row.get("hr_gross", 0.0))
        first_period_by_dim.setdefault(dim_value, period)

        for history, value, label in (
            (history_electra, electra_gross, "Electra"),
            (history_hr, hr_gross, "HotelRunner"),
        ):
            trailing = history[dim_value]
            if len(trailing) >= _ANOMALY_TRAILING_WINDOW:
                avg = sum(trailing[-_ANOMALY_TRAILING_WINDOW:]) / float(_ANOMALY_TRAILING_WINDOW)
                if avg > 0:
                    pct_change = (value - avg) / avg
                    if abs(pct_change) > _ANOMALY_PCT_THRESHOLD:
                        anomaly_type = "SPIKE" if pct_change > 0 else "DROP"
                        anomalies.append(
                            {
                                "period": period,
                                "dim_value": dim_value,
                                "anomaly_type": anomaly_type,
                                "severity_score": round(abs(pct_change) * 100.0, 2),
                                "explanation": (
                                    f"{label} changed {pct_change * 100.0:.1f}% vs trailing "
                                    f"{_ANOMALY_TRAILING_WINDOW}-period avg ({avg:.2f})."
                                ),
                            }
                        )
            trailing.append(value)

    for dim_value, first_period in sorted(first_period_by_dim.items(), key=lambda x: (x[1], x[0])):
        if not first_global_period or first_period == first_global_period:
            continue
        row = next(
            (
                r
                for r in rows_sorted
                if str(r.get("dim_value", "")) == dim_value and str(r.get(period_field, "")) == first_period
            ),
            None,
        )
        if row is None:
            continue
        gross = max(float(row.get("electra_gross", 0.0)), float(row.get("hr_gross", 0.0)))
        anomalies.append(
            {
                "period": first_period,
                "dim_value": dim_value,
                "anomaly_type": "NEW_DIM_VALUE",
                "severity_score": round(gross, 2),
                "explanation": f"'{dim_value}' first appears in {first_period}.",
            }
        )

    by_period: dict[str, list[dict]] = defaultdict(list)
    for row in rows_sorted:
        if str(row.get("status", "")) != "MISMATCH":
            continue
        by_period[str(row.get(period_field, ""))].append(row)

    for period in sorted(by_period.keys(), key=_stable_period_key):
        mismatches = sorted(
            by_period[period],
            key=lambda r: (
                -abs(float(r.get("delta", 0.0))),
                str(r.get("dim_value", "")),
            ),
        )
        for rank, row in enumerate(mismatches[:_ANOMALY_TOP_N], start=1):
            delta = float(row.get("delta", 0.0))
            anomalies.append(
                {
                    "period": period,
                    "dim_value": str(row.get("dim_value", "")),
                    "anomaly_type": "TOP_MISMATCH_CONTRIBUTOR",
                    "severity_score": round(abs(delta), 2),
                    "explanation": f"Rank {rank} mismatch contributor with delta {delta:.2f}.",
                }
            )

    anomalies.sort(
        key=lambda r: (
            _stable_period_key(str(r.get("period", ""))),
            str(r.get("dim_value", "")),
            str(r.get("anomaly_type", "")),
            -float(r.get("severity_score", 0.0)),
        )
    )
    return anomalies


def detect_anomalies_daily_by_dim(
    years: list[int],
    dim: str,
    normalized_root_electra: Path,
    normalized_root_hr: Path,
    mapping_agencies_path: Path | None = None,
    mapping_channels_path: Path | None = None,
):
    """
    Detect deterministic anomalies from daily by-dimension reconciliation rows.

    Output columns:
    - period
    - dim_value
    - anomaly_type
    - severity_score
    - explanation
    """
    rows = _df_rows(
        reconcile_by_dim_daily(
            years=years,
            dim=dim,
            normalized_root_electra=normalized_root_electra,
            normalized_root_hr=normalized_root_hr,
            mapping_agencies_path=mapping_agencies_path,
            mapping_channels_path=mapping_channels_path,
        )
    )
    anomalies = _detect_anomalies_from_rows(rows, period_field="date")
    return _to_dataframe(anomalies)


def detect_anomalies_monthly_by_dim(
    years: list[int],
    dim: str,
    normalized_root_electra: Path,
    normalized_root_hr: Path,
    mapping_agencies_path: Path | None = None,
    mapping_channels_path: Path | None = None,
):
    """
    Detect deterministic anomalies from monthly by-dimension reconciliation rows.

    Output columns:
    - period
    - dim_value
    - anomaly_type
    - severity_score
    - explanation
    """
    rows = _df_rows(
        reconcile_by_dim_monthly(
            years=years,
            dim=dim,
            normalized_root_electra=normalized_root_electra,
            normalized_root_hr=normalized_root_hr,
            mapping_agencies_path=mapping_agencies_path,
            mapping_channels_path=mapping_channels_path,
        )
    )
    anomalies = _detect_anomalies_from_rows(rows, period_field="month")
    return _to_dataframe(anomalies)
