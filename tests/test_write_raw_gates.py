import subprocess
from pathlib import Path


def test_write_raw_py_compile_gate(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]

    tasks_dir = repo_root / "tests" / "_tmp_tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    tasks_path = tasks_dir / "tasks_write_raw_fail.txt"
    tasks_path.write_text(
        "WRITE_RAW=bad_raw.py\n"
        "def oops(:\n"
        "    pass\n"
        "END_WRITE_RAW\n",
        encoding="utf-8",
    )

    outdir = tmp_path / "out_batch"
    outdir.mkdir(parents=True, exist_ok=True)

    p = subprocess.run(
        ["python", "batch_agent.py", str(tasks_path), "--outdir", str(outdir)],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )

    assert p.returncode != 0, f"expected nonzero exit; stdout={p.stdout}\nstderr={p.stderr}"

    gen = outdir / "generated" / "bad_raw.py"
    if not gen.exists():
        files = sorted(str(x.relative_to(outdir)) for x in outdir.rglob("*") if x.is_file())
        raise AssertionError(
            "expected generated/bad_raw.py to exist, but it did not\n"
            f"outdir={outdir}\n"
            f"files={files}\n"
            f"stdout={p.stdout}\n"
            f"stderr={p.stderr}\n"
        )

    err_files = list(outdir.glob("*.py_compile.error.txt"))
    if not err_files:
        files = sorted(str(x.relative_to(outdir)) for x in outdir.rglob("*") if x.is_file())
        raise AssertionError(
            "expected *.py_compile.error.txt to exist, but none found\n"
            f"outdir={outdir}\n"
            f"files={files}\n"
            f"stdout={p.stdout}\n"
            f"stderr={p.stderr}\n"
        )
