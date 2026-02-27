"""Playwright connector scaffold for Electra Test Portal."""

from __future__ import annotations

import hashlib
from pathlib import Path
from urllib.request import urlopen

from .electra_base import ElectraConnectorBase

_SUPPORTED_REPORT_TYPES = {"sales_summary", "sales_by_agency"}


def _ensure_within_root(path: Path, root: Path) -> None:
    try:
        path.resolve().relative_to(root.resolve())
    except Exception as exc:
        raise ValueError(f"path escapes repo root: {path}") from exc


class ElectraPlaywrightConnector(ElectraConnectorBase):
    """Download Electra report exports from the local test portal via browser automation."""

    def __init__(
        self,
        repo_root: Path | None = None,
        raw_root: Path | None = None,
        portal_base_url: str = "http://127.0.0.1:8008",
        username: str = "demo",
        password: str = "demo123",
        timeout_ms: int = 15000,
        max_retries: int = 2,
        screenshot_root: Path | None = None,
    ) -> None:
        self.repo_root = (repo_root or Path(__file__).resolve().parents[3]).resolve()
        self.raw_root = (raw_root or (self.repo_root / "data" / "raw" / "electra_portal")).resolve()
        self.portal_base_url = portal_base_url.rstrip("/")
        self.username = username
        self.password = password
        self.timeout_ms = int(timeout_ms)
        self.max_retries = max(0, int(max_retries))
        self.screenshot_root = (screenshot_root or (self.repo_root / "outputs" / "_watcher_logs")).resolve()

        _ensure_within_root(self.raw_root, self.repo_root)
        _ensure_within_root(self.screenshot_root, self.repo_root)

    def fetch_report(self, report_type: str, params: dict) -> list[Path]:
        if report_type not in _SUPPORTED_REPORT_TYPES:
            raise ValueError(f"unsupported report_type: {report_type}")

        years = self._coerce_years(params)
        variant = str(params.get("export_variant", "canonical")).strip().lower() or "canonical"
        run_id = str(params.get("run_id", self._build_run_id(report_type=report_type, years=years, variant=variant))).strip()
        if not run_id:
            raise ValueError("run_id must not be empty")

        out_paths: list[Path] = []
        for year in years:
            target_dir = self.raw_root / run_id / report_type / str(int(year))
            _ensure_within_root(target_dir, self.repo_root)
            target_dir.mkdir(parents=True, exist_ok=True)
            dst = target_dir / f"{report_type}_{int(year)}.csv"
            self._download_with_retries(report_type=report_type, year=int(year), variant=variant, dst=dst)
            if not dst.exists() or int(dst.stat().st_size) <= 0:
                raise RuntimeError(f"download failed or empty file: {dst}")
            out_paths.append(dst)

        return out_paths

    def _download_with_retries(self, report_type: str, year: int, variant: str, dst: Path) -> None:
        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 2):
            try:
                self._download_once(report_type=report_type, year=year, variant=variant, dst=dst, attempt=attempt)
                return
            except Exception as exc:  # pragma: no cover - retry branch is environment-specific
                last_exc = exc
                if attempt > self.max_retries:
                    break
        if last_exc is None:
            raise RuntimeError("portal download failed without explicit error")
        raise RuntimeError(f"portal download failed for {report_type}/{year}: {last_exc}") from last_exc

    def _download_once(self, report_type: str, year: int, variant: str, dst: Path, attempt: int) -> None:
        self._probe_portal_health()
        try:
            from playwright.sync_api import sync_playwright
        except Exception as exc:  # pragma: no cover - dependency gate
            raise RuntimeError(
                "playwright is not installed; install with: pip install playwright && playwright install chromium"
            ) from exc

        page = None
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(accept_downloads=True)
            try:
                page = context.new_page()
                page.set_default_timeout(self.timeout_ms)

                page.goto(f"{self.portal_base_url}/login", wait_until="domcontentloaded")
                page.fill("input[name='username']", self.username)
                page.fill("input[name='password']", self.password)
                page.click("#login-submit")
                page.wait_for_url("**/reports")

                page.goto(f"{self.portal_base_url}/reports", wait_until="domcontentloaded")
                page.select_option("select[name='report_type']", report_type)
                page.fill("input[name='years']", str(year))
                page.select_option("select[name='variant']", variant)

                with page.expect_download(timeout=self.timeout_ms) as dl:
                    page.click("#download-submit")
                download = dl.value
                download.save_as(str(dst))
            except Exception:
                self._save_failure_screenshot(page=page, report_type=report_type, year=year, attempt=attempt)
                raise
            finally:
                context.close()
                browser.close()

    def _probe_portal_health(self) -> None:
        health_url = f"{self.portal_base_url}/health"
        try:
            with urlopen(health_url, timeout=2.0) as response:  # nosec B310 - trusted local portal URL
                status = int(getattr(response, "status", 200))
                if status >= 400:
                    raise RuntimeError(f"health probe returned HTTP {status}")
        except Exception as exc:
            raise RuntimeError(
                f"Electra Test Portal not reachable at {self.portal_base_url}. "
                "Start it with: bash scripts/run_electra_test_portal.sh "
                f"(details: {exc})"
            ) from exc

    def _save_failure_screenshot(self, page, report_type: str, year: int, attempt: int) -> None:
        if page is None:
            return
        self.screenshot_root.mkdir(parents=True, exist_ok=True)
        out = self.screenshot_root / f"electra_portal_fail_{report_type}_{year}_attempt{attempt}.png"
        _ensure_within_root(out, self.repo_root)
        try:
            page.screenshot(path=str(out), full_page=True)
        except Exception:
            return

    @staticmethod
    def _coerce_years(params: dict) -> list[int]:
        if "years" in params:
            years_raw = params["years"]
        elif "year" in params:
            years_raw = [params["year"]]
        else:
            raise ValueError("params must include 'years' or 'year'")
        if not isinstance(years_raw, list):
            raise ValueError("'years' must be a list[int]")
        years: list[int] = []
        for y in years_raw:
            years.append(int(y))
        if not years:
            raise ValueError("at least one year is required")
        return sorted(set(years))

    @staticmethod
    def _build_run_id(report_type: str, years: list[int], variant: str) -> str:
        seed = f"{report_type}:{','.join(str(y) for y in years)}:{variant}"
        digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:10]
        return f"portal_{digest}"
