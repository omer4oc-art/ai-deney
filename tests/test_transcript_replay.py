import os
import subprocess
from pathlib import Path


def _safe_env() -> dict[str, str]:
    env = dict(os.environ)
    env["AI_DENEY_PYTEST_ARGS"] = "-k test_ast_quality_gate_text_rejects_top_level_print_and_pass_only"
    return env


def _write_task(repo_root: Path, name: str, prompt_line: str) -> Path:
    tasks_dir = repo_root / "tests" / "_tmp_tasks" / "transcript_replay"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    tasks_path = tasks_dir / name
    tasks_path.write_text(
        "WRITE_BLOCK: outputs/_smoke_agent_quality/replay_ok.py\n"
        "PROMPT:\n"
        f"{prompt_line}\n"
        "END_WRITE_BLOCK\n",
        encoding="utf-8",
    )
    return tasks_path


def test_record_then_replay_roundtrip_stub(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    task = _write_task(repo_root, "tasks_transcript_roundtrip.md", "Write ok() -> int returning 1.")
    out1 = tmp_path / "out_record"
    p1 = subprocess.run(
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
            "--record-transcript",
            "--outdir",
            str(out1),
            str(task),
        ],
        cwd=str(repo_root),
        env=_safe_env(),
        capture_output=True,
        text=True,
    )
    assert p1.returncode == 0, f"stdout={p1.stdout}\nstderr={p1.stderr}"
    transcript = out1 / "transcript.jsonl"
    assert transcript.exists()
    lines = [ln for ln in transcript.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) >= 2, "expected at least 2 model calls due to repair"

    out2 = tmp_path / "out_replay"
    p2 = subprocess.run(
        [
            "python",
            "batch_agent.py",
            "--chat",
            "--tasks-format",
            "blocks",
            "--replay-transcript",
            str(transcript),
            "--repair-retries",
            "2",
            "--outdir",
            str(out2),
            str(task),
        ],
        cwd=str(repo_root),
        env=_safe_env(),
        capture_output=True,
        text=True,
    )
    assert p2.returncode == 0, f"stdout={p2.stdout}\nstderr={p2.stderr}"
    gen = out2 / "generated" / "outputs" / "_smoke_agent_quality" / "replay_ok.py"
    assert gen.exists()
    pc = subprocess.run(["python", "-m", "py_compile", str(gen)], capture_output=True, text=True)
    assert pc.returncode == 0, f"stdout={pc.stdout}\nstderr={pc.stderr}"
    idx = (out2 / "index.md").read_text(encoding="utf-8")
    assert "gate-summary" in idx


def test_replay_strict_mismatch_fails_with_clear_error(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    task1 = _write_task(repo_root, "tasks_transcript_mismatch_a.md", "Write ok() -> int returning 1.")
    out1 = tmp_path / "out_record_mismatch"
    p1 = subprocess.run(
        [
            "python",
            "batch_agent.py",
            "--chat",
            "--tasks-format",
            "blocks",
            "--stub-model",
            "good_py_add",
            "--repair-retries",
            "1",
            "--record-transcript",
            "--outdir",
            str(out1),
            str(task1),
        ],
        cwd=str(repo_root),
        env=_safe_env(),
        capture_output=True,
        text=True,
    )
    assert p1.returncode == 0, f"stdout={p1.stdout}\nstderr={p1.stderr}"

    task2 = _write_task(repo_root, "tasks_transcript_mismatch_b.md", "Write ok() -> int returning 2.")
    out2 = tmp_path / "out_replay_mismatch"
    transcript = out1 / "transcript.jsonl"
    p2 = subprocess.run(
        [
            "python",
            "batch_agent.py",
            "--chat",
            "--tasks-format",
            "blocks",
            "--replay-transcript",
            str(transcript),
            "--replay-strict",
            "--outdir",
            str(out2),
            str(task2),
        ],
        cwd=str(repo_root),
        env=_safe_env(),
        capture_output=True,
        text=True,
    )
    assert p2.returncode != 0
    err_files = sorted(out2.glob("*.error.txt"))
    assert err_files, f"stdout={p2.stdout}\nstderr={p2.stderr}"
    err_text = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in err_files)
    assert "REPLAY_PROMPT_MISMATCH" in err_text
    assert "expected_hash=" in err_text
    assert "got_hash=" in err_text
