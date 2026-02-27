"""Electra export adapter for canonical column mapping and validation."""

from __future__ import annotations

import csv
import re
from pathlib import Path

_SUPPORTED_SUFFIXES = {".csv", ".xlsx", ".xlsm"}
_SUPPORTED_REPORT_TYPES = {"sales_summary", "sales_by_agency"}

_REQUIRED_BY_REPORT = {
    "sales_summary": ("date", "gross_sales"),
    "sales_by_agency": ("date", "agency_id", "agency_name", "gross_sales"),
}

_ALIAS_MAP = {
    "date": ("date", "report_date", "transaction_date", "date_value"),
    "agency_id": ("agency_id", "agencyid", "agent_id", "agentid", "partner_id", "partnerid"),
    "agency_name": ("agency_name", "agency", "agencyname", "agent_name", "agentname", "partner_name"),
    "gross_sales": ("gross_sales", "gross", "gross_revenue", "grossrevenue", "gross_amount", "grossamount"),
    "net_sales": ("net_sales", "net", "net_revenue", "netrevenue", "net_amount", "netamount"),
    "currency": ("currency", "currency_code", "currencycode", "curr", "ccy"),
}


class ElectraAdapterError(ValueError):
    """Raised when Electra export files cannot be mapped into canonical schema."""


def _normalize_col(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name or "").strip().lower())


def _assert_supported_suffix(path: Path) -> None:
    if path.suffix.lower() not in _SUPPORTED_SUFFIXES:
        raise ElectraAdapterError(
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
            raise ElectraAdapterError(f"CSV must be UTF-8 readable: {path.name}") from exc
        except OSError as exc:
            raise ElectraAdapterError(f"unable to read file: {path}") from exc
        if not fieldnames:
            raise ElectraAdapterError(f"header mismatch in {path.name}: CSV header is empty")
        return fieldnames, rows

    try:
        from openpyxl import load_workbook  # type: ignore
    except Exception as exc:
        raise ElectraAdapterError(
            f"xlsx support not available for {path.name}: install openpyxl to enable .xlsx/.xlsm ingestion"
        ) from exc

    wb = load_workbook(filename=path, read_only=True, data_only=True)
    try:
        ws = wb.active
        values = ws.values
        try:
            first = next(values)
        except StopIteration as exc:
            raise ElectraAdapterError(f"header mismatch in {path.name}: spreadsheet is empty") from exc
        fieldnames = [str(v).strip() for v in first if str(v or "").strip()]
        if not fieldnames:
            raise ElectraAdapterError(f"header mismatch in {path.name}: spreadsheet header is empty")

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


def _resolve_mapping(report_type: str, fieldnames: list[str], path: Path) -> dict[str, str]:
    if report_type not in _SUPPORTED_REPORT_TYPES:
        raise ElectraAdapterError(f"unsupported electra report_type: {report_type}")

    lookup = _build_header_lookup(fieldnames)
    mapping: dict[str, str] = {}

    for canonical, aliases in _ALIAS_MAP.items():
        for alias in aliases:
            resolved = lookup.get(_normalize_col(alias))
            if resolved:
                mapping[canonical] = resolved
                break

    missing: list[str] = []
    for canonical in _REQUIRED_BY_REPORT[report_type]:
        if canonical not in mapping:
            aliases = ", ".join(_ALIAS_MAP[canonical])
            missing.append(f"{canonical} (aliases: {aliases})")

    if missing:
        raise ElectraAdapterError(
            f"header mismatch in {path.name}: required columns missing [{'; '.join(missing)}]"
        )

    return mapping


def _value(row: dict[str, object], key: str) -> str:
    raw = row.get(key)
    if raw is None:
        return ""
    return str(raw).strip()


def parse_electra_export(path: Path, report_type: str) -> list[dict[str, str]]:
    """Parse one Electra export into canonical row dictionaries."""
    _assert_supported_suffix(path)
    fieldnames, rows = _read_rows(path)
    mapping = _resolve_mapping(report_type=report_type, fieldnames=fieldnames, path=path)

    canonical_rows: list[dict[str, str]] = []
    for row in rows:
        date = _value(row, mapping["date"])
        if not date:
            continue

        out: dict[str, str] = {
            "date": date,
            "gross_sales": _value(row, mapping["gross_sales"]),
            "net_sales": _value(row, mapping.get("net_sales", "")) or "0",
            "currency": _value(row, mapping.get("currency", "")) or "USD",
        }

        if report_type == "sales_by_agency":
            out["agency_id"] = _value(row, mapping["agency_id"])
            out["agency_name"] = _value(row, mapping["agency_name"])

        canonical_rows.append(out)

    return canonical_rows


def validate_electra_export(path: Path, report_type: str) -> None:
    """Validate that Electra export columns are adapter-compatible."""
    parse_electra_export(path=path, report_type=report_type)
