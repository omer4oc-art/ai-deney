from __future__ import annotations

import subprocess
from pathlib import Path


class GateError(RuntimeError):
    """Raised when a quality gate fails (py_compile, pytest, etc.)."""


def run_py_compile(python_file: Path) -> None:
    python_file = Path(python_file).resolve()

    if not python_file.exists():
        raise GateError(f"py_compile target does not exist: {python_file}")
    if python_file.suffix != ".py":
        raise GateError(f"py_compile target is not a .py file: {python_file}")

    cmd = ["python", "-m", "py_compile", str(python_file)]
    p = subprocess.run(cmd, capture_output=True, text=True)

    if p.returncode != 0:
        stderr = (p.stderr or "").strip()
        stdout = (p.stdout or "").strip()
        msg = "py_compile failed"
        if stderr:
            msg += f"\nSTDERR:\n{stderr}"
        if stdout:
            msg += f"\nSTDOUT:\n{stdout}"
        raise GateError(msg)
