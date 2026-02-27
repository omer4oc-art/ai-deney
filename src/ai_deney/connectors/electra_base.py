"""Connector abstractions for Electra report fetching."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class ElectraConnectorBase(ABC):
    """
    Base interface for Electra report connectors.

    Implementations should fetch one or more report artifacts for the requested
    report type and return local file paths to the downloaded artifacts.
    """

    @abstractmethod
    def fetch_report(self, report_type: str, params: dict) -> list[Path]:
        """
        Fetch report artifacts.

        Supported report_type values:
        - ``sales_summary``
        - ``sales_by_agency``
        """
        raise NotImplementedError

