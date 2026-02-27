from pathlib import Path
import shutil

from ai_deney.connectors.hotelrunner_mock import HotelRunnerMockConnector


def _repo_tmp(name: str) -> Path:
    repo_root = Path(__file__).resolve().parents[1]
    p = repo_root / "tests" / "_tmp_tasks" / "hotelrunner_connector" / name
    shutil.rmtree(p, ignore_errors=True)
    p.mkdir(parents=True, exist_ok=True)
    return p


def test_mock_connector_fetches_daily_sales_reports() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    raw_root = _repo_tmp("basic") / "raw"
    conn = HotelRunnerMockConnector(repo_root=repo_root, raw_root=raw_root)

    daily = conn.fetch_report("daily_sales", {"years": [2026, 2025]})

    assert [p.name for p in daily] == ["daily_sales_2025.csv", "daily_sales_2026.csv"]
    assert all(p.exists() for p in daily)
    assert all(str(raw_root.resolve()) in str(p.resolve()) for p in daily)
