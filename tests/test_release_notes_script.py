import os
import subprocess
from pathlib import Path


def test_release_notes_script_reads_changelog_section(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    (tmp_path / "CHANGELOG.md").write_text(
        "# Changelog\n\n"
        "## v0.0.1 - 2026-02-26\n"
        "- first item\n"
        "- second item\n\n"
        "## v0.0.0 - 2026-02-25\n"
        "- older\n",
        encoding="utf-8",
    )
    env = dict(os.environ)
    env["AI_DENEY_REPO_ROOT"] = str(tmp_path)
    p = subprocess.run(
        ["bash", "scripts/release_notes.sh", "v0.0.1"],
        cwd=str(repo_root),
        env=env,
        capture_output=True,
        text=True,
    )
    assert p.returncode == 0, f"stdout={p.stdout}\nstderr={p.stderr}"
    out = p.stdout
    assert "## v0.0.1 - 2026-02-26" in out
    assert "- first item" in out
    assert "v0.0.0" not in out
