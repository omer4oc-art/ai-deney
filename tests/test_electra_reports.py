import csv
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from ai_deney.analytics.electra_queries import get_sales_years
from ai_deney.reports.electra_reports import answer_question


def _repo_tmp_dir(name: str) -> Path:
    repo_root = Path(__file__).resolve().parents[1]
    p = repo_root / "tests" / "_tmp_tasks" / "electra_reports" / name
    shutil.rmtree(p, ignore_errors=True)
    p.mkdir(parents=True, exist_ok=True)
    return p


def test_answer_question_sales_summary_markdown_contains_expected_totals() -> None:
    tmp_root = _repo_tmp_dir("summary")
    normalized_root = tmp_root / "normalized"
    text = answer_question(
        "get me the sales data of 2026 and 2025",
        normalized_root=normalized_root,
    )
    assert "# Sales Summary (2025, 2026)" in text
    assert "| year | gross_sales | net_sales | currency |" in text
    assert "| 2025 |" in text
    assert "| 2026 |" in text
    assert "Data freshness / source: Source: Electra mock fixtures; Generated: deterministic run." in text
    for year in (2025, 2026):
        path = normalized_root / f"electra_sales_{year}.csv"
        with path.open("r", encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
        assert rows
        assert all(r["agency_id"] == "TOTAL" for r in rows)


def test_answer_question_sales_by_agency_compare_includes_table_and_note() -> None:
    tmp_root = _repo_tmp_dir("agency_compare")
    normalized_root = tmp_root / "normalized"
    text = answer_question(
        "compare 2025 vs 2026 by agency",
        normalized_root=normalized_root,
    )
    assert "# Sales By Agency (2025, 2026)" in text
    assert "| year | agency_id | agency_name | gross_sales | net_sales | currency |" in text
    assert "Comparison 2025 -> 2026" in text
    assert "Atlas Partners" in text


def test_answer_question_sales_by_agency_only_passes_with_agency_rows_only() -> None:
    tmp_root = _repo_tmp_dir("agency_only")
    normalized_root = tmp_root / "normalized"
    text = answer_question(
        "get me the sales categorized by agencies for 2025",
        normalized_root=normalized_root,
    )
    assert "# Sales By Agency (2025)" in text
    path = normalized_root / "electra_sales_2025.csv"
    with path.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert rows
    assert all(r["agency_id"] != "TOTAL" for r in rows)


def test_answer_question_supports_new_month_top_and_share_patterns() -> None:
    tmp_root = _repo_tmp_dir("new_patterns")
    normalized_root = tmp_root / "normalized"

    by_month = answer_question("sales by month for 2025", normalized_root=normalized_root)
    assert "# Sales By Month (2025)" in by_month
    assert "| year | month | gross_sales | net_sales | currency |" in by_month

    top = answer_question("top agencies in 2026", normalized_root=normalized_root)
    assert "# Top Agencies (2026)" in top
    assert "| year | rank | agency_id | agency_name | gross_sales | net_sales | currency |" in top

    share = answer_question("share of direct vs agencies in 2025", normalized_root=normalized_root)
    assert "# Direct vs Agency Share (2025)" in share
    assert "| year | direct_gross_sales | agency_gross_sales | direct_share_pct | agency_share_pct | currency |" in share


def test_answer_question_can_render_html() -> None:
    tmp_root = _repo_tmp_dir("html")
    normalized_root = tmp_root / "normalized"
    html = answer_question(
        "get me the sales categorized by agencies for 2025",
        normalized_root=normalized_root,
        output_format="html",
    )
    assert "<!doctype html>" in html.lower()
    assert "<table>" in html
    assert "Data freshness / source: Source: Electra mock fixtures; Generated: deterministic run." in html


def test_cross_check_runs_and_catches_mismatch_when_both_sides_exist() -> None:
    tmp_root = _repo_tmp_dir("mismatch")
    normalized_root = tmp_root / "normalized"
    answer_question("get me the sales data of 2025", normalized_root=normalized_root)
    answer_question("get me the sales categorized by agencies for 2025", normalized_root=normalized_root)

    path = normalized_root / "electra_sales_2025.csv"
    with path.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        if row["agency_id"] == "AG001":
            row["gross_sales"] = "401.00"
            break
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    with pytest.raises(ValueError, match="agency totals mismatch"):
        get_sales_years([2025], normalized_root=normalized_root)


def test_ask_electra_cli_writes_report() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    tmp_root = _repo_tmp_dir("cli")
    out_path = tmp_root / "report.md"
    p = subprocess.run(
        [
            sys.executable,
            "scripts/ask_electra.py",
            "get me the sales categorized by agencies for 2025",
            "--out",
            str(out_path),
        ],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    assert p.returncode == 0, f"stdout={p.stdout}\nstderr={p.stderr}"
    assert out_path.exists()
    content = out_path.read_text(encoding="utf-8")
    assert "# Sales By Agency (2025)" in content
    assert "Agency" in content
    assert "WROTE:" in p.stdout


def test_ask_electra_cli_writes_html_report() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    tmp_root = _repo_tmp_dir("cli_html")
    out_path = tmp_root / "report.html"
    p = subprocess.run(
        [
            sys.executable,
            "scripts/ask_electra.py",
            "sales by month for 2025",
            "--format",
            "html",
            "--out",
            str(out_path),
        ],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    assert p.returncode == 0, f"stdout={p.stdout}\nstderr={p.stderr}"
    assert out_path.exists()
    content = out_path.read_text(encoding="utf-8")
    assert "<!doctype html>" in content.lower()
    assert "<table>" in content
    assert "WROTE:" in p.stdout


def test_answer_question_supports_reconciliation_report() -> None:
    tmp_root = _repo_tmp_dir("reconcile")
    normalized_root = tmp_root / "normalized"
    text = answer_question(
        "compare electra vs hotelrunner for 2025",
        normalized_root=normalized_root,
    )
    assert "# Electra vs HotelRunner Daily Reconciliation (2025)" in text
    assert "## Summary" in text
    assert "- mismatched_days: 3" in text
    assert "- top_reason_codes: TIMING=2, UNKNOWN=1" in text
    assert "- total_mismatch_amount: 107.00" in text
    assert "- year_rollups: 2025: MATCH=27, MISMATCH=3, ABS_MISMATCH=107.00" in text
    assert "## How to read this" in text
    assert "- ROUNDING: minor rounding differences (<= $1)" in text
    assert "## Top mismatch days" in text
    assert "| date | delta | reason_code |" in text
    assert "| date | year | electra_gross | hr_gross | delta | status | reason_code |" in text
    assert "TIMING" in text
    assert "ROUNDING" in text


def test_answer_question_supports_reconciliation_report_html_summary() -> None:
    tmp_root = _repo_tmp_dir("reconcile_html")
    normalized_root = tmp_root / "normalized"
    text = answer_question(
        "compare electra vs hotelrunner for 2026",
        normalized_root=normalized_root,
        output_format="html",
    )
    assert "<!doctype html>" in text.lower()
    assert "<h2>Summary</h2>" in text
    assert "mismatched_days: 3" in text
    assert "top_reason_codes: TIMING=2, UNKNOWN=1" in text
    assert "total_mismatch_amount: 106.00" in text
    assert "year_rollups: 2026: MATCH=27, MISMATCH=3, ABS_MISMATCH=106.00" in text
    assert "<h2>How to read this</h2>" in text
    assert "<h2>Top mismatch days</h2>" in text


def test_answer_question_supports_monthly_reconciliation_report() -> None:
    tmp_root = _repo_tmp_dir("reconcile_monthly")
    normalized_root = tmp_root / "normalized"
    text = answer_question(
        "electra vs hotelrunner monthly reconciliation for 2025",
        normalized_root=normalized_root,
    )
    assert "# Electra vs HotelRunner Monthly Reconciliation (2025)" in text
    assert "| year | month | electra_gross | hr_gross | delta | status |" in text
    assert "Data freshness / source: Source: Electra + HotelRunner mock fixtures; Generated: deterministic run." in text


def test_answer_question_supports_daily_reconciliation_by_agency_report() -> None:
    tmp_root = _repo_tmp_dir("reconcile_daily_by_agency")
    normalized_root = tmp_root / "normalized"
    text = answer_question(
        "where do electra and hotelrunner differ by agency in 2025",
        normalized_root=normalized_root,
    )
    assert "# Electra vs HotelRunner Daily Reconciliation by Agency (2025)" in text
    assert "## Top mismatch contributors" in text
    assert "## Top anomalies" in text
    assert "| date | year | dim_value | electra_gross | hr_gross | delta | status | reason_code |" in text


def test_answer_question_supports_monthly_reconciliation_by_agency_report_html() -> None:
    tmp_root = _repo_tmp_dir("reconcile_monthly_by_agency")
    normalized_root = tmp_root / "normalized"
    html = answer_question(
        "monthly reconciliation by agency 2026 electra hotelrunner",
        normalized_root=normalized_root,
        output_format="html",
    )
    assert "<!doctype html>" in html.lower()
    assert "<h2>Top mismatch contributors</h2>" in html
    assert "<h2>Top anomalies</h2>" in html
    assert "Electra vs HotelRunner Monthly Reconciliation by Agency (2026)" in html


def test_answer_question_supports_anomalies_by_agency_report() -> None:
    tmp_root = _repo_tmp_dir("reconcile_anomalies_by_agency")
    normalized_root = tmp_root / "normalized"
    text = answer_question(
        "any anomalies by agency in 2026",
        normalized_root=normalized_root,
    )
    assert "# Electra vs HotelRunner Agency Anomalies (2026)" in text
    assert "## Top mismatch contributors" in text
    assert "## Top anomalies" in text
    assert "NEW_DIM_VALUE" in text
