"""Query specification for Electra report intent parsing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ReportName = Literal["sales_summary", "sales_by_agency"]
GroupBy = Literal["agency", "month"]
OutputFormat = Literal["markdown", "html"]
AnalysisName = Literal[
    "sales_summary",
    "sales_by_agency",
    "sales_by_month",
    "top_agencies",
    "direct_share",
]


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
    analysis: AnalysisName | None = None
    top_n: int = 5
    original_text: str = ""

    @property
    def registry_key(self) -> str:
        key = self.analysis or self.report
        return f"electra.{key}"
