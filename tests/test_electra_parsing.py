import csv
from pathlib import Path

from ai_deney.parsing.electra_sales import (
    TOTAL_AGENCY_ID,
    normalize_report_files,
    parse_sales_by_agency_csv,
    parse_sales_summary_csv,
    parse_sales_summary_pdf,
)
from scripts.make_fixture_pdf import TABLE_LINES, build_pdf_bytes


def test_csv_parsing_and_normalization_for_both_report_types(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    fixture_root = repo_root / "fixtures" / "electra"
    normalized_root = tmp_path / "normalized"

    summary_paths = [fixture_root / "sales_summary_2025.csv", fixture_root / "sales_summary_2026.csv"]
    agency_paths = [fixture_root / "sales_by_agency_2025.csv", fixture_root / "sales_by_agency_2026.csv"]
    normalize_report_files(summary_paths, "sales_summary", normalized_root)
    out_paths = normalize_report_files(agency_paths, "sales_by_agency", normalized_root)

    assert sorted(p.name for p in out_paths) == ["electra_sales_2025.csv", "electra_sales_2026.csv"]
    for year in (2025, 2026):
        path = normalized_root / f"electra_sales_{year}.csv"
        assert path.exists()
        with path.open("r", encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
        assert rows
        assert any(r["agency_id"] == TOTAL_AGENCY_ID for r in rows)

    parsed_summary = parse_sales_summary_csv(summary_paths[0])
    parsed_agency = parse_sales_by_agency_csv(agency_paths[0])
    assert parsed_summary[0]["agency_id"] == TOTAL_AGENCY_ID
    assert len(parsed_agency) == 3


def test_pdf_parsing_works_for_generated_sample(tmp_path: Path) -> None:
    generated_pdf = tmp_path / "generated_sample.pdf"
    generated_pdf.write_bytes(build_pdf_bytes(TABLE_LINES))
    rows = parse_sales_summary_pdf(generated_pdf)
    assert len(rows) == 2
    assert [r["year"] for r in rows] == [2025, 2026]
    assert rows[0]["gross_sales"] == 1000.0
    assert rows[1]["net_sales"] == 1170.0

