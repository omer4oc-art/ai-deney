import sys
from pathlib import Path

import pytest

import batch_agent as b


def _run_main_with_argv(monkeypatch, argv: list[str]) -> None:
    monkeypatch.setattr(sys, "argv", argv)
    b.main()


def test_repair_compile_fail_then_success_write_block(tmp_path: Path, monkeypatch) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    tasks_dir = repo_root / "tests" / "_tmp_tasks" / "repair_compile"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    tasks_path = tasks_dir / "write_block_compile_fix.md"
    tasks_path.write_text(
        "WRITE_BLOCK: outputs/_smoke_agent_quality/repair_compile.py\n"
        "EXPECT:\n"
        "- must_contain: \"def add(\"\n"
        "- must_contain: \"return a + b\"\n"
        "PROMPT:\n"
        "Write add(a: int, b: int) -> int.\n"
        "END_WRITE_BLOCK\n",
        encoding="utf-8",
    )

    calls = {"n": 0}

    def fake_generate(prompt: str, stream: bool = False) -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            return "def add(:\n    pass\n"
        return "def add(a: int, b: int) -> int:\n    return a + b\n"

    monkeypatch.setattr(b, "generate", fake_generate)
    monkeypatch.setattr(b, "_maybe_run_pytest", lambda project_root: (True, "pytest skipped (stubbed)"))

    outdir = tmp_path / "out_compile_repair"
    _run_main_with_argv(
        monkeypatch,
        [
            "batch_agent.py",
            str(tasks_path),
            "--outdir",
            str(outdir),
            "--repair-retries",
            "1",
        ],
    )

    assert calls["n"] == 2
    gen = outdir / "generated" / "outputs" / "_smoke_agent_quality" / "repair_compile.py"
    assert gen.exists()
    ok, msg = b._lint_python_file(gen)
    assert ok, msg


def test_repair_expect_fail_then_success_write_block(tmp_path: Path, monkeypatch) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    tasks_dir = repo_root / "tests" / "_tmp_tasks" / "repair_expect"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    tasks_path = tasks_dir / "write_block_expect_fix.md"
    tasks_path.write_text(
        "WRITE_BLOCK: outputs/_smoke_agent_quality/repair_expect.py\n"
        "EXPECT:\n"
        "- must_contain: \"return a + b\"\n"
        "- forbid: \"```\"\n"
        "PROMPT:\n"
        "Write add(a: int, b: int) -> int.\n"
        "END_WRITE_BLOCK\n",
        encoding="utf-8",
    )

    calls = {"n": 0}

    def fake_generate(prompt: str, stream: bool = False) -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            return "def add(a: int, b: int) -> int:\n    return a - b\n"
        return "def add(a: int, b: int) -> int:\n    return a + b\n"

    monkeypatch.setattr(b, "generate", fake_generate)
    monkeypatch.setattr(b, "_maybe_run_pytest", lambda project_root: (True, "pytest skipped (stubbed)"))

    outdir = tmp_path / "out_expect_repair"
    _run_main_with_argv(
        monkeypatch,
        [
            "batch_agent.py",
            str(tasks_path),
            "--outdir",
            str(outdir),
            "--repair-retries",
            "1",
        ],
    )

    assert calls["n"] == 2
    gen = outdir / "generated" / "outputs" / "_smoke_agent_quality" / "repair_expect.py"
    assert gen.exists()
    txt = gen.read_text(encoding="utf-8")
    assert "return a + b" in txt
    idx = (outdir / "index.md").read_text(encoding="utf-8")
    assert "EXPECT_MISSING" in idx
    assert "final: PASS" in idx


def test_repair_ast_fail_then_success_write_block(tmp_path: Path, monkeypatch) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    tasks_dir = repo_root / "tests" / "_tmp_tasks" / "repair_ast"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    tasks_path = tasks_dir / "write_block_ast_fix.md"
    tasks_path.write_text(
        "WRITE_BLOCK: outputs/_smoke_agent_quality/repair_ast.py\n"
        "PROMPT:\n"
        "Write add(a: int, b: int) -> int.\n"
        "END_WRITE_BLOCK\n",
        encoding="utf-8",
    )

    calls = {"n": 0}

    def fake_generate(prompt: str, stream: bool = False) -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            return "def add(a: int, b: int) -> int:\n    pass\n"
        return "def add(a: int, b: int) -> int:\n    return a + b\n"

    monkeypatch.setattr(b, "generate", fake_generate)
    monkeypatch.setattr(b, "_maybe_run_pytest", lambda project_root: (True, "pytest skipped (stubbed)"))

    outdir = tmp_path / "out_ast_repair"
    _run_main_with_argv(
        monkeypatch,
        [
            "batch_agent.py",
            str(tasks_path),
            "--outdir",
            str(outdir),
            "--repair-retries",
            "1",
        ],
    )

    assert calls["n"] == 2
    gen = outdir / "generated" / "outputs" / "_smoke_agent_quality" / "repair_ast.py"
    assert gen.exists()
    ok, msg = b._run_python_file_gates(gen)
    assert ok, msg


