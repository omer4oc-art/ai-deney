from pathlib import Path
import pytest

from ai_deney.validation import run_py_compile, GateError


def test_py_compile_pass(tmp_path: Path) -> None:
    f = tmp_path / "ok.py"
    f.write_text("x = 1\n", encoding="utf-8")
    run_py_compile(f)


def test_py_compile_fail(tmp_path: Path) -> None:
    f = tmp_path / "bad.py"
    f.write_text("def oops(:\n    pass\n", encoding="utf-8")
    with pytest.raises(GateError):
        run_py_compile(f)
