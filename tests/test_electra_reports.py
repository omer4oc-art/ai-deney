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
    assert "| 2025 | 1000.00 | 900.00 | USD |" in text
    assert "| 2026 | 1300.00 | 1170.00 | USD |" in text
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
