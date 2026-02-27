import shutil
import subprocess
import sys
from pathlib import Path


def test_generate_truth_pack_script_creates_index_and_bundle() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    outdir = repo_root / "tests" / "_tmp_tasks" / "truth_pack" / "out"
    shutil.rmtree(outdir.parent, ignore_errors=True)
    outdir.parent.mkdir(parents=True, exist_ok=True)
    p = subprocess.run(
        [sys.executable, "scripts/generate_truth_pack.py", "--outdir", str(outdir)],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    assert p.returncode == 0, f"stdout={p.stdout}\nstderr={p.stderr}"
    index_path = outdir / "index.md"
    bundle_path = outdir / "bundle.txt"
    assert index_path.exists()
    assert bundle_path.exists()

    index_text = index_path.read_text(encoding="utf-8")
    assert "# Hotel Truth Pack v1" in index_text
    assert "Q1" in index_text
    assert ".md" in index_text
    assert ".html" in index_text
    assert "compare electra vs hotelrunner for 2025" in index_text
    assert "electra vs hotelrunner monthly reconciliation for 2025" in index_text
    assert "electra vs hotelrunner monthly reconciliation for 2026" in index_text
    assert "where do electra and hotelrunner differ by agency in 2025" in index_text
    assert "monthly reconciliation by agency 2026 electra hotelrunner" in index_text
    assert "any anomalies by agency in 2026" in index_text
    assert "mapping health report 2025" in index_text
    assert "which agencies are unmapped in 2026" in index_text
    assert "agency drift electra vs hotelrunner 2025" in index_text
    assert "mapping explain agency 2025" in index_text
    assert "mapping explain agency 2026" in index_text
    assert "mapping unknown rate improvement 2025" in index_text
    assert "mapping unknown rate improvement 2026" in index_text

    bundle_text = bundle_path.read_text(encoding="utf-8")
    assert "===== FILE: index.md =====" in bundle_text
    assert "Data freshness / source: Source: Electra mock fixtures; Generated: deterministic run." in bundle_text
    assert "Data freshness / source: Source: Electra + HotelRunner mock fixtures; Generated: deterministic run." in bundle_text
    assert (
        "Data freshness / source: Source: Electra + HotelRunner mock fixtures + mapping config; Generated: deterministic run."
        in bundle_text
    )
