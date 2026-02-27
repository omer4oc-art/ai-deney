import importlib.util
import os
import shutil
import subprocess
from pathlib import Path

import pytest


def _has_module(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _run_dir_from_stdout(stdout: str) -> Path | None:
    for line in stdout.splitlines():
        if line.startswith("PORTAL_TO_INBOX_RUN_DIR="):
            raw = line.split("=", 1)[1].strip()
            if raw:
                return Path(raw)
    return None


@pytest.mark.integration
def test_portal_to_inbox_truth_pack_script_creates_inbox_and_run_artifacts() -> None:
    if not _has_module("fastapi") or not _has_module("uvicorn") or not _has_module("multipart"):
        pytest.skip("portal e2e integration requires fastapi+uvicorn+python-multipart")
    if not _has_module("playwright"):
        pytest.skip("portal e2e integration requires playwright")

    repo_root = Path(__file__).resolve().parents[1]
    work_root = repo_root / "tests" / "_tmp_tasks" / "portal_to_inbox_truth_pack" / "basic"
    shutil.rmtree(work_root, ignore_errors=True)
    work_root.mkdir(parents=True, exist_ok=True)

    inbox_root = work_root / "data" / "inbox"
    truth_pack_out = work_root / "outputs" / "truth_pack"
    runs_root = work_root / "outputs" / "inbox_runs"

    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"

    p = subprocess.run(
        [
            "bash",
            "scripts/portal_to_inbox_truth_pack.sh",
            "--inbox-root",
            str(inbox_root),
            "--truth-pack-out",
            str(truth_pack_out),
            "--runs-root",
            str(runs_root),
            "--date",
            "2025-06-25",
            "--variant",
            "canonical",
        ],
        cwd=str(repo_root),
        env=env,
        capture_output=True,
        text=True,
    )

    if p.returncode != 0:
        out = f"{p.stdout}\n{p.stderr}"
        if "Executable doesn't exist" in out or "playwright is not installed" in out:
            pytest.skip(f"playwright browser/runtime unavailable: {out}")
    assert p.returncode == 0, f"stdout={p.stdout}\nstderr={p.stderr}"

    assert (inbox_root / "electra" / "electra_sales_summary_2025-06-25.csv").exists()
    assert (inbox_root / "electra" / "electra_sales_by_agency_2025-06-25.csv").exists()
    assert (inbox_root / "hotelrunner" / "hotelrunner_daily_sales_2025-06-25.csv").exists()

    run_dir = _run_dir_from_stdout(p.stdout)
    assert run_dir is not None, f"stdout={p.stdout}\nstderr={p.stderr}"
    assert run_dir.exists()
    assert str(run_dir.resolve()).startswith(str(runs_root.resolve()))
    assert (run_dir / "manifest.json").exists()
    assert (run_dir / "index.md").exists()
