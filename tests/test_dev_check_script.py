import os
import subprocess
from pathlib import Path

import pytest


_EXPECTED_REPO = Path("/Users/omer/ai-deney/week1")
_FIX_CMD = "cd /Users/omer/ai-deney/week1 && source .venv/bin/activate"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _guardrail_env(repo_root: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["VIRTUAL_ENV"] = str((repo_root / ".venv").resolve())
    return env


def _assert_expected_layout(repo_root: Path) -> None:
    if repo_root.resolve() != _EXPECTED_REPO.resolve():
        pytest.skip("dev_check.sh is intentionally pinned to /Users/omer/ai-deney/week1")
    if not (repo_root / ".venv" / "bin" / "python3").exists():
        pytest.skip("expected .venv/bin/python3 to exist")


def test_dev_scripts_exist_and_are_executable() -> None:
    repo_root = _repo_root()
    dev_check = repo_root / "scripts" / "dev_check.sh"
    dev_run_all = repo_root / "scripts" / "dev_run_all.sh"
    assert dev_check.exists()
    assert dev_run_all.exists()
    assert os.access(dev_check, os.X_OK)
    assert os.access(dev_run_all, os.X_OK)


def test_dev_check_passes_from_repo_root() -> None:
    repo_root = _repo_root()
    _assert_expected_layout(repo_root)

    p = subprocess.run(
        ["bash", "scripts/dev_check.sh"],
        cwd=str(repo_root),
        env=_guardrail_env(repo_root),
        capture_output=True,
        text=True,
    )
    assert p.returncode == 0, f"stdout={p.stdout}\nstderr={p.stderr}"
    assert "dev_check: OK" in p.stdout


def test_dev_check_fails_from_wrong_directory(tmp_path: Path) -> None:
    repo_root = _repo_root()
    _assert_expected_layout(repo_root)

    p = subprocess.run(
        ["bash", str(repo_root / "scripts" / "dev_check.sh")],
        cwd=str(tmp_path),
        env=_guardrail_env(repo_root),
        capture_output=True,
        text=True,
    )
    assert p.returncode != 0
    out = p.stdout + p.stderr
    assert "wrong directory" in out
    assert _FIX_CMD in out
