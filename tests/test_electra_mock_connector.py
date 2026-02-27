from pathlib import Path
import shutil

from ai_deney.connectors.electra_mock import ElectraMockConnector


def _repo_tmp(name: str) -> Path:
    repo_root = Path(__file__).resolve().parents[1]
    p = repo_root / "tests" / "_tmp_tasks" / "electra_connector" / name
    shutil.rmtree(p, ignore_errors=True)
    p.mkdir(parents=True, exist_ok=True)
    return p


def test_mock_connector_fetches_sales_summary_and_agency_reports() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    raw_root = _repo_tmp("basic") / "raw"
    conn = ElectraMockConnector(repo_root=repo_root, raw_root=raw_root)

    summary = conn.fetch_report("sales_summary", {"years": [2026, 2025]})
    by_agency = conn.fetch_report("sales_by_agency", {"years": [2025, 2026]})

    assert [p.name for p in summary] == ["sales_summary_2025.csv", "sales_summary_2026.csv"]
    assert [p.name for p in by_agency] == ["sales_by_agency_2025.csv", "sales_by_agency_2026.csv"]
    assert all(p.exists() for p in summary + by_agency)
    assert all(str(raw_root.resolve()) in str(p.resolve()) for p in summary + by_agency)


def test_mock_connector_can_include_pdf_sample() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    raw_root = _repo_tmp("with_pdf") / "raw"
    conn = ElectraMockConnector(repo_root=repo_root, raw_root=raw_root)
    paths = conn.fetch_report("sales_summary", {"years": [2025], "include_pdf_sample": True})
    names = [p.name for p in paths]
    assert "sales_summary_2025.csv" in names
    assert "sales_summary_sample.pdf" in names
