import os
import subprocess
from pathlib import Path


def test_end_of_batch_pytest_gate(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]

    fail_test = repo_root / "tests" / "_tmp_force_fail_test.py"
    fail_test.write_text(
        "def test__force_fail_gate():\n"
        "    assert False\n",
        encoding="utf-8",
    )

    tasks_dir = repo_root / "tests" / "_tmp_tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    tasks_path = tasks_dir / "tasks_write_raw_ok_for_pytest_gate.txt"
    tasks_path.write_text(
        "WRITE_RAW=ok_raw.py\n"
        "def ok(a: int) -> int:\n"
        "    return a + 1\n"
        "END_WRITE_RAW\n",
        encoding="utf-8",
    )

    outdir = tmp_path / "out_batch_pytest_gate"
    outdir.mkdir(parents=True, exist_ok=True)

    env = dict(os.environ)
    env["AI_DENEY_PYTEST_ARGS"] = "-k test__force_fail_gate"

    try:
        p = subprocess.run(
            ["python", "batch_agent.py", str(tasks_path), "--outdir", str(outdir)],
            cwd=str(repo_root),
            env=env,
            capture_output=True,
            text=True,
        )

        assert p.returncode != 0, f"expected nonzero exit; stdout={p.stdout}\nstderr={p.stderr}"

        err = outdir / "pytest.error.txt"
        if not err.exists():
            files = sorted(str(x.relative_to(outdir)) for x in outdir.rglob("*") if x.is_file())
            raise AssertionError(
                "expected pytest.error.txt to exist, but it did not\n"
                f"outdir={outdir}\n"
                f"files={files}\n"
                f"stdout={p.stdout}\n"
                f"stderr={p.stderr}\n"
            )
    finally:
        if fail_test.exists():
            fail_test.unlink()
