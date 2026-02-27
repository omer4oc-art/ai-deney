import hashlib
import json
import shutil
from pathlib import Path

import pytest

from ai_deney.inbox.ingest import ingest_inbox_for_years
from ai_deney.inbox.scan import InboxMissingReportsError, InboxScanError, scan_inbox_candidates, select_newest_for_years
from ai_deney.inbox.validate import InboxValidationError


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _case_root(name: str) -> Path:
    root = _repo_root() / "tests" / "_tmp_tasks" / "inbox" / name
    shutil.rmtree(root, ignore_errors=True)
    (root / "data" / "inbox" / "electra").mkdir(parents=True, exist_ok=True)
    (root / "data" / "inbox" / "hotelrunner").mkdir(parents=True, exist_ok=True)
    return root


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _electra_summary_csv(date_value: str = "2025-01-01") -> str:
    return (
        "date,gross_sales,net_sales,currency\n"
        f"{date_value},100.00,90.00,USD\n"
    )


def _electra_agency_csv(date_value: str = "2025-01-01") -> str:
    return (
        "date,agency_id,agency_name,gross_sales,net_sales,currency\n"
        f"{date_value},AG001,Atlas Partners,100.00,90.00,USD\n"
    )


def _hotelrunner_csv(date_value: str = "2025-01-01") -> str:
    return (
        "date,booking_id,channel,gross_sales,net_sales,currency\n"
        f"{date_value},HR1,Booking.com,100.00,90.00,USD\n"
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_inbox_selects_newest_valid_files() -> None:
    root = _case_root("select_newest")
    inbox_root = root / "data" / "inbox"

    _write(
        inbox_root / "electra" / "electra_sales_summary_2025-01-15.csv",
        _electra_summary_csv("2025-01-15"),
    )
    _write(
        inbox_root / "electra" / "electra_sales_summary_2025-02-01.csv",
        _electra_summary_csv("2025-02-01"),
    )
    _write(
        inbox_root / "electra" / "electra_sales_by_agency_2025-01-31.csv",
        _electra_agency_csv("2025-01-31"),
    )
    _write(
        inbox_root / "hotelrunner" / "hotelrunner_daily_sales_2025-01-31.csv",
        _hotelrunner_csv("2025-01-31"),
    )

    candidates = scan_inbox_candidates(repo_root=_repo_root(), inbox_root=inbox_root)
    selected = select_newest_for_years(candidates, years=[2025], require_complete=True)

    by_key = {(s.source, s.report_type, s.year): s.path.name for s in selected}
    assert by_key[("electra", "sales_summary", 2025)] == "electra_sales_summary_2025-02-01.csv"
    assert by_key[("electra", "sales_by_agency", 2025)] == "electra_sales_by_agency_2025-01-31.csv"
    assert by_key[("hotelrunner", "daily_sales", 2025)] == "hotelrunner_daily_sales_2025-01-31.csv"


def test_inbox_scan_rejects_invalid_filename() -> None:
    root = _case_root("invalid_name")
    inbox_root = root / "data" / "inbox"
    _write(inbox_root / "electra" / "wrong_name_2025-01-01.csv", _electra_summary_csv())

    with pytest.raises(InboxScanError, match="invalid inbox filename"):
        scan_inbox_candidates(repo_root=_repo_root(), inbox_root=inbox_root)


def test_inbox_selection_requires_all_reports_per_year() -> None:
    root = _case_root("missing_required")
    inbox_root = root / "data" / "inbox"

    _write(
        inbox_root / "electra" / "electra_sales_summary_2025-01-31.csv",
        _electra_summary_csv("2025-01-31"),
    )
    _write(
        inbox_root / "hotelrunner" / "hotelrunner_daily_sales_2025-01-31.csv",
        _hotelrunner_csv("2025-01-31"),
    )

    candidates = scan_inbox_candidates(repo_root=_repo_root(), inbox_root=inbox_root)
    with pytest.raises(InboxMissingReportsError, match="electra:sales_by_agency:2025"):
        select_newest_for_years(candidates, years=[2025], require_complete=True)


def test_inbox_ingest_rejects_header_mismatch() -> None:
    root = _case_root("header_mismatch")
    inbox_root = root / "data" / "inbox"
    raw_root = root / "data" / "raw" / "inbox_run"

    _write(
        inbox_root / "electra" / "electra_sales_summary_2025-01-31.csv",
        _electra_summary_csv("2025-01-31"),
    )
    _write(
        inbox_root / "electra" / "electra_sales_by_agency_2025-01-31.csv",
        "date,agency_id,gross_sales,net_sales,currency\n2025-01-31,AG001,100.00,90.00,USD\n",
    )
    _write(
        inbox_root / "hotelrunner" / "hotelrunner_daily_sales_2025-01-31.csv",
        _hotelrunner_csv("2025-01-31"),
    )

    with pytest.raises(InboxValidationError, match="header mismatch"):
        ingest_inbox_for_years(
            years=[2025],
            repo_root=_repo_root(),
            inbox_root=inbox_root,
            raw_runs_root=raw_root,
        )


def test_inbox_ingest_writes_manifest_with_hashes() -> None:
    root = _case_root("manifest_hashes")
    repo_root = _repo_root()
    inbox_root = root / "data" / "inbox"
    raw_root = root / "data" / "raw" / "inbox_run"

    electra_summary = inbox_root / "electra" / "electra_sales_summary_2025-01-31.csv"
    electra_agency = inbox_root / "electra" / "electra_sales_by_agency_2025-01-31.csv"
    hotelrunner = inbox_root / "hotelrunner" / "hotelrunner_daily_sales_2025-01-31.csv"

    _write(electra_summary, _electra_summary_csv("2025-01-31"))
    _write(electra_agency, _electra_agency_csv("2025-01-31"))
    _write(hotelrunner, _hotelrunner_csv("2025-01-31"))

    result = ingest_inbox_for_years(
        years=[2025],
        repo_root=repo_root,
        inbox_root=inbox_root,
        raw_runs_root=raw_root,
    )

    assert result.manifest_path.exists()
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))

    assert manifest["run_id"] == result.run_id
    assert len(manifest["selected_files"]) == 3
    sha_by_report = {row["report_type"]: row["sha256"] for row in manifest["selected_files"]}
    assert sha_by_report["sales_summary"] == _sha256(electra_summary)
    assert sha_by_report["sales_by_agency"] == _sha256(electra_agency)
    assert sha_by_report["daily_sales"] == _sha256(hotelrunner)

    out_files = {Path(p).name for p in manifest["normalization_outputs"]}
    assert "electra_sales_2025.csv" in out_files
    assert "hotelrunner_sales_2025.csv" in out_files

    for rel in manifest["normalization_outputs"]:
        assert (repo_root / rel).exists()
