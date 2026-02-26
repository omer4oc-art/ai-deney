import os
import shutil
import subprocess
from pathlib import Path


def _init_mini_repo(tmp_path: Path) -> Path:
    repo_root = Path(__file__).resolve().parents[1]
    src_release = repo_root / "scripts" / "release.sh"

    r = tmp_path / "mini_repo"
    (r / "scripts").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src_release, r / "scripts" / "release.sh")
    (r / "scripts" / "check.sh").write_text("#!/usr/bin/env bash\nset -euo pipefail\necho check_ok\n", encoding="utf-8")
    (r / "scripts" / "run_eval_pack.sh").write_text("#!/usr/bin/env bash\nset -euo pipefail\necho eval_ok\n", encoding="utf-8")
    (r / "VERSION").write_text("9.9.9\n", encoding="utf-8")

    subprocess.run(["chmod", "+x", "scripts/release.sh", "scripts/check.sh", "scripts/run_eval_pack.sh"], cwd=str(r), check=True)
    subprocess.run(["git", "init"], cwd=str(r), check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "ci@example.com"], cwd=str(r), check=True)
    subprocess.run(["git", "config", "user.name", "CI"], cwd=str(r), check=True)
    subprocess.run(["git", "add", "."], cwd=str(r), check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(r), check=True, capture_output=True, text=True)
    return r


def test_release_dry_run_in_clean_repo(tmp_path: Path) -> None:
    r = _init_mini_repo(tmp_path)

    env = dict(os.environ)
    env["RELEASE_CHECK_CMD"] = "bash scripts/check.sh"
    env["RELEASE_EVAL_CMD"] = "bash scripts/run_eval_pack.sh"
    p = subprocess.run(
        ["bash", "scripts/release.sh", "--tag", "v0.0.1", "--dry-run"],
        cwd=str(r),
        env=env,
        capture_output=True,
        text=True,
    )
    assert p.returncode == 0, f"stdout={p.stdout}\nstderr={p.stderr}"
    out = p.stdout + p.stderr
    assert "dry_run=1" in out
    assert "would_create_tag=v0.0.1" in out
    assert (r / "VERSION").read_text(encoding="utf-8").strip() == "9.9.9"
    tags = subprocess.run(["git", "tag"], cwd=str(r), check=True, capture_output=True, text=True).stdout.strip()
    assert tags == ""


def test_release_invalid_semver_fails(tmp_path: Path) -> None:
    r = _init_mini_repo(tmp_path)
    env = dict(os.environ)
    env["RELEASE_CHECK_CMD"] = "bash scripts/check.sh"
    env["RELEASE_EVAL_CMD"] = "bash scripts/run_eval_pack.sh"
    p = subprocess.run(
        ["bash", "scripts/release.sh", "--tag", "v1.2", "--dry-run"],
        cwd=str(r),
        env=env,
        capture_output=True,
        text=True,
    )
    assert p.returncode != 0
    assert "Invalid tag format" in (p.stdout + p.stderr)


def test_release_non_dry_run_updates_files_and_creates_tag(tmp_path: Path) -> None:
    r = _init_mini_repo(tmp_path)
    env = dict(os.environ)
    env["RELEASE_CHECK_CMD"] = "bash scripts/check.sh"
    env["RELEASE_EVAL_CMD"] = "bash scripts/run_eval_pack.sh"
    p = subprocess.run(
        ["bash", "scripts/release.sh", "--tag", "v0.0.1"],
        cwd=str(r),
        env=env,
        capture_output=True,
        text=True,
    )
    assert p.returncode == 0, f"stdout={p.stdout}\nstderr={p.stderr}"
    assert (r / "VERSION").read_text(encoding="utf-8").strip() == "0.0.1"
    changelog = (r / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## v0.0.1 -" in changelog
    assert "- commit:" in changelog
    tags = subprocess.run(["git", "tag"], cwd=str(r), check=True, capture_output=True, text=True).stdout.splitlines()
    assert "v0.0.1" in tags
