from __future__ import annotations

import importlib.util
import os
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import pytest


def _has_module(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _seed_toy_db(repo_root: Path, db_path: Path) -> None:
    seed_cmd = [
        sys.executable,
        "-m",
        "tools.toy_hotel_portal.seed",
        "--db",
        str(db_path),
        "--rows",
        "3000",
        "--seed",
        "42",
        "--date-start",
        "2025-01-01",
        "--date-end",
        "2025-12-31",
        "--hot-range",
        "2025-06-19:2025-06-25",
        "--hot-occupancy",
        "0.75",
        "--reset",
    ]
    seeded = subprocess.run(seed_cmd, cwd=str(repo_root), capture_output=True, text=True, check=False)
    assert seeded.returncode == 0, seeded.stderr or seeded.stdout


def _wait_health(url: str, proc: subprocess.Popen[str], timeout_seconds: float = 20.0) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if proc.poll() is not None:
            break
        try:
            with urlopen(url, timeout=1.0) as response:  # nosec B310 - localhost integration server
                if int(getattr(response, "status", 200)) == 200:
                    return
        except URLError:
            pass
        time.sleep(0.2)

    stdout_tail = ""
    stderr_tail = ""
    if proc.poll() is None:
        stdout_tail = "<process still running>"
        stderr_tail = "<process still running>"
    else:
        if proc.stdout:
            try:
                stdout_tail = proc.stdout.read()[-4000:]
            except Exception:
                stdout_tail = ""
        if proc.stderr:
            try:
                stderr_tail = proc.stderr.read()[-4000:]
            except Exception:
                stderr_tail = ""
    raise RuntimeError(
        f"toy portal health check did not become ready: {url}\n"
        f"stdout_tail={stdout_tail}\n"
        f"stderr_tail={stderr_tail}"
    )


def _can_launch_playwright_or_skip() -> None:
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        pytest.skip("toy portal e2e requires playwright")

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            browser.close()
    except Exception as exc:
        msg = str(exc)
        if (
            "Executable doesn't exist" in msg
            or "playwright install" in msg
            or "Permission denied" in msg
            or "Target page, context or browser has been closed" in msg
            or "bootstrap_check_in" in msg
        ):
            pytest.skip(f"playwright browser/runtime unavailable: {msg}")
        raise


@pytest.mark.integration
def test_toy_portal_playwright_ask_panel_e2e(tmp_path: Path) -> None:
    if not _has_module("fastapi") or not _has_module("uvicorn"):
        pytest.skip("toy portal e2e requires fastapi+uvicorn")
    if not _has_module("playwright"):
        pytest.skip("toy portal e2e requires playwright")
    _can_launch_playwright_or_skip()

    repo_root = Path(__file__).resolve().parents[1]
    db_path = tmp_path / "toy_e2e.db"
    _seed_toy_db(repo_root, db_path)

    try:
        port = _free_port()
    except OSError as exc:
        pytest.skip(f"integration environment forbids localhost port binding: {exc}")
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

    page = None
    screenshot_path = (
        repo_root
        / "outputs"
        / "_e2e"
        / f"toy_e2e_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.png"
    )
    screenshot_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        try:
            _wait_health(f"{base_url}/health", proc=proc)
        except RuntimeError as exc:
            msg = str(exc).lower()
            if "bind on address" in msg and "operation not permitted" in msg:
                pytest.skip("integration environment forbids localhost port binding")
            raise

        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(accept_downloads=True)
            page = context.new_page()
            page.set_default_timeout(20000)
            page.goto(f"{base_url}/", wait_until="domcontentloaded")

            page.fill("#ask-input", "Total sales on March 1st 2025 and June 3rd 2025")
            page.select_option("#ask-format", "md")
            if not page.is_checked("#ask-redact"):
                page.check("#ask-redact")
            page.click("#ask-submit")

            page.wait_for_function(
                """
                () => {
                  const output = document.querySelector("#ask-output");
                  if (!output) return false;
                  const text = output.innerText || "";
                  return text.includes("2025-03-01") && text.includes("2025-06-03");
                }
                """,
                timeout=20000,
            )
            output_text = page.inner_text("#ask-output")

            assert "2025-03-01" in output_text
            assert "2025-06-03" in output_text
            assert "4040.47" in output_text
            assert "3970.50" in output_text
            assert "Drew Shaw" not in output_text
            assert "Casey Walker" not in output_text
            assert "Sam Reed" not in output_text

            context.close()
            browser.close()
    except Exception:
        if page is not None:
            try:
                page.screenshot(path=str(screenshot_path), full_page=True)
            except Exception:
                pass
        raise
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
