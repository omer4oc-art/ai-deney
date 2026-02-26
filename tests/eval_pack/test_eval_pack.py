import os
import py_compile
import shutil
import subprocess
from pathlib import Path


def _safe_env() -> dict[str, str]:
    env = dict(os.environ)
    env["AI_DENEY_PYTEST_ARGS"] = "-k test_ast_quality_gate_text_rejects_top_level_print_and_pass_only"
    return env


def _prepare_task_copy(repo_root: Path, fixture_name: str) -> Path:
    src = repo_root / "tests" / "eval_pack" / "tasks" / fixture_name
    dst_dir = repo_root / "tests" / "_tmp_tasks" / "eval_pack"
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / fixture_name
    shutil.copyfile(src, dst)
    return dst


def _run_batch(repo_root: Path, task_path: Path, outdir: Path, extra: list[str]) -> subprocess.CompletedProcess[str]:
    cmd = ["python", "batch_agent.py", "--outdir", str(outdir), str(task_path), *extra]
    return subprocess.run(
        cmd,
        cwd=str(repo_root),
        env=_safe_env(),
        capture_output=True,
        text=True,
    )


def _assert_ok(p: subprocess.CompletedProcess[str]) -> None:
    assert p.returncode == 0, f"stdout={p.stdout}\nstderr={p.stderr}"


def test_eval_case_1_blocks_write_block_bad_then_good_bundle(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    task = _prepare_task_copy(repo_root, "case1_blocks_write_block_bad_then_good.md")
    outdir = tmp_path / "case1"
    p = _run_batch(
        repo_root,
        task,
        outdir,
        ["--chat", "--tasks-format", "blocks", "--stub-model", "bad_then_good_py", "--repair-retries", "2", "--bundle"],
    )
    _assert_ok(p)
    gen = outdir / "generated" / "ok.py"
    assert gen.exists()
    py_compile.compile(str(gen), doraise=True)
    idx = (outdir / "index.md").read_text(encoding="utf-8")
    assert "gate-summary" in idx
    assert "attempt 0: PY_COMPILE_FAILED" in idx
    assert "final: PASS" in idx
    bundle = (outdir / "bundle.txt").read_text(encoding="utf-8")
    assert "number_of_tasks=" in bundle
    assert "number_of_generated_files=" in bundle
    assert "GATE_SUMMARY:" in bundle


def test_eval_case_2_lines_rejects_write_block(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    task = _prepare_task_copy(repo_root, "case2_lines_reject_write_block.md")
    outdir = tmp_path / "case2"
    p = _run_batch(
        repo_root,
        task,
        outdir,
        ["--chat", "--tasks-format", "lines", "--stub-model", "good_py_add"],
    )
    assert p.returncode != 0
    assert "WRITE_BLOCK not supported in --tasks-format=lines" in (p.stdout + p.stderr)


def test_eval_case_3_tidy_contract_repairs(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    task = _prepare_task_copy(repo_root, "case3_tidy_contract.md")
    outdir = tmp_path / "case3"
    p = _run_batch(
        repo_root,
        task,
        outdir,
        ["--chat", "--tasks-format", "blocks", "--stub-model", "tidy_weird_then_good", "--repair-retries", "2"],
    )
    _assert_ok(p)
    txt = (outdir / "generated" / "tidy_ok.py").read_text(encoding="utf-8")
    assert "if not True" not in txt
    assert "never be reached" not in txt
    assert "isinstance((), tuple)" not in txt


def test_eval_case_4_strict_contract_dupdef_repairs(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    task = _prepare_task_copy(repo_root, "case4_strict_contract_dupdef.md")
    outdir = tmp_path / "case4"
    p = _run_batch(
        repo_root,
        task,
        outdir,
        ["--chat", "--tasks-format", "blocks", "--stub-model", "dupdef_then_good", "--repair-retries", "2"],
    )
    _assert_ok(p)
    txt = (outdir / "generated" / "strict_ok.py").read_text(encoding="utf-8")
    assert "# def ok(" not in txt


def test_eval_case_5_ast_todo_repairs(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    task = _prepare_task_copy(repo_root, "case5_ast_todo.md")
    outdir = tmp_path / "case5"
    p = _run_batch(
        repo_root,
        task,
        outdir,
        ["--chat", "--tasks-format", "blocks", "--stub-model", "ast_todo_then_good", "--repair-retries", "2"],
    )
    _assert_ok(p)
    idx = (outdir / "index.md").read_text(encoding="utf-8")
    assert "AST_TODO_FOUND" in idx
    assert "final: PASS" in idx


def test_eval_case_6_write_raw_compile_fail_keeps_file(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    task = _prepare_task_copy(repo_root, "case6_write_raw_compile_fail.md")
    outdir = tmp_path / "case6"
    p = _run_batch(
        repo_root,
        task,
        outdir,
        ["--chat", "--tasks-format", "blocks", "--stub-model", "good_py_add", "--repair-retries", "0"],
    )
    assert p.returncode != 0
    gen = outdir / "generated" / "bad_raw.py"
    assert gen.exists()
    idx = (outdir / "index.md").read_text(encoding="utf-8")
    assert "PY_COMPILE_FAILED" in idx


def test_eval_case_7_write_directive_coverage(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    task = _prepare_task_copy(repo_root, "case7_write_good_py.md")
    outdir = tmp_path / "case7"
    p = _run_batch(
        repo_root,
        task,
        outdir,
        ["--chat", "--tasks-format", "blocks", "--stub-model", "good_py_add", "--repair-retries", "1"],
    )
    _assert_ok(p)
    gen = outdir / "generated" / "write_ok.py"
    assert gen.exists()


def test_eval_case_8_file_directive_coverage(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    task = _prepare_task_copy(repo_root, "case8_file_directive.md")
    outdir = tmp_path / "case8"
    p = _run_batch(
        repo_root,
        task,
        outdir,
        ["--chat", "--tasks-format", "blocks", "--stub-model", "good_py_add"],
    )
    _assert_ok(p)
    outs = list(outdir.glob("*.txt"))
    assert outs, f"expected chat output txt file, got stdout={p.stdout}\nstderr={p.stderr}"
