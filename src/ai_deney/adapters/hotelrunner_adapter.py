"""HotelRunner export adapter for canonical column mapping and validation."""

from __future__ import annotations

import csv
import re
from pathlib import Path

_SUPPORTED_SUFFIXES = {".csv", ".xlsx", ".xlsm"}

_BASE_REQUIRED = ("date", "gross_sales")

_ALIAS_MAP = {
    "date": ("date", "report_date", "transaction_date", "date_value"),
    "booking_id": ("booking_id", "bookingid", "reservation_id", "reservationid", "invoice_id", "invoiceid"),
    "channel": ("channel", "agency", "source", "sales_channel", "saleschannel"),
    "agency_id": ("agency_id", "agencyid", "agent_id", "agentid", "agency_code", "agencycode"),
    "agency_name": ("agency_name", "agencyname", "agent_name", "agentname", "agency_label", "agencylabel"),
    "gross_sales": ("gross_sales", "gross", "gross_revenue", "grossrevenue", "gross_amount", "grossamount"),
    "net_sales": ("net_sales", "net", "net_revenue", "netrevenue", "net_amount", "netamount"),
    "currency": ("currency", "currency_code", "currencycode", "curr", "ccy"),
}


class HotelRunnerAdapterError(ValueError):
    """Raised when HotelRunner export files cannot be mapped into canonical schema."""


def _normalize_col(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name or "").strip().lower())


def _assert_supported_suffix(path: Path) -> None:
    if path.suffix.lower() not in _SUPPORTED_SUFFIXES:
        raise HotelRunnerAdapterError(
            f"unsupported file type for {path.name}: expected one of {sorted(_SUPPORTED_SUFFIXES)}"
        )


def _read_rows(path: Path) -> tuple[list[str], list[dict[str, object]]]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        try:
            with path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                fieldnames = [str(name).strip() for name in (reader.fieldnames or []) if str(name).strip()]
                rows = [dict(row) for row in reader]
        except UnicodeDecodeError as exc:
            raise HotelRunnerAdapterError(f"CSV must be UTF-8 readable: {path.name}") from exc
        except OSError as exc:
            raise HotelRunnerAdapterError(f"unable to read file: {path}") from exc
        if not fieldnames:
            raise HotelRunnerAdapterError(f"header mismatch in {path.name}: CSV header is empty")
        return fieldnames, rows

    try:
        from openpyxl import load_workbook  # type: ignore
    except Exception as exc:
        raise HotelRunnerAdapterError(
            f"xlsx support not available for {path.name}: install openpyxl to enable .xlsx/.xlsm ingestion"
        ) from exc

    wb = load_workbook(filename=path, read_only=True, data_only=True)
    try:
        ws = wb.active
        values = ws.values
        try:
            first = next(values)
        except StopIteration as exc:
            raise HotelRunnerAdapterError(f"header mismatch in {path.name}: spreadsheet is empty") from exc
        fieldnames = [str(v).strip() for v in first if str(v or "").strip()]
        if not fieldnames:
            raise HotelRunnerAdapterError(f"header mismatch in {path.name}: spreadsheet header is empty")

        rows: list[dict[str, object]] = []
        for row_values in values:
            row_dict: dict[str, object] = {}
            for idx, col in enumerate(fieldnames):
                value = row_values[idx] if idx < len(row_values) else ""
                row_dict[col] = value
            rows.append(row_dict)
        return fieldnames, rows
    finally:
        wb.close()


def _build_header_lookup(fieldnames: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for name in fieldnames:
        key = _normalize_col(name)
        if key and key not in out:
            out[key] = name
    return out


def _resolve_mapping(fieldnames: list[str], path: Path) -> dict[str, str]:
    lookup = _build_header_lookup(fieldnames)
    mapping: dict[str, str] = {}

    for canonical, aliases in _ALIAS_MAP.items():
        for alias in aliases:
            resolved = lookup.get(_normalize_col(alias))
            if resolved:
                mapping[canonical] = resolved
                break

    missing: list[str] = []
    for canonical in _BASE_REQUIRED:
        if canonical not in mapping:
            aliases = ", ".join(_ALIAS_MAP[canonical])
            missing.append(f"{canonical} (aliases: {aliases})")

    has_booking = "booking_id" in mapping
    has_channel = "channel" in mapping
    has_agency_dim = "agency_id" in mapping and "agency_name" in mapping

    if not has_booking:
        missing.append("booking_id (aliases include invoice_id, reservation_id)")
    if not (has_channel or has_agency_dim):
        missing.append("channel (or both agency_id + agency_name)")

    if missing:
        raise HotelRunnerAdapterError(
            f"header mismatch in {path.name}: required columns missing [{'; '.join(missing)}]"
        )

    return mapping


def _value(row: dict[str, object], key: str) -> str:
    raw = row.get(key)
    if raw is None:
        return ""
    return str(raw).strip()


def parse_hotelrunner_export(path: Path) -> list[dict[str, str]]:
    """Parse one HotelRunner export into canonical row dictionaries."""
    _assert_supported_suffix(path)
    fieldnames, rows = _read_rows(path)
    mapping = _resolve_mapping(fieldnames=fieldnames, path=path)

    canonical_rows: list[dict[str, str]] = []
    for row in rows:
        date = _value(row, mapping["date"])
        if not date:
            continue

        canonical_rows.append(
            {
                "date": date,
                "booking_id": _value(row, mapping["booking_id"]),
                "channel": _value(row, mapping.get("channel", "")),
                "agency_id": _value(row, mapping.get("agency_id", "")),
                "agency_name": _value(row, mapping.get("agency_name", "")),
                "gross_sales": _value(row, mapping["gross_sales"]),
                "net_sales": _value(row, mapping.get("net_sales", "")) or "0",
                "currency": _value(row, mapping.get("currency", "")) or "USD",
            }
        )

    return canonical_rows


def validate_hotelrunner_export(path: Path) -> None:
    """Validate that HotelRunner export columns are adapter-compatible."""
    parse_hotelrunner_export(path=path)
