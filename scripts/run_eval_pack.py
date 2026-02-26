#!/usr/bin/env python3
import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    env["AI_DENEY_PYTEST_ARGS"] = "-k test_ast_quality_gate_text_rejects_top_level_print_and_pass_only"

    venv_pytest = repo_root / ".venv" / "bin" / "pytest"
    if venv_pytest.exists():
        cmd = [str(venv_pytest), "-q", "tests/eval_pack"]
    else:
        cmd = [sys.executable, "-m", "pytest", "-q", "tests/eval_pack"]

    p = subprocess.run(cmd, cwd=str(repo_root), env=env)
    return p.returncode


if __name__ == "__main__":
    raise SystemExit(main())
