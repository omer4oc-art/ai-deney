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
    "reconcile_daily",
    "reconcile_monthly",
    "reconcile_daily_by_agency",
    "reconcile_monthly_by_agency",
    "reconcile_anomalies_agency",
    "mapping_health_agency",
    "mapping_health_channel",
    "mapping_unmapped_agency",
    "mapping_drift_agency",
]
SourceName = Literal["electra", "reconcile", "mapping"]


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
    source: SourceName = "electra"
    original_text: str = ""

    @property
    def registry_key(self) -> str:
        if self.source == "reconcile":
            if self.analysis == "reconcile_monthly":
                return "reconcile.monthly"
            if self.analysis == "reconcile_daily_by_agency":
                return "reconcile.daily_by_agency"
            if self.analysis == "reconcile_monthly_by_agency":
                return "reconcile.monthly_by_agency"
            if self.analysis == "reconcile_anomalies_agency":
                return "reconcile.anomalies_agency"
            return "reconcile.daily"
        if self.source == "mapping":
            if self.analysis == "mapping_health_channel":
                return "mapping.health_channel"
            return "mapping.health_agency"
        key = self.analysis or self.report
        return f"electra.{key}"
