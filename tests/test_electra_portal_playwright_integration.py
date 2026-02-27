import csv
import importlib.util
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import pytest

from ai_deney.connectors.electra_playwright import ElectraPlaywrightConnector
from ai_deney.parsing.electra_sales import normalize_report_files


def _has_module(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _wait_health(url: str, timeout_seconds: float = 12.0) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            with urlopen(url, timeout=1.0) as r:  # nosec B310 - localhost test server
                if r.status == 200:
                    return
        except URLError:
            pass
        time.sleep(0.2)
    raise RuntimeError(f"portal health check did not become ready: {url}")


@pytest.mark.integration
def test_portal_playwright_download_and_normalize(tmp_path: Path) -> None:
    if not _has_module("fastapi") or not _has_module("uvicorn"):
        pytest.skip("portal integration requires fastapi+uvicorn")
    if not _has_module("playwright"):
        pytest.skip("portal integration requires playwright")

    repo_root = Path(__file__).resolve().parents[1]
    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"

    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"

    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app:app",
            "--app-dir",
            "tools/electra_test_portal",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=str(repo_root),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        _wait_health(f"{base_url}/health")

        connector = ElectraPlaywrightConnector(
            repo_root=repo_root,
            raw_root=tmp_path / "raw",
            portal_base_url=base_url,
            username="demo",
            password="demo123",
            screenshot_root=tmp_path / "screenshots",
            timeout_ms=12000,
            max_retries=1,
        )

        try:
            downloaded = connector.fetch_report(
                "sales_summary",
                {
                    "years": [2025],
                    "run_id": "integration",
                    "export_variant": "messy",
                },
            )
        except RuntimeError as exc:
            msg = str(exc)
            if "playwright is not installed" in msg or "Executable doesn't exist" in msg:
                pytest.skip(f"playwright browser/runtime unavailable: {msg}")
            raise

        assert len(downloaded) == 1
        assert downloaded[0].exists()
        assert downloaded[0].stat().st_size > 0

        out_paths = normalize_report_files(downloaded, report_type="sales_summary", output_root=tmp_path / "normalized")
        assert out_paths
        normalized = tmp_path / "normalized" / "electra_sales_2025.csv"
        assert normalized.exists()
        with normalized.open("r", encoding="utf-8", newline="") as f:
            row = next(csv.DictReader(f))
        assert {"date", "year", "agency_id", "agency_name", "gross_sales", "net_sales", "currency"} <= set(row.keys())
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