def test_repair_commented_out_duplicate_def_then_success(tmp_path: Path, monkeypatch) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    tasks_dir = repo_root / "tests" / "_tmp_tasks" / "repair_commented_dup"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    tasks_path = tasks_dir / "write_block_commented_dup_fix.md"
    tasks_path.write_text(
        "WRITE_BLOCK: outputs/_smoke_agent_quality/repair_commented_dup.py\n"
        "PROMPT:\n"
        "Write ok() that returns 1.\n"
        "END_WRITE_BLOCK\n",
        encoding="utf-8",
    )

    calls = {"n": 0}

    def fake_generate(prompt: str, stream: bool = False) -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            return (
                "def ok() -> int:\n"
                "    return 1\n\n"
                "# def ok():\n"
                "#     raise RuntimeError('This task cannot be completed.')\n"
            )
        return "def ok() -> int:\n    return 1\n"

    monkeypatch.setattr(b, "generate", fake_generate)
    monkeypatch.setattr(b, "_maybe_run_pytest", lambda project_root: (True, "pytest skipped (stubbed)"))

    outdir = tmp_path / "out_commented_dup_repair"
    _run_main_with_argv(
        monkeypatch,
        [
            "batch_agent.py",
            str(tasks_path),
            "--outdir",
            str(outdir),
            "--repair-retries",
            "1",
        ],
    )

    assert calls["n"] == 2
    gen = outdir / "generated" / "outputs" / "_smoke_agent_quality" / "repair_commented_dup.py"
    assert gen.exists()
    ok, msg = b._lint_python_file(gen)
    assert ok, msg
    txt = gen.read_text(encoding="utf-8")
    assert "# def ok(" not in txt


def test_repair_fail_after_retries_includes_status_in_index(tmp_path: Path, monkeypatch) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    tasks_dir = repo_root / "tests" / "_tmp_tasks" / "repair_fail_after"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    tasks_path = tasks_dir / "write_block_fail_after.md"
    tasks_path.write_text(
        "WRITE_BLOCK: outputs/_smoke_agent_quality/repair_fail_after.py\n"
        "PROMPT:\n"
        "Write ok() that returns 1.\n"
        "END_WRITE_BLOCK\n",
        encoding="utf-8",
    )

    calls = {"n": 0}

    def fake_generate(prompt: str, stream: bool = False) -> str:
        calls["n"] += 1
        return "def ok() -> int:\n    pass\n"

    monkeypatch.setattr(b, "generate", fake_generate)
    monkeypatch.setattr(b, "_maybe_run_pytest", lambda project_root: (True, "pytest skipped (stubbed)"))

    outdir = tmp_path / "out_fail_after"
    with pytest.raises(SystemExit):
        _run_main_with_argv(
            monkeypatch,
            [
                "batch_agent.py",
                str(tasks_path),
                "--outdir",
                str(outdir),
                "--repair-retries",
                "1",
            ],
        )

    idx = (outdir / "index.md").read_text(encoding="utf-8")
    assert "AST_PASS_ONLY_FUNCTION" in idx
    assert "FAIL_AFTER_RETRIES" in idx


def test_py_contract_strict_triggers_repair_without_explicit_expect(tmp_path: Path, monkeypatch) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    tasks_dir = repo_root / "tests" / "_tmp_tasks" / "contract_strict_exec"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    tasks_path = tasks_dir / "write_block_contract_strict.md"
    tasks_path.write_text(
        "PY_CONTRACT: strict\n"
        "WRITE_BLOCK: outputs/_smoke_agent_quality/contract_strict.py\n"
        "PROMPT:\n"
        "Write ok() returning 1.\n"
        "END_WRITE_BLOCK\n",
        encoding="utf-8",
    )

    calls = {"n": 0}

    def fake_generate(prompt: str, stream: bool = False) -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            return (
                "def ok() -> int:\n"
                "    return 1\n"
                "# TODO: remove\n"
                "# def ok():\n"
                "#     raise RuntimeError('junk')\n"
            )
        return "def ok() -> int:\n    return 1\n"

    monkeypatch.setattr(b, "generate", fake_generate)
    monkeypatch.setattr(b, "_maybe_run_pytest", lambda project_root: (True, "pytest skipped (stubbed)"))

    outdir = tmp_path / "out_contract_strict"
    _run_main_with_argv(
        monkeypatch,
        [
            "batch_agent.py",
            str(tasks_path),
            "--outdir",
            str(outdir),
            "--repair-retries",
            "1",
        ],
    )

    assert calls["n"] == 2
    gen = outdir / "generated" / "outputs" / "_smoke_agent_quality" / "contract_strict.py"
    assert gen.exists()
    txt = gen.read_text(encoding="utf-8")
    assert "```" not in txt
    assert "TODO" not in txt
    assert "# def ok(" not in txt
    ok, msg = b._run_python_file_gates(gen)
    assert ok, msg
