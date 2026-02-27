"""Parsing + normalization helpers for HotelRunner daily sales fixtures."""

from __future__ import annotations

import csv
from pathlib import Path

NORMALIZED_COLUMNS = [
    "date",
    "year",
    "booking_id",
    "agency_id",
    "agency_name",
    "channel",
    "gross_sales",
    "net_sales",
    "currency",
]

_REQUIRED_BASE_COLUMNS = {"date", "gross_sales", "net_sales", "currency"}
_ID_COLUMNS = ("booking_id", "invoice_id")
_CHANNEL_COLUMNS = ("channel", "agency")

_CHANNEL_TO_AGENCY: dict[str, tuple[str, str]] = {
    "direct": ("DIRECT", "Direct Channel"),
    "booking.com": ("AG001", "Atlas Partners"),
    "expedia": ("AG002", "Beacon Agency"),
    "agoda": ("AG003", "Cedar Travel"),
    "hotelbeds": ("AG004", "Drift Voyages"),
    "wholesaler": ("AG005", "Elm Holidays"),
    "wholesalerx": ("AG005", "Elm Holidays"),
}


def _pick_column(row: dict, candidates: tuple[str, ...], label: str) -> str:
    for name in candidates:
        value = row.get(name)
        if value is not None and str(value).strip() != "":
            return str(value).strip()
    joined = ", ".join(candidates)
    raise ValueError(f"missing required {label} column (expected one of: {joined})")


def _safe_str(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_agency_id(raw: str) -> str:
    out = []
    for ch in raw.upper():
        if ch.isalnum():
            out.append(ch)
        elif ch in {" ", "-", ".", "/", "&"}:
            out.append("_")
    cleaned = "".join(out).strip("_")
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return cleaned or "UNKNOWN"


def _resolve_agency(row: dict, channel: str) -> tuple[str, str]:
    agency_id = _safe_str(row.get("agency_id"))
    agency_name = _safe_str(row.get("agency_name"))
    if agency_id and agency_name:
        return agency_id, agency_name

    mapped = _CHANNEL_TO_AGENCY.get(channel.lower())
    if mapped:
        default_id, default_name = mapped
    else:
        default_id, default_name = _normalize_agency_id(channel), channel or "Unknown Agency"

    if not agency_id:
        agency_id = default_id
    if not agency_name:
        agency_name = default_name
    return agency_id, agency_name


def _validate_required_input_columns(fieldnames: list[str] | None) -> None:
    names = {str(n).strip() for n in (fieldnames or []) if n is not None}
    missing = sorted(c for c in _REQUIRED_BASE_COLUMNS if c not in names)
    has_id = any(c in names for c in _ID_COLUMNS)
    has_channel = any(c in names for c in _CHANNEL_COLUMNS)
    if missing or (not has_id) or (not has_channel):
        missing_parts: list[str] = []
        if missing:
            missing_parts.append(", ".join(missing))
        if not has_id:
            missing_parts.append("booking_id|invoice_id")
        if not has_channel:
            missing_parts.append("channel|agency")
        raise ValueError(f"required columns missing: {', '.join(missing_parts)}")


def parse_daily_sales_csv(path: Path) -> list[dict]:
    """Parse ``daily_sales_<year>.csv`` fixture rows."""
    rows: list[dict] = []
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        _validate_required_input_columns(reader.fieldnames)
        for row in reader:
            date = str(row["date"]).strip()
            year = int(date.split("-", 1)[0])
            channel = _pick_column(row, _CHANNEL_COLUMNS, "channel")
            agency_id, agency_name = _resolve_agency(row, channel=channel)
            rows.append(
                {
                    "date": date,
                    "year": year,
                    "booking_id": _pick_column(row, _ID_COLUMNS, "id"),
                    "agency_id": agency_id,
                    "agency_name": agency_name,
                    "channel": channel,
                    "gross_sales": float(row["gross_sales"]),
                    "net_sales": float(row["net_sales"]),
                    "currency": (row.get("currency") or "USD").strip() or "USD",
                }
            )
    validate_no_negative_gross_sales(rows)
    return rows


def _dedupe_rows(rows: list[dict]) -> list[dict]:
    seen = set()
    out: list[dict] = []
    for row in rows:
        key = tuple(str(row[c]) for c in NORMALIZED_COLUMNS)
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def validate_no_negative_gross_sales(rows: list[dict]) -> None:
    """Raise if any row has negative gross_sales."""
    bad = [r for r in rows if float(r["gross_sales"]) < 0]
    if bad:
        raise ValueError(f"negative gross_sales rows found: {len(bad)}")


def validate_requested_years_exist(years: list[int], normalized_root: Path) -> None:
    """Raise if any requested year does not have a normalized CSV."""
    missing: list[int] = []
    for year in years:
        path = normalized_root / f"hotelrunner_sales_{int(year)}.csv"
        if not path.exists():
            missing.append(int(year))
    if missing:
        raise ValueError(f"normalized data missing for years: {missing}")


def write_normalized_yearly(records: list[dict], output_root: Path) -> list[Path]:
    """Write/update deterministic normalized yearly CSVs."""
    output_root.mkdir(parents=True, exist_ok=True)
    years = sorted({int(r["year"]) for r in records})
    out_paths: list[Path] = []

    for year in years:
        year_rows = [r for r in records if int(r["year"]) == year]
        out_path = output_root / f"hotelrunner_sales_{year}.csv"

        merged_rows: list[dict] = []
        if out_path.exists():
            with out_path.open("r", encoding="utf-8", newline="") as f:
                for row in csv.DictReader(f):
                    merged_rows.append(
                        {
                            "date": row["date"],
                            "year": int(row["year"]),
                            "booking_id": row["booking_id"],
                            "agency_id": row.get("agency_id", ""),
                            "agency_name": row.get("agency_name", ""),
                            "channel": row.get("channel") or row.get("agency_name") or "",
                            "gross_sales": float(row["gross_sales"]),
                            "net_sales": float(row.get("net_sales", "") or 0.0),
                            "currency": row.get("currency", "USD") or "USD",
                        }
                    )

        merged_rows.extend(year_rows)
        merged_rows = _dedupe_rows(merged_rows)
        merged_rows.sort(key=lambda r: (r["date"], r["booking_id"]))

        with out_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=NORMALIZED_COLUMNS)
            writer.writeheader()
            for row in merged_rows:
                writer.writerow(
                    {
                        "date": row["date"],
                        "year": int(row["year"]),
                        "booking_id": row["booking_id"],
                        "agency_id": row["agency_id"],
                        "agency_name": row["agency_name"],
                        "channel": row["channel"],
                        "gross_sales": f"{float(row['gross_sales']):.2f}",
                        "net_sales": f"{float(row['net_sales']):.2f}",
                        "currency": row.get("currency", "USD") or "USD",
                    }
                )
        out_paths.append(out_path)

    return out_paths


def normalize_report_files(report_paths: list[Path], output_root: Path) -> list[Path]:
    """Parse one HotelRunner report batch and write normalized yearly CSV files."""
    records: list[dict] = []
    for path in report_paths:
        if path.suffix.lower() != ".csv":
            raise ValueError(f"unsupported report file: {path}")
        records.extend(parse_daily_sales_csv(path))
    return write_normalized_yearly(records, output_root=output_root)
