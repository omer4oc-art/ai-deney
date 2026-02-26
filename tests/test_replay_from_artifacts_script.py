import subprocess
import os
import shutil
from pathlib import Path


def test_replay_from_artifacts_missing_transcript_fails_cleanly(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    art = tmp_path / "artifact_dir"
    art.mkdir(parents=True, exist_ok=True)
    tasks_dir = repo_root / "tests" / "_tmp_tasks" / "replay_from_artifacts"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    task = tasks_dir / "task.md"
    task.write_text(
        "WRITE_BLOCK: outputs/_smoke_agent_quality/ra_ok.py\nPROMPT:\nWrite ok() -> int returning 1.\nEND_WRITE_BLOCK\n",
        encoding="utf-8",
    )
    p = subprocess.run(
        ["bash", "scripts/replay_from_artifacts.sh", str(art), str(task)],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    assert p.returncode != 0
    assert "No transcript.jsonl found under:" in (p.stdout + p.stderr)


def test_replay_from_artifacts_autopicks_task_and_succeeds(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    art = tmp_path / "artifact_dir"
    fixture = repo_root / "tests" / "fixtures" / "transcripts" / "bad_then_good_py"
    shutil.copytree(fixture, art / "fixture_copy")
    task_dir = art / "tests" / "_tmp_tasks" / "from_artifact"
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "task.md").write_text(
        "WRITE_BLOCK: outputs/_smoke_agent_quality/replay_fixture_ok.py\n"
        "PROMPT:\n"
        "Write ok() -> int returning 1.\n"
        "END_WRITE_BLOCK\n",
        encoding="utf-8",
    )
    env = dict(os.environ)
    env["AI_DENEY_PYTEST_ARGS"] = "-k test_ast_quality_gate_text_rejects_top_level_print_and_pass_only"
    p = subprocess.run(
        ["bash", "scripts/replay_from_artifacts.sh", str(art)],
        cwd=str(repo_root),
        env=env,
        capture_output=True,
        text=True,
    )
    assert p.returncode == 0, f"stdout={p.stdout}\nstderr={p.stderr}"
    out = p.stdout + p.stderr
    assert "transcript_path=" in out
    assert "taskfile_path=" in out
    assert "outdir=" in out
    assert (art / "replay_out" / "generated" / "outputs" / "_smoke_agent_quality" / "replay_fixture_ok.py").exists()
