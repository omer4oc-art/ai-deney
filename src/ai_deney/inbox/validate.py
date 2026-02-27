"""Validation helpers for inbox files prior to ingestion."""

from __future__ import annotations

from pathlib import Path

from ai_deney.adapters.electra_adapter import ElectraAdapterError, validate_electra_export
from ai_deney.adapters.hotelrunner_adapter import HotelRunnerAdapterError, validate_hotelrunner_export
from ai_deney.inbox.scan import SelectedInboxFile

DEFAULT_MAX_FILE_SIZE_BYTES = 25 * 1024 * 1024

class InboxValidationError(ValueError):
    """Raised when inbox file content is invalid."""

def _assert_csv_suffix(path: Path) -> None:
    if path.suffix.lower() not in {".csv", ".xlsx", ".xlsm"}:
        raise InboxValidationError(
            f"unsupported inbox file type for {path.name}: expected .csv (or .xlsx/.xlsm when adapter support is available)"
        )


def _assert_file_size(path: Path, max_file_size_bytes: int) -> None:
    size = int(path.stat().st_size)
    if size > int(max_file_size_bytes):
        raise InboxValidationError(
            f"inbox file too large: {path.name} is {size} bytes; limit is {int(max_file_size_bytes)} bytes"
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

    if selected.source == "electra":
        try:
            validate_electra_export(path=path, report_type=selected.report_type)
        except ElectraAdapterError as exc:
            raise InboxValidationError(str(exc)) from exc
        return
    if selected.source == "hotelrunner":
        if selected.report_type != "daily_sales":
            raise InboxValidationError(f"unsupported hotelrunner report_type: {selected.report_type}")
        try:
            validate_hotelrunner_export(path=path)
        except HotelRunnerAdapterError as exc:
            raise InboxValidationError(str(exc)) from exc
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
