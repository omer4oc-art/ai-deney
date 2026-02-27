"""Scan and select inbox drop-folder files with strict naming rules."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
import re

ELECTRA_REPORT_TYPES = ("sales_summary", "sales_by_agency")
HOTELRUNNER_REPORT_TYPES = ("daily_sales",)
REQUIRED_REPORT_KEYS = (
    ("electra", "sales_summary"),
    ("electra", "sales_by_agency"),
    ("hotelrunner", "daily_sales"),
)

_ELECTRA_RE = re.compile(r"^electra_(sales_summary|sales_by_agency)_(\d{4}-\d{2}-\d{2})\.(csv|xlsx|xlsm)$")
_HOTELRUNNER_RE = re.compile(r"^hotelrunner_daily_sales_(\d{4}-\d{2}-\d{2})\.(csv|xlsx|xlsm)$")


class InboxScanError(ValueError):
    """Base class for inbox scanning/selection errors."""


class InboxNoFilesError(InboxScanError):
    """Raised when inbox does not contain candidate files."""


class InboxMissingReportsError(InboxScanError):
    """Raised when required report files are missing for requested years."""


@dataclass(frozen=True)
class InboxCandidate:
    source: str
    report_type: str
    report_date: date
    path: Path
    mtime_ns: int
    size_bytes: int

    @property
    def year(self) -> int:
        return int(self.report_date.year)


@dataclass(frozen=True)
class SelectedInboxFile:
    source: str
    report_type: str
    report_date: date
    year: int
    path: Path
    mtime_ns: int
    size_bytes: int


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _assert_within_repo(path: Path, repo_root: Path) -> None:
    try:
        path.resolve().relative_to(repo_root.resolve())
    except Exception as exc:
        raise InboxScanError(f"path escapes repo root: {path}") from exc


def _parse_date(raw: str, filename: str) -> date:
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError as exc:
        raise InboxScanError(f"invalid date in filename '{filename}': expected YYYY-MM-DD") from exc


def _parse_candidate_filename(source: str, filename: str) -> tuple[str, date]:
    if source == "electra":
        m = _ELECTRA_RE.match(filename)
        if not m:
            raise InboxScanError(
                "invalid inbox filename for electra: "
                f"{filename}; expected electra_<report>_<YYYY-MM-DD>.<csv|xlsx|xlsm> "
                f"where report in {list(ELECTRA_REPORT_TYPES)}"
            )
        report_type = m.group(1)
        report_date = _parse_date(m.group(2), filename)
        return report_type, report_date

    if source == "hotelrunner":
        m = _HOTELRUNNER_RE.match(filename)
        if not m:
            raise InboxScanError(
                "invalid inbox filename for hotelrunner: "
                f"{filename}; expected hotelrunner_daily_sales_<YYYY-MM-DD>.<csv|xlsx|xlsm>"
            )
        report_date = _parse_date(m.group(1), filename)
        return "daily_sales", report_date

    raise InboxScanError(f"unsupported inbox source: {source}")


def _scan_source(source: str, source_root: Path, repo_root: Path) -> list[InboxCandidate]:
    if not source_root.exists():
        return []
    if not source_root.is_dir():
        raise InboxScanError(f"inbox source path is not a directory: {source_root}")

    candidates: list[InboxCandidate] = []
    for path in sorted(source_root.iterdir(), key=lambda p: p.name):
        _assert_within_repo(path, repo_root)
        if path.is_dir():
            raise InboxScanError(f"unexpected directory inside inbox source ({source}): {path.name}")

        report_type, report_date = _parse_candidate_filename(source=source, filename=path.name)
        stat = path.stat()
        candidates.append(
            InboxCandidate(
                source=source,
                report_type=report_type,
                report_date=report_date,
                path=path.resolve(),
                mtime_ns=int(stat.st_mtime_ns),
                size_bytes=int(stat.st_size),
            )
        )

    return candidates


def scan_inbox_candidates(repo_root: Path | None = None, inbox_root: Path | None = None) -> list[InboxCandidate]:
    """Scan inbox roots and return strict filename-parsed candidates."""
    repo = (repo_root or _repo_root()).resolve()
    root = (inbox_root or (repo / "data" / "inbox")).resolve()
    _assert_within_repo(root, repo)

    candidates: list[InboxCandidate] = []
    candidates.extend(_scan_source("electra", root / "electra", repo))
    candidates.extend(_scan_source("hotelrunner", root / "hotelrunner", repo))
    candidates.sort(key=lambda c: (c.source, c.report_type, c.report_date.isoformat(), c.path.name))
    return candidates


def _normalize_years(years: list[int]) -> list[int]:
    if not years:
        raise InboxScanError("at least one year is required")
    return sorted({int(y) for y in years})


def select_newest_for_years(
    candidates: list[InboxCandidate],
    years: list[int],
    require_complete: bool = True,
) -> list[SelectedInboxFile]:
    """Select newest candidate per (source, report_type, year)."""
    years_i = _normalize_years(years)
    if not candidates:
        raise InboxNoFilesError("no inbox files found")

    grouped: dict[tuple[str, str, int], list[InboxCandidate]] = {}
    for candidate in candidates:
        if candidate.year not in years_i:
            continue
        key = (candidate.source, candidate.report_type, candidate.year)
        grouped.setdefault(key, []).append(candidate)

    selected: list[SelectedInboxFile] = []
    for key, items in grouped.items():
        newest = sorted(
            items,
            key=lambda c: (c.report_date.isoformat(), c.mtime_ns, c.path.name),
            reverse=True,
        )[0]
        selected.append(
            SelectedInboxFile(
                source=newest.source,
                report_type=newest.report_type,
                report_date=newest.report_date,
                year=newest.year,
                path=newest.path,
                mtime_ns=newest.mtime_ns,
                size_bytes=newest.size_bytes,
            )
        )

    selected.sort(key=lambda s: (s.year, s.source, s.report_type, s.path.name))

    if require_complete:
        selected_keys = {(s.source, s.report_type, s.year) for s in selected}
        missing: list[str] = []
        for year in years_i:
            for source, report_type in REQUIRED_REPORT_KEYS:
                if (source, report_type, year) not in selected_keys:
                    missing.append(f"{source}:{report_type}:{year}")
        if missing:
            available_years = sorted({c.year for c in candidates})
            raise InboxMissingReportsError(
                "missing required inbox report files for requested years: "
                + ", ".join(missing)
                + f"; available years in inbox: {available_years or 'none'}"
            )

    return selected


def scan_and_select_newest(
    years: list[int],
    repo_root: Path | None = None,
    inbox_root: Path | None = None,
    require_complete: bool = True,
) -> list[SelectedInboxFile]:
    """Convenience helper that scans inbox and selects newest files."""
    candidates = scan_inbox_candidates(repo_root=repo_root, inbox_root=inbox_root)
    return select_newest_for_years(candidates=candidates, years=years, require_complete=require_complete)
