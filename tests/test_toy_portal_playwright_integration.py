from __future__ import annotations

import importlib.util
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import urlopen

import pytest

from ai_deney.connectors.toy_portal_playwright import ToyPortalPlaywrightConnector


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
            with urlopen(url, timeout=1.0) as r:  # nosec B310 - localhost integration server
                if int(getattr(r, "status", 200)) == 200:
                    return
        except URLError:
            pass
        time.sleep(0.2)
    raise RuntimeError(f"toy portal health check did not become ready: {url}")


def _fetch_json(url: str) -> dict | list:
    with urlopen(url, timeout=4.0) as r:  # nosec B310 - localhost integration server
        payload = r.read().decode("utf-8")
    return json.loads(payload)


@pytest.mark.integration
def test_toy_portal_playwright_flow_checkin_and_export(tmp_path: Path) -> None:
    if not _has_module("fastapi") or not _has_module("uvicorn"):
        pytest.skip("toy portal integration requires fastapi+uvicorn")
    if not _has_module("playwright"):
        pytest.skip("toy portal integration requires playwright")

    repo_root = Path(__file__).resolve().parents[1]
    work_root = repo_root / "tests" / "_tmp_tasks" / "toy_portal_playwright_integration"
    shutil.rmtree(work_root, ignore_errors=True)
    work_root.mkdir(parents=True, exist_ok=True)
    db_path = tmp_path / "toy.db"
    seed = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.toy_hotel_portal.seed",
            "--db",
            str(db_path),
            "--rows",
            "180",
            "--seed",
            "20260301",
            "--date-start",
            "2025-01-01",
            "--date-end",
            "2025-12-31",
            "--hot-range",
            "2025-06-19:2025-06-25",
            "--hot-occupancy",
            "0.75",
            "--reset",
        ],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )
    assert seed.returncode == 0, seed.stderr or seed.stdout

    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    launch_code = (
        "from pathlib import Path;"
        "import uvicorn;"
        "from tools.toy_hotel_portal.app import create_app;"
        f"app=create_app(repo_root=Path({str(repo_root)!r}), db_path=Path({str(db_path)!r}));"
        f"uvicorn.run(app, host='127.0.0.1', port={int(port)}, log_level='warning')"
    )
    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    proc = subprocess.Popen(
        [sys.executable, "-c", launch_code],
        cwd=str(repo_root),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        _wait_health(f"{base_url}/health")
        query = urlencode({"start": "2025-03-01", "end": "2025-03-31", "limit": 1000})
        before = _fetch_json(f"{base_url}/api/reservations?{query}")
        assert isinstance(before, list)
        before_count = len(before)

        connector = ToyPortalPlaywrightConnector(
            repo_root=repo_root,
            raw_root=work_root / "raw",
            screenshot_root=work_root / "screenshots",
            portal_base_url=base_url,
            timeout_ms=12000,
            max_retries=1,
        )
        try:
            connector.open_dashboard(start_date="2025-03-01", end_date="2025-03-31")
            success_text = connector.submit_checkin(
                {
                    "reservation_id": "PW-INT-0001",
                    "guest_name": "Playwright Integration",
                    "check_in": "2025-03-20",
                    "check_out": "2025-03-22",
                    "room_type": "suite",
                    "adults": "2",
                    "children": "0",
                    "source_channel": "booking",
                    "nightly_rate": "180.00",
                    "total_paid": "360.00",
                    "currency": "USD",
                }
            )
            out_file = connector.download_export_csv(start_date="2025-03-01", end_date="2025-03-31", run_id="integration")
        except RuntimeError as exc:
            msg = str(exc)
            if "playwright is not installed" in msg or "Executable doesn't exist" in msg:
                pytest.skip(f"playwright browser/runtime unavailable: {msg}")
            raise

        assert "Check-in saved" in success_text
        after = _fetch_json(f"{base_url}/api/reservations?{query}")
        assert isinstance(after, list)
        assert len(after) == before_count + 1

        assert out_file.exists()
        assert out_file.stat().st_size > 0
        header = out_file.read_text(encoding="utf-8").splitlines()[0]
        assert (
            header
            == "reservation_id,guest_name,check_in,check_out,room_type,adults,children,source_channel,agency_id,agency_name,nightly_rate,total_paid,currency,created_at"
        )
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
