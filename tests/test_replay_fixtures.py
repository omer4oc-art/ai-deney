import os
import subprocess
from pathlib import Path


def _safe_env() -> dict[str, str]:
    env = dict(os.environ)
    env["AI_DENEY_PYTEST_ARGS"] = "-k test_ast_quality_gate_text_rejects_top_level_print_and_pass_only"
    return env


def _write_fixture_task(repo_root: Path, case_name: str) -> Path:
    tasks_dir = repo_root / "tests" / "_tmp_tasks" / "replay_fixtures"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    task = tasks_dir / f"{case_name}.md"
    task.write_text(
        "WRITE_BLOCK: outputs/_smoke_agent_quality/replay_fixture_ok.py\n"
        "PROMPT:\n"
        "Write ok() -> int returning 1.\n"
        "END_WRITE_BLOCK\n",
        encoding="utf-8",
    )
    return task


def test_replay_fixture_bad_then_good_py(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    task = _write_fixture_task(repo_root, "fixture_bad_then_good")
    fixture = repo_root / "tests" / "fixtures" / "transcripts" / "bad_then_good_py" / "transcript.jsonl"
    outdir = tmp_path / "out_replay_fixture_1"
    p = subprocess.run(
        [
            "python",
            "batch_agent.py",
            "--chat",
            "--tasks-format",
            "blocks",
            "--replay-transcript",
            str(fixture),
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
    py_file = outdir / "generated" / "outputs" / "_smoke_agent_quality" / "replay_fixture_ok.py"
    assert py_file.exists()
    c = subprocess.run(["python", "-m", "py_compile", str(py_file)], capture_output=True, text=True)
    assert c.returncode == 0, f"stdout={c.stdout}\nstderr={c.stderr}"


def test_replay_fixture_ast_todo_then_good(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    task = _write_fixture_task(repo_root, "fixture_ast_todo")
    fixture = repo_root / "tests" / "fixtures" / "transcripts" / "ast_todo_then_good" / "transcript.jsonl"
    outdir = tmp_path / "out_replay_fixture_2"
    p = subprocess.run(
        [
            "python",
            "batch_agent.py",
            "--chat",
            "--tasks-format",
            "blocks",
            "--replay-transcript",
            str(fixture),
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
    py_file = outdir / "generated" / "outputs" / "_smoke_agent_quality" / "replay_fixture_ok.py"
    assert py_file.exists()
    c = subprocess.run(["python", "-m", "py_compile", str(py_file)], capture_output=True, text=True)
    assert c.returncode == 0, f"stdout={c.stdout}\nstderr={c.stderr}"
