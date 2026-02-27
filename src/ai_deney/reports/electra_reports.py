"""Electra report executors and markdown rendering."""

from __future__ import annotations

from pathlib import Path

from ai_deney.analytics.electra_queries import get_sales_by_agency, get_sales_years
from ai_deney.connectors.electra_mock import ElectraMockConnector
from ai_deney.intent.electra_intent import parse_electra_query
from ai_deney.parsing.electra_sales import normalize_report_files
from ai_deney.reports.registry import ReportRegistry


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _default_normalized_root() -> Path:
    return _repo_root() / "data" / "normalized"


def _default_raw_root() -> Path:
    return _repo_root() / "data" / "raw" / "electra_mock"


def _df_records(df) -> list[dict]:
    if hasattr(df, "to_dict"):
        return df.to_dict("records")
    raise TypeError("unsupported dataframe-like object")


def ensure_normalized_data(years: list[int], reports: list[str], normalized_root: Path | None = None, raw_root: Path | None = None) -> None:
    """
    Ensure normalized data exists for requested years using deterministic fixtures.
    """

    normalized = (normalized_root or _default_normalized_root()).resolve()
    raw = (raw_root or _default_raw_root()).resolve()
    repo = _repo_root().resolve()
    for path in (normalized, raw):
        try:
            path.relative_to(repo)
        except Exception as exc:
            raise ValueError(f"path escapes repo root: {path}") from exc

    conn = ElectraMockConnector(repo_root=repo, raw_root=raw)
    if "sales_summary" in reports:
        summary_paths = conn.fetch_report("sales_summary", {"years": years})
        normalize_report_files(summary_paths, report_type="sales_summary", output_root=normalized)
    if "sales_by_agency" in reports:
        agency_paths = conn.fetch_report("sales_by_agency", {"years": years})
        normalize_report_files(agency_paths, report_type="sales_by_agency", output_root=normalized)


def run_sales_summary(years: list[int], normalized_root: Path | None = None):
    return get_sales_years(years, normalized_root=normalized_root)


def run_sales_by_agency(years: list[int], normalized_root: Path | None = None):
    return get_sales_by_agency(years, normalized_root=normalized_root)


def _format_value(value) -> str:
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def render_markdown(df, title: str, notes: str) -> str:
    """Render dataframe-like rows as markdown."""
    rows = _df_records(df)
    if not rows:
        return f"# {title}\n\n{notes}\n\n_No rows_\n"

    columns = list(rows[0].keys())
    lines = [f"# {title}", "", notes, ""]
    lines.append("| " + " | ".join(columns) + " |")
    lines.append("| " + " | ".join(["---"] * len(columns)) + " |")
    for row in rows:
        lines.append("| " + " | ".join(_format_value(row.get(col, "")) for col in columns) + " |")
    lines.append("")
    return "\n".join(lines)


def _comparison_note(spec_years: list[int], rows: list[dict], report: str) -> str:
    if len(spec_years) < 2:
        return ""
    y0, y1 = sorted(spec_years)[0], sorted(spec_years)[-1]
    if report == "sales_summary":
        r0 = next((r for r in rows if int(r.get("year", -1)) == y0), None)
        r1 = next((r for r in rows if int(r.get("year", -1)) == y1), None)
        if r0 and r1:
            d = float(r1["gross_sales"]) - float(r0["gross_sales"])
            return f"Comparison {y0} -> {y1}: gross_sales delta is {d:.2f}."
    if report == "sales_by_agency":
        sums: dict[int, float] = {}
        for row in rows:
            y = int(row["year"])
            sums[y] = sums.get(y, 0.0) + float(row["gross_sales"])
        if y0 in sums and y1 in sums:
            d = sums[y1] - sums[y0]
            return f"Comparison {y0} -> {y1}: total agency gross delta is {d:.2f}."
    return ""


def _build_registry(normalized_root: Path | None = None) -> ReportRegistry:
    registry = ReportRegistry()
    registry.register("electra.sales_summary", lambda years: run_sales_summary(years, normalized_root=normalized_root))
    registry.register("electra.sales_by_agency", lambda years: run_sales_by_agency(years, normalized_root=normalized_root))
    return registry


def answer_question(text: str, normalized_root: Path | None = None) -> str:
    """
    Parse question -> execute report -> render markdown answer.
    """

    spec = parse_electra_query(text)
    ensure_normalized_data(spec.years, reports=[spec.report], normalized_root=normalized_root)
    registry = _build_registry(normalized_root=normalized_root)
    executor = registry.get(spec.registry_key)
    df = executor(spec.years)
    rows = _df_records(df)

    years_label = ", ".join(str(y) for y in spec.years)
    if spec.report == "sales_summary":
        title = f"Sales Summary ({years_label})"
        notes = f"Sales summary totals for years: {years_label}."
    else:
        title = f"Sales By Agency ({years_label})"
        notes = f"Sales categorized by agencies for years: {years_label}."

    if spec.compare:
        comp = _comparison_note(spec.years, rows, spec.report)
        if comp:
            notes = f"{notes} {comp}"

    return render_markdown(df, title=title, notes=notes)

