"""Query specification for Electra report intent parsing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ReportName = Literal["sales_summary", "sales_by_agency"]
GroupBy = Literal["agency"]
OutputFormat = Literal["markdown"]


@dataclass(frozen=True)
class QuerySpec:
    """
    Structured query for Electra reporting.

    Fields are intentionally compact and stable so they can be serialized and
    validated by future router/overseer layers.
    """

    report: ReportName
    years: list[int]
    group_by: GroupBy | None = None
    output_format: OutputFormat = "markdown"
    compare: bool = False
    original_text: str = ""

    @property
    def registry_key(self) -> str:
        return f"electra.{self.report}"

