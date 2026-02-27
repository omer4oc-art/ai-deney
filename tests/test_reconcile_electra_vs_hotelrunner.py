from pathlib import Path
import shutil

import pytest

from ai_deney.connectors.electra_mock import ElectraMockConnector
from ai_deney.connectors.hotelrunner_mock import HotelRunnerMockConnector
from ai_deney.parsing.electra_sales import normalize_report_files as normalize_electra_report_files
from ai_deney.parsing.hotelrunner_sales import normalize_report_files as normalize_hotelrunner_report_files
from ai_deney.reconcile.electra_vs_hotelrunner import reconcile_daily


def _normalize_sources(tmp_path: Path, years: list[int]) -> Path:
    repo_root = Path(__file__).resolve().parents[1]
    normalized_root = tmp_path / "normalized"
    raw_root = repo_root / "tests" / "_tmp_tasks" / "reconcile" / "raw"
    shutil.rmtree(raw_root.parent, ignore_errors=True)
    raw_root.mkdir(parents=True, exist_ok=True)

    electra_conn = ElectraMockConnector(repo_root=repo_root, raw_root=raw_root / "electra")
    electra_paths = electra_conn.fetch_report("sales_summary", {"years": years})
    normalize_electra_report_files(electra_paths, "sales_summary", normalized_root)

    hotelrunner_conn = HotelRunnerMockConnector(repo_root=repo_root, raw_root=raw_root / "hotelrunner")
    hotelrunner_paths = hotelrunner_conn.fetch_report("daily_sales", {"years": years})
    normalize_hotelrunner_report_files(hotelrunner_paths, normalized_root)

    return normalized_root


def test_reconcile_daily_flags_rounding_timing_and_unknown(tmp_path: Path) -> None:
    normalized_root = _normalize_sources(tmp_path, [2025, 2026])
    df = reconcile_daily([2025, 2026], normalized_root, normalized_root)
    rows = df.to_dict("records")
    assert len(rows) >= 60

    by_key = {(int(r["year"]), str(r["date"])): r for r in rows}

    rounding_2025 = by_key[(2025, "2025-02-19")]
    assert rounding_2025["status"] == "MATCH"
    assert rounding_2025["reason_code"] == "ROUNDING"
    assert float(rounding_2025["delta"]) == pytest.approx(-0.75, abs=1e-6)

    timing_a = by_key[(2025, "2025-03-13")]
    timing_b = by_key[(2025, "2025-03-19")]
    assert timing_a["status"] == "MISMATCH"
    assert timing_b["status"] == "MISMATCH"
    assert timing_a["reason_code"] == "TIMING"
    assert timing_b["reason_code"] == "TIMING"
    assert float(timing_a["delta"]) == pytest.approx(50.0, abs=1e-6)
    assert float(timing_b["delta"]) == pytest.approx(-50.0, abs=1e-6)

    unknown_2025 = by_key[(2025, "2025-05-25")]
    assert unknown_2025["status"] == "MISMATCH"
    assert unknown_2025["reason_code"] == "UNKNOWN"
    assert float(unknown_2025["delta"]) == pytest.approx(-7.0, abs=1e-6)

    unknown_2026 = by_key[(2026, "2026-06-19")]
    assert unknown_2026["status"] == "MISMATCH"
    assert unknown_2026["reason_code"] == "UNKNOWN"
    assert float(unknown_2026["delta"]) == pytest.approx(6.0, abs=1e-6)


def test_reconcile_daily_requires_year_files(tmp_path: Path) -> None:
    normalized_root = tmp_path / "normalized"
    normalized_root.mkdir(parents=True, exist_ok=True)
    with pytest.raises(ValueError, match="normalized data missing for years"):
        reconcile_daily([2025], normalized_root, normalized_root)
