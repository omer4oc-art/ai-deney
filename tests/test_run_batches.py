import json
import os
import subprocess
from pathlib import Path


def _safe_env() -> dict[str, str]:
    env = dict(os.environ)
    env["AI_DENEY_PYTEST_ARGS"] = "-k test_ast_quality_gate_text_rejects_top_level_print_and_pass_only"
    return env


def test_run_batches_creates_summary_and_batch_dirs(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    tasks_dir = repo_root / "tests" / "_tmp_tasks" / "run_batches"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    (tasks_dir / "a_first.md").write_text(
        "WRITE_BLOCK: outputs/_smoke_agent_quality/batch_a.py\n"
        "PROMPT:\n"
        "Write ok() -> int returning 1.\n"
        "END_WRITE_BLOCK\n",
        encoding="utf-8",
    )
    (tasks_dir / "b_second.md").write_text(
        "WRITE_BLOCK: outputs/_smoke_agent_quality/batch_b.py\n"
        "PROMPT:\n"
        "Write add(a: int, b: int) -> int returning a + b.\n"
        "END_WRITE_BLOCK\n",
        encoding="utf-8",
    )
    outbase = tmp_path / "multi_batches"
    p = subprocess.run(
        [
            "python3",
            "scripts/run_batches.py",
            str(tasks_dir),
            "--outbase",
            str(outbase),
            "--stub-model",
            "good_py_add",
            "--repair-retries",
            "0",
            "--bundle",
            "--html",
        ],
        cwd=str(repo_root),
        env=_safe_env(),
        capture_output=True,
        text=True,
    )
    assert p.returncode == 0, f"stdout={p.stdout}\nstderr={p.stderr}"
    summary_json = outbase / "summary.json"
    summary_md = outbase / "summary.md"
    summary_html = outbase / "summary.html"
    assert summary_json.exists()
    assert summary_md.exists()
    assert summary_html.exists()
    data = json.loads(summary_json.read_text(encoding="utf-8"))
    assert "gate_counts" in data
    assert isinstance(data["gate_counts"], dict)
    assert "aggregate_gate_counts" in data
    assert isinstance(data["aggregate_gate_counts"], dict)
    assert "known_gate_keys" in data
    assert isinstance(data["known_gate_keys"], list)
    assert "PY_COMPILE_FAILED" in data["aggregate_gate_counts"]
    md_text = summary_md.read_text(encoding="utf-8")
    assert "index.md" in md_text
    assert "bundle.txt" in md_text
    assert "gate_report.json" in md_text
    batch_dirs = sorted([p for p in outbase.iterdir() if p.is_dir() and p.name.startswith("batch_")])
    assert len(batch_dirs) == 2
