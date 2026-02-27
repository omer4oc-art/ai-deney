"""Validation helpers for inbox files prior to ingestion."""

from __future__ import annotations

import csv
from pathlib import Path

from ai_deney.inbox.scan import SelectedInboxFile

DEFAULT_MAX_FILE_SIZE_BYTES = 25 * 1024 * 1024

_ELECTRA_SUMMARY_REQUIRED = {"date", "gross_sales", "net_sales", "currency"}
_ELECTRA_AGENCY_REQUIRED = {"date", "agency_id", "agency_name", "gross_sales", "net_sales", "currency"}
_HOTELRUNNER_BASE_REQUIRED = {"date", "gross_sales", "net_sales", "currency"}
_HOTELRUNNER_ID_COLUMNS = {"booking_id", "invoice_id"}
_HOTELRUNNER_CHANNEL_COLUMNS = {"channel", "agency"}
_HOTELRUNNER_AGENCY_DIM_COLUMNS = {"agency_id", "agency_name"}


class InboxValidationError(ValueError):
    """Raised when inbox file content is invalid."""


def _format_cols(cols: set[str]) -> str:
    return ", ".join(sorted(cols))


def _assert_csv_suffix(path: Path) -> None:
    if path.suffix.lower() != ".csv":
        raise InboxValidationError(
            f"unsupported inbox file type for {path.name}: expected .csv based on workflow convention"
        )


def _assert_file_size(path: Path, max_file_size_bytes: int) -> None:
    size = int(path.stat().st_size)
    if size > int(max_file_size_bytes):
        raise InboxValidationError(
            f"inbox file too large: {path.name} is {size} bytes; limit is {int(max_file_size_bytes)} bytes"
        )


def _read_csv_header(path: Path) -> list[str]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            try:
                row = next(reader)
            except StopIteration as exc:
                raise InboxValidationError(f"empty CSV file: {path.name}") from exc
    except UnicodeDecodeError as exc:
        raise InboxValidationError(f"CSV must be UTF-8 readable: {path.name}") from exc
    except OSError as exc:
        raise InboxValidationError(f"unable to read CSV file: {path}") from exc

    header = [str(col).strip() for col in row if str(col).strip()]
    if not header:
        raise InboxValidationError(f"CSV header is empty: {path.name}")
    return header


def _validate_electra_header(report_type: str, header: set[str], path: Path) -> None:
    if report_type == "sales_summary":
        required = _ELECTRA_SUMMARY_REQUIRED
    elif report_type == "sales_by_agency":
        required = _ELECTRA_AGENCY_REQUIRED
    else:
        raise InboxValidationError(f"unsupported electra report_type: {report_type}")

    missing = sorted(required - header)
    if missing:
        raise InboxValidationError(
            f"header mismatch in {path.name}: missing columns [{', '.join(missing)}]; "
            f"required columns are [{_format_cols(required)}]"
        )


def _validate_hotelrunner_header(report_type: str, header: set[str], path: Path) -> None:
    if report_type != "daily_sales":
        raise InboxValidationError(f"unsupported hotelrunner report_type: {report_type}")

    missing_base = sorted(_HOTELRUNNER_BASE_REQUIRED - header)
    has_id = bool(_HOTELRUNNER_ID_COLUMNS & header)
    has_channel = bool(_HOTELRUNNER_CHANNEL_COLUMNS & header)
    has_agency_dim = _HOTELRUNNER_AGENCY_DIM_COLUMNS.issubset(header)
    if missing_base or (not has_id) or (not (has_channel or has_agency_dim)):
        detail: list[str] = []
        if missing_base:
            detail.append(f"missing [{', '.join(missing_base)}]")
        if not has_id:
            detail.append("need one of [booking_id, invoice_id]")
        if not (has_channel or has_agency_dim):
            detail.append("need one of [channel, agency] or both [agency_id, agency_name]")
        raise InboxValidationError(
            f"header mismatch in {path.name}: " + "; ".join(detail)
        )


def validate_file(
    selected: SelectedInboxFile,
    max_file_size_bytes: int = DEFAULT_MAX_FILE_SIZE_BYTES,
) -> None:
    """Validate one selected inbox file for size, readability, and header schema."""
    path = selected.path
    if not path.exists() or not path.is_file():
        raise InboxValidationError(f"selected inbox file is missing or not a file: {path}")

    _assert_csv_suffix(path)
    _assert_file_size(path, max_file_size_bytes=max_file_size_bytes)
    header = set(_read_csv_header(path))

    if selected.source == "electra":
        _validate_electra_header(selected.report_type, header, path)
        return
    if selected.source == "hotelrunner":
        _validate_hotelrunner_header(selected.report_type, header, path)
        return
    raise InboxValidationError(f"unsupported source: {selected.source}")


def validate_selected_files(
    selected_files: list[SelectedInboxFile],
    max_file_size_bytes: int = DEFAULT_MAX_FILE_SIZE_BYTES,
) -> None:
    """Validate all selected files before copying/normalization."""
    for selected in sorted(
        selected_files,
        key=lambda s: (s.year, s.source, s.report_type, s.path.name),
    ):
        validate_file(selected=selected, max_file_size_bytes=max_file_size_bytes)
