"""Connector abstractions for HotelRunner report fetching."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class HotelRunnerConnectorBase(ABC):
    """
    Base interface for HotelRunner report connectors.

    Implementations fetch report artifacts for requested years and return local
    paths to deterministic files.
    """

    @abstractmethod
    def fetch_report(self, report_type: str, params: dict) -> list[Path]:
        """
        Fetch report artifacts.

        Supported report_type values:
        - ``daily_sales``
        """
        raise NotImplementedError
