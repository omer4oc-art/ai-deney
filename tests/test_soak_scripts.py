import os
import json
import subprocess
from pathlib import Path


def _safe_env() -> dict[str, str]:
    env = dict(os.environ)
    env["AI_DENEY_PYTEST_ARGS"] = "-k test_ast_quality_gate_text_rejects_top_level_print_and_pass_only"
    return env


def test_run_eval_pack_sh_executes(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    p = subprocess.run(
        ["bash", "scripts/run_eval_pack.sh"],
        cwd=str(repo_root),
        env=_safe_env(),
        capture_output=True,
        text=True,
    )
    assert p.returncode == 0, f"stdout={p.stdout}\nstderr={p.stderr}"
    assert "eval_pack_status=PASS" in p.stdout


def test_soak_eval_pack_two_iterations(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    outbase = tmp_path / "soak_out"
    p = subprocess.run(
        [
            "bash",
            "scripts/soak_eval_pack.sh",
            "--iterations",
            "2",
            "--sleep-seconds",
            "0",
            "--no-stop-on-fail",
            "--max-runs-kept",
            "2",
            "--outbase",
            str(outbase),
        ],
        cwd=str(repo_root),
        env=_safe_env(),
        capture_output=True,
        text=True,
    )
    assert p.returncode == 0, f"stdout={p.stdout}\nstderr={p.stderr}"

    soak_dirs = sorted([d for d in outbase.iterdir() if d.is_dir()])
    assert soak_dirs, "expected soak output directories"
    latest = soak_dirs[-1]
    summary = latest / "soak_summary.jsonl"
    assert summary.exists()
    lines = [ln for ln in summary.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 2
    records = [json.loads(ln) for ln in lines]
    for rec in records:
        assert "run_dir" in rec
        assert "log_path" in rec
        run_dir = latest / rec["run_dir"]
        log_path = latest / rec["log_path"]
        assert run_dir.exists(), f"missing run_dir: {run_dir}"
        assert log_path.exists(), f"missing log_path: {log_path}"
        assert log_path.read_text(encoding="utf-8").strip(), f"empty log: {log_path}"

    assert (latest / "runs" / "iter-0001" / "pytest.log").exists()
    assert (latest / "runs" / "iter-0002" / "pytest.log").exists()

    p2 = subprocess.run(
        ["bash", "scripts/print_soak_summary.sh", str(latest)],
        cwd=str(repo_root),
        env=_safe_env(),
        capture_output=True,
        text=True,
    )
    assert p2.returncode == 0, f"stdout={p2.stdout}\nstderr={p2.stderr}"
    assert "total_iterations=2" in p2.stdout
