import subprocess
from pathlib import Path


def test_report_soak_script_outputs_expected_summary(tmp_path: Path) -> None:
    soak = tmp_path / "soak-1"
    runs = soak / "runs"
    (runs / "iter-0001").mkdir(parents=True, exist_ok=True)
    (runs / "iter-0002").mkdir(parents=True, exist_ok=True)
    (runs / "iter-0003").mkdir(parents=True, exist_ok=True)

    (soak / "soak_summary.jsonl").write_text(
        '{"iteration":1,"status":"PASS","duration_seconds":2,"log_path":"runs/iter-0001/pytest.log"}\n'
        '{"iteration":2,"status":"FAIL","duration_seconds":8,"log_path":"runs/iter-0002/pytest.log"}\n'
        '{"iteration":3,"status":"PASS","duration_seconds":4,"log_path":"runs/iter-0003/pytest.log"}\n',
        encoding="utf-8",
    )
    (runs / "iter-0001" / "gate_report.json").write_text(
        '{"gate_counts":{"PY_COMPILE_FAILED":2,"AST_TODO_FOUND":1}}',
        encoding="utf-8",
    )
    (runs / "iter-0002" / "gate_report.json").write_text(
        '{"gate_counts":{"PY_COMPILE_FAILED":1,"EXPECT_MISSING":3}}',
        encoding="utf-8",
    )

    repo_root = Path(__file__).resolve().parents[1]
    p = subprocess.run(
        ["python3", "scripts/report_soak.py", str(soak), "--top", "5"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    assert p.returncode == 0, f"stdout={p.stdout}\nstderr={p.stderr}"
    out = p.stdout
    assert "total_iterations=3" in out
    assert "failures=1" in out
    assert "failure_iterations=2" in out
    assert "slowest_iteration=2" in out
    assert "GATE PY_COMPILE_FAILED 3" in out
    assert "GATE EXPECT_MISSING 3" in out
    assert "GATE AST_TODO_FOUND 1" in out
