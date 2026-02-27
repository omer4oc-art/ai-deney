"""Deterministic mock connector for HotelRunner exports."""

from __future__ import annotations

import shutil
from pathlib import Path

from .hotelrunner_base import HotelRunnerConnectorBase

_SUPPORTED_REPORT_TYPES = {"daily_sales"}


def _ensure_within_root(path: Path, root: Path) -> None:
    try:
        path.resolve().relative_to(root.resolve())
    except Exception as exc:
        raise ValueError(f"path escapes repo root: {path}") from exc


class HotelRunnerMockConnector(HotelRunnerConnectorBase):
    """
    Resolve HotelRunner reports from local fixtures and copy them to
    deterministic raw-data locations.
    """

    def __init__(
        self,
        repo_root: Path | None = None,
        raw_root: Path | None = None,
        fixture_root: Path | None = None,
    ) -> None:
        self.repo_root = (repo_root or Path(__file__).resolve().parents[3]).resolve()
        self.fixture_root = (fixture_root or (self.repo_root / "fixtures" / "hotelrunner")).resolve()
        self.raw_root = (raw_root or (self.repo_root / "data" / "raw" / "hotelrunner_mock")).resolve()

        _ensure_within_root(self.fixture_root, self.repo_root)
        _ensure_within_root(self.raw_root, self.repo_root)

    def fetch_report(self, report_type: str, params: dict) -> list[Path]:
        """
        Copy fixture exports for ``report_type`` and ``years`` into ``data/raw``.

        Params:
        - ``years``: list[int] (or ``year`` for a single year)
        """
        if report_type not in _SUPPORTED_REPORT_TYPES:
            raise ValueError(f"unsupported report_type: {report_type}")

        years = self._coerce_years(params)
        out_paths: list[Path] = []

        for year in years:
            fixture_name = f"daily_sales_{year}.csv"
            src = self.fixture_root / fixture_name
            if not src.exists():
                raise FileNotFoundError(f"fixture not found: {src}")

            target_dir = self.raw_root / report_type / str(year)
            _ensure_within_root(target_dir, self.repo_root)
            target_dir.mkdir(parents=True, exist_ok=True)
            dst = target_dir / fixture_name
            shutil.copyfile(src, dst)
            out_paths.append(dst)

        return out_paths

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
