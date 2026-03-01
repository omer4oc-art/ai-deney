from __future__ import annotations

from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from tools.viewer.app import create_app


def test_home_lists_truth_pack() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    app = create_app(repo_root=repo_root)
    client = TestClient(app)

    resp = client.get("/")
    assert resp.status_code == 200
    assert "Truth Pack" in resp.text


def test_truth_pack_run_page_when_available() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    if not (repo_root / "outputs" / "_truth_pack").is_dir():
        pytest.skip("outputs/_truth_pack is not present")

    app = create_app(repo_root=repo_root)
    client = TestClient(app)
    resp = client.get("/run/truth_pack")
    assert resp.status_code == 200
    assert "Truth Pack" in resp.text


def test_path_traversal_rejected() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    app = create_app(repo_root=repo_root)
    client = TestClient(app)

    resp = client.get("/file/%2e%2e/%2e%2e")
    assert resp.status_code in {400, 404}


def test_compare_endpoint_with_temp_runs(tmp_path: Path) -> None:
    truth_pack_root = tmp_path / "outputs" / "_truth_pack"
    inbox_runs_root = tmp_path / "outputs" / "inbox_runs"
    raw_root = tmp_path / "data" / "raw"
    truth_pack_root.mkdir(parents=True, exist_ok=True)
    inbox_runs_root.mkdir(parents=True, exist_ok=True)
    raw_root.mkdir(parents=True, exist_ok=True)

    run_a = inbox_runs_root / "run_a"
    run_b = inbox_runs_root / "run_b"
    run_a.mkdir()
    run_b.mkdir()

    (run_a / "same.md").write_text("# Same\nalpha\n", encoding="utf-8")
    (run_b / "same.md").write_text("# Same\nalpha\n", encoding="utf-8")

    (run_a / "only_a.md").write_text("# A only\n", encoding="utf-8")
    (run_b / "only_b.md").write_text("# B only\n", encoding="utf-8")

    (run_a / "changed.md").write_text("# Changed\nline-a\n", encoding="utf-8")
    (run_b / "changed.md").write_text("# Changed\nline-b\n", encoding="utf-8")

    app = create_app(
        repo_root=tmp_path,
        truth_pack_root=truth_pack_root,
        inbox_runs_root=inbox_runs_root,
        raw_root=raw_root,
    )
    client = TestClient(app)

    compare_resp = client.get("/compare", params={"run_a": "run_a", "run_b": "run_b"})
    assert compare_resp.status_code == 200
    assert "only_a.md" in compare_resp.text
    assert "only_b.md" in compare_resp.text
    assert "changed.md" in compare_resp.text

    diff_resp = client.get("/compare", params={"run_a": "run_a", "run_b": "run_b", "file": "changed.md"})
    assert diff_resp.status_code == 200
    assert "--- run_a/changed.md" in diff_resp.text
    assert "+++ run_b/changed.md" in diff_resp.text
