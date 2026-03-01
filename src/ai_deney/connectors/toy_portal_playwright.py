"""Playwright connector for toy hotel portal dashboard/check-in automation."""

from __future__ import annotations

import re
import time
from pathlib import Path
from urllib.request import urlopen


def _ensure_within_root(path: Path, root: Path) -> None:
    try:
        path.resolve().relative_to(root.resolve())
    except Exception as exc:
        raise ValueError(f"path escapes repo root: {path}") from exc


def _safe_run_id(raw: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", str(raw or "").strip()).strip("._")
    if not cleaned:
        raise ValueError("run_id must not be empty")
    return cleaned


class ToyPortalPlaywrightConnector:
    """Automate toy portal dashboard export + check-in flows using Playwright."""

    def __init__(
        self,
        repo_root: Path | None = None,
        raw_root: Path | None = None,
        portal_base_url: str = "http://127.0.0.1:8011",
        timeout_ms: int = 15000,
        max_retries: int = 2,
        screenshot_root: Path | None = None,
        save_failure_screenshots: bool = True,
    ) -> None:
        self.repo_root = (repo_root or Path(__file__).resolve().parents[3]).resolve()
        self.raw_root = (raw_root or (self.repo_root / "data" / "raw" / "toy_portal_playwright")).resolve()
        self.portal_base_url = str(portal_base_url).rstrip("/")
        self.timeout_ms = int(timeout_ms)
        self.max_retries = max(0, int(max_retries))
        self.screenshot_root = (screenshot_root or (self.repo_root / "outputs" / "_watcher_logs")).resolve()
        self.save_failure_screenshots = bool(save_failure_screenshots)

        _ensure_within_root(self.raw_root, self.repo_root)
        _ensure_within_root(self.screenshot_root, self.repo_root)

    def open_dashboard(self, start_date: str, end_date: str) -> None:
        """Open dashboard, set date inputs, and trigger refresh."""
        self._run_with_retries(
            action_name="open_dashboard",
            callback=lambda attempt: self._open_dashboard_once(start_date=start_date, end_date=end_date, attempt=attempt),
        )

    def download_export_csv(self, start_date: str, end_date: str, run_id: str) -> Path:
        """Open dashboard and download CSV export into data/raw/toy_portal_playwright/<run_id>/."""
        safe_run_id = _safe_run_id(run_id)
        target_dir = self.raw_root / safe_run_id
        _ensure_within_root(target_dir, self.repo_root)
        target_dir.mkdir(parents=True, exist_ok=True)

        dst = self._run_with_retries(
            action_name="download_export_csv",
            callback=lambda attempt: self._download_export_once(
                start_date=start_date,
                end_date=end_date,
                target_dir=target_dir,
                attempt=attempt,
            ),
        )
        if not isinstance(dst, Path):
            raise RuntimeError("download_export_csv did not produce a file path")
        if (not dst.exists()) or int(dst.stat().st_size) <= 0:
            raise RuntimeError(f"download failed or empty file: {dst}")
        return dst

    def submit_checkin(self, payload: dict[str, object]) -> str:
        """Open check-in page, submit the form, and return success text."""
        return str(
            self._run_with_retries(
                action_name="submit_checkin",
                callback=lambda attempt: self._submit_checkin_once(payload=payload, attempt=attempt),
            )
        )

    def _run_with_retries(self, action_name: str, callback):
        last_exc: Exception | None = None
        errors: list[str] = []
        for attempt in range(1, self.max_retries + 2):
            try:
                self._probe_portal_health()
                return callback(attempt)
            except Exception as exc:  # pragma: no cover - retry behavior depends on runtime/environment
                last_exc = exc
                errors.append(f"attempt={attempt}: {exc}")
                time.sleep(0.2)
        if last_exc is None:
            raise RuntimeError(f"{action_name} failed without explicit error")
        error_text = "; ".join(errors)
        raise RuntimeError(f"{action_name} failed after {self.max_retries + 1} attempt(s): {error_text}") from last_exc

    def _open_dashboard_once(self, start_date: str, end_date: str, attempt: int) -> None:
        page = None
        with self._playwright_context() as context:
            try:
                page = context.new_page()
                page.set_default_timeout(self.timeout_ms)
                page.goto(f"{self.portal_base_url}/", wait_until="domcontentloaded")
                self._set_dashboard_range(page=page, start_date=start_date, end_date=end_date)
            except Exception:
                self._save_failure_screenshot(page=page, action="open_dashboard", attempt=attempt)
                raise

    def _download_export_once(self, start_date: str, end_date: str, target_dir: Path, attempt: int) -> Path:
        page = None
        with self._playwright_context() as context:
            try:
                page = context.new_page()
                page.set_default_timeout(self.timeout_ms)
                page.goto(f"{self.portal_base_url}/", wait_until="domcontentloaded")
                self._set_dashboard_range(page=page, start_date=start_date, end_date=end_date)
                with page.expect_download(timeout=max(self.timeout_ms, 4000)) as dl:
                    page.click("#export-btn")
                download = dl.value
                suggested = str(download.suggested_filename or "").strip()
                filename = suggested or f"toy_portal_{start_date}_{end_date}.csv"
                dst = target_dir / filename
                _ensure_within_root(dst, self.repo_root)
                download.save_as(str(dst))
                return dst
            except Exception:
                self._save_failure_screenshot(page=page, action="download_export_csv", attempt=attempt)
                raise

    def _submit_checkin_once(self, payload: dict[str, object], attempt: int) -> str:
        page = None
        with self._playwright_context() as context:
            try:
                page = context.new_page()
                page.set_default_timeout(self.timeout_ms)
                page.goto(f"{self.portal_base_url}/checkin", wait_until="domcontentloaded")
                page.wait_for_selector("#checkin-form")

                values = self._coerce_checkin_values(payload)
                for field, value in values.items():
                    selector = f"#{field}"
                    if field in {"room_type", "source_channel", "currency"}:
                        page.select_option(selector, str(value))
                    else:
                        page.fill(selector, str(value))

                page.click("#checkin-submit")
                page.wait_for_selector("#checkin-success:not(.hidden)", timeout=self.timeout_ms)
                return page.locator("#checkin-success").inner_text().strip()
            except Exception:
                self._save_failure_screenshot(page=page, action="submit_checkin", attempt=attempt)
                raise

    @staticmethod
    def _coerce_checkin_values(payload: dict[str, object]) -> dict[str, str]:
        required = {
            "guest_name": "Playwright Guest",
            "check_in": "2025-03-10",
            "check_out": "2025-03-12",
            "room_type": "standard",
            "adults": "2",
            "children": "0",
            "source_channel": "direct",
            "agency_id": "",
            "agency_name": "",
            "nightly_rate": "110.00",
            "total_paid": "220.00",
            "currency": "USD",
        }
        out: dict[str, str] = {}
        for field, default_value in required.items():
            value = payload.get(field, default_value)
            out[field] = str(default_value if value is None else value)
        if str(payload.get("reservation_id", "")).strip():
            out["reservation_id"] = str(payload["reservation_id"])
        return out

    def _set_dashboard_range(self, page, start_date: str, end_date: str) -> None:
        page.fill("#start-date", start_date)
        page.fill("#end-date", end_date)
        with page.expect_response(
            lambda resp: (
                "/api/occupancy" in resp.url
                and f"start={start_date}" in resp.url
                and f"end={end_date}" in resp.url
            ),
            timeout=self.timeout_ms,
        ):
            page.click("#refresh-btn")
        page.wait_for_selector("#occupancy-chart [data-bar-fill]")

    def _probe_portal_health(self) -> None:
        health_url = f"{self.portal_base_url}/health"
        try:
            with urlopen(health_url, timeout=2.0) as response:  # nosec B310 - trusted local portal URL
                status = int(getattr(response, "status", 200))
                if status >= 400:
                    raise RuntimeError(f"health probe returned HTTP {status}")
        except Exception as exc:
            raise RuntimeError(
                f"Toy portal not reachable at {self.portal_base_url}. "
                "Start it with: bash scripts/run_toy_portal.sh "
                f"(details: {exc})"
            ) from exc

    def _playwright_context(self):
        try:
            from playwright.sync_api import sync_playwright
        except Exception as exc:  # pragma: no cover - dependency gate
            raise RuntimeError(
                "playwright is not installed; install with: pip install playwright && playwright install chromium"
            ) from exc

        class _ContextManager:
            def __init__(self, timeout_ms: int):
                self.timeout_ms = timeout_ms
                self._pw = None
                self._browser = None
                self._context = None

            def __enter__(self):
                self._pw = sync_playwright().start()
                self._browser = self._pw.chromium.launch(headless=True)
                self._context = self._browser.new_context(accept_downloads=True)
                return self._context

            def __exit__(self, exc_type, exc, tb):
                if self._context is not None:
                    self._context.close()
                if self._browser is not None:
                    self._browser.close()
                if self._pw is not None:
                    self._pw.stop()
                return False

        return _ContextManager(timeout_ms=self.timeout_ms)

    def _save_failure_screenshot(self, page, action: str, attempt: int) -> None:
        if (not self.save_failure_screenshots) or page is None:
            return
        self.screenshot_root.mkdir(parents=True, exist_ok=True)
        out = self.screenshot_root / f"toy_portal_fail_{action}_attempt{attempt}.png"
        _ensure_within_root(out, self.repo_root)
        try:
            page.screenshot(path=str(out), full_page=True)
        except Exception:
            return
