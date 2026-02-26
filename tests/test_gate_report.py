import json
import os
import shutil
import subprocess
from pathlib import Path


def _safe_env() -> dict[str, str]:
    env = dict(os.environ)
    env["AI_DENEY_PYTEST_ARGS"] = "-k test_ast_quality_gate_text_rejects_top_level_print_and_pass_only"
    return env


def test_gate_report_written_and_contains_attempts(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    src = repo_root / "tests" / "eval_pack" / "tasks" / "case1_blocks_write_block_bad_then_good.md"
    dst_dir = repo_root / "tests" / "_tmp_tasks" / "gate_report"
    dst_dir.mkdir(parents=True, exist_ok=True)
    task = dst_dir / "case_gate_report.md"
    shutil.copyfile(src, task)

    outdir = tmp_path / "out_gate_report"
    p = subprocess.run(
        [
            "python",
            "batch_agent.py",
            "--chat",
            "--tasks-format",
            "blocks",
            "--stub-model",
            "bad_then_good_py",
            "--repair-retries",
            "2",
            "--outdir",
            str(outdir),
            str(task),
        ],
        cwd=str(repo_root),
        env=_safe_env(),
        capture_output=True,
        text=True,
    )
    assert p.returncode == 0, f"stdout={p.stdout}\nstderr={p.stderr}"

    report_path = outdir / "gate_report.json"
    assert report_path.exists()
    data = json.loads(report_path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    assert "gate_counts" in data
    assert data["gate_counts"].get("PY_COMPILE_FAILED", 0) >= 1
    assert data.get("tasks"), "tasks list missing"
    t0 = data["tasks"][0]
    assert isinstance(t0.get("attempts"), list)
    assert any(int(a.get("attempt", -1)) == 0 for a in t0["attempts"])
