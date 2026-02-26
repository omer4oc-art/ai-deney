import os
import subprocess
from pathlib import Path


def _safe_env() -> dict[str, str]:
    env = dict(os.environ)
    # Prevent nested batch pytest from recursing through heavy integration tests.
    env["AI_DENEY_PYTEST_ARGS"] = "-k test_ast_quality_gate_text_rejects_top_level_print_and_pass_only"
    return env


def test_stub_model_cli_write_block_repairs_without_ollama(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    tasks_dir = repo_root / "tests" / "_tmp_tasks" / "stub_model_cli"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    tasks_path = tasks_dir / "tasks_stub_bad_then_good.txt"
    tasks_path.write_text(
        "WRITE_BLOCK: outputs/_smoke_agent_quality/stub_ok.py\n"
        "PROMPT:\n"
        "Write ok() -> int returning 1.\n"
        "END_WRITE_BLOCK\n",
        encoding="utf-8",
    )

    outdir = tmp_path / "out_stub_cli"
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
            "--bundle",
            "--outdir",
            str(outdir),
            str(tasks_path),
        ],
        cwd=str(repo_root),
        env=_safe_env(),
        capture_output=True,
        text=True,
    )
    assert p.returncode == 0, f"stdout={p.stdout}\nstderr={p.stderr}"
    gen = outdir / "generated" / "outputs" / "_smoke_agent_quality" / "stub_ok.py"
    assert gen.exists()
    assert (outdir / "bundle.txt").exists()
    idx = (outdir / "index.md").read_text(encoding="utf-8")
    assert "gate-summary" in idx
    assert "attempt 0: PY_COMPILE_FAILED" in idx
    assert "final: PASS" in idx


def test_tasks_format_lines_rejects_write_block_cli(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    tasks_dir = repo_root / "tests" / "_tmp_tasks" / "lines_mode_cli"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    tasks_path = tasks_dir / "tasks_lines_reject.md"
    tasks_path.write_text(
        "WRITE_BLOCK: outputs/_smoke_agent_quality/lines_reject.py\n"
        "PROMPT:\n"
        "Write ok() -> int returning 1.\n"
        "END_WRITE_BLOCK\n",
        encoding="utf-8",
    )
    outdir = tmp_path / "out_lines_reject"
    p = subprocess.run(
        [
            "python",
            "batch_agent.py",
            "--tasks-format",
            "lines",
            "--stub-model",
            "good_py_add",
            "--outdir",
            str(outdir),
            str(tasks_path),
        ],
        cwd=str(repo_root),
        env=_safe_env(),
        capture_output=True,
        text=True,
    )
    assert p.returncode != 0
    assert "WRITE_BLOCK not supported in --tasks-format=lines" in (p.stdout + p.stderr)


def test_py_contract_tidy_with_stub_repairs(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    tasks_dir = repo_root / "tests" / "_tmp_tasks" / "contract_tidy_cli"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    tasks_path = tasks_dir / "tasks_contract_tidy.md"
    tasks_path.write_text(
        "PY_CONTRACT: tidy\n"
        "WRITE_BLOCK: outputs/_smoke_agent_quality/tidy_ok.py\n"
        "PROMPT:\n"
        "Write ok() -> int returning 1.\n"
        "END_WRITE_BLOCK\n",
        encoding="utf-8",
    )
    outdir = tmp_path / "out_tidy_cli"
    p = subprocess.run(
        [
            "python",
            "batch_agent.py",
            "--chat",
            "--tasks-format",
            "blocks",
            "--stub-model",
            "tidy_weird_then_good",
            "--repair-retries",
            "2",
            "--outdir",
            str(outdir),
            str(tasks_path),
        ],
        cwd=str(repo_root),
        env=_safe_env(),
        capture_output=True,
        text=True,
    )
    assert p.returncode == 0, f"stdout={p.stdout}\nstderr={p.stderr}"
    gen = outdir / "generated" / "outputs" / "_smoke_agent_quality" / "tidy_ok.py"
    assert gen.exists()
    txt = gen.read_text(encoding="utf-8")
    assert "if not True" not in txt
    assert "never be reached" not in txt
    assert "isinstance((), tuple)" not in txt
