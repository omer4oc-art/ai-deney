"""Electra report executors and deterministic markdown/html rendering."""

from __future__ import annotations

from html import escape
from pathlib import Path

from ai_deney.analytics.electra_queries import (
    get_direct_share,
    get_sales_by_agency,
    get_sales_by_month,
    get_sales_years,
    get_top_agencies,
)
from ai_deney.connectors.electra_mock import ElectraMockConnector
from ai_deney.intent.electra_intent import parse_electra_query
from ai_deney.parsing.electra_sales import normalize_report_files
from ai_deney.reports.registry import ReportRegistry

_DETERMINISTIC_SOURCE_FOOTER = "Source: Electra mock fixtures; Generated: deterministic run."


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


def ensure_normalized_data(
    years: list[int],
    reports: list[str],
    normalized_root: Path | None = None,
    raw_root: Path | None = None,
) -> None:
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


def run_sales_by_month(years: list[int], normalized_root: Path | None = None):
    return get_sales_by_month(years, normalized_root=normalized_root)


def run_top_agencies(years: list[int], top_n: int = 5, normalized_root: Path | None = None):
    return get_top_agencies(years, top_n=top_n, normalized_root=normalized_root)


def run_direct_share(years: list[int], normalized_root: Path | None = None):
    return get_direct_share(years, normalized_root=normalized_root)


def _format_value(value) -> str:
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def _sorted_rows(rows: list[dict], sort_by: str | list[str] | None = None, descending: bool = False) -> list[dict]:
    if not rows or not sort_by:
        return rows
    keys = [sort_by] if isinstance(sort_by, str) else list(sort_by)
    return sorted(rows, key=lambda r: tuple(r.get(k) for k in keys), reverse=descending)


def render_markdown(
    df,
    title: str,
    notes: str,
    sort_by: str | list[str] | None = None,
    descending: bool = False,
) -> str:
    """Render dataframe-like rows as markdown with deterministic footer."""
    rows = _sorted_rows(_df_records(df), sort_by=sort_by, descending=descending)
    if not rows:
        return (
            f"# {title}\n\n{notes}\n\n_No rows_\n\n"
            f"Data freshness / source: {_DETERMINISTIC_SOURCE_FOOTER}\n"
        )

    columns = list(rows[0].keys())
    lines = [f"# {title}", "", notes, ""]
    lines.append("| " + " | ".join(columns) + " |")
    lines.append("| " + " | ".join(["---"] * len(columns)) + " |")
    for row in rows:
        lines.append("| " + " | ".join(_format_value(row.get(col, "")) for col in columns) + " |")
    lines.append("")
    lines.append(f"Data freshness / source: {_DETERMINISTIC_SOURCE_FOOTER}")
    lines.append("")
    return "\n".join(lines)


def render_html(
    df,
    title: str,
    notes: str,
    sort_by: str | list[str] | None = None,
    descending: bool = False,
) -> str:
    """Render dataframe-like rows as deterministic HTML."""
    rows = _sorted_rows(_df_records(df), sort_by=sort_by, descending=descending)
    if not rows:
        return (
            "<!doctype html>\n"
            "<html><head><meta charset=\"utf-8\"><title>"
            + escape(title)
            + "</title></head><body>"
            + f"<h1>{escape(title)}</h1><p>{escape(notes)}</p><p><em>No rows</em></p>"
            + f"<p>Data freshness / source: {escape(_DETERMINISTIC_SOURCE_FOOTER)}</p>"
            + "</body></html>\n"
        )

    columns = list(rows[0].keys())
    lines = [
        "<!doctype html>",
        "<html>",
        "<head>",
        "<meta charset=\"utf-8\">",
        f"<title>{escape(title)}</title>",
        "<style>",
        "body { font-family: sans-serif; margin: 24px; }",
        "table { border-collapse: collapse; width: 100%; }",
        "th, td { border: 1px solid #ddd; padding: 6px 8px; text-align: left; }",
        "th { background: #f5f5f5; }",
        "</style>",
        "</head>",
        "<body>",
        f"<h1>{escape(title)}</h1>",
        f"<p>{escape(notes)}</p>",
        "<table>",
        "<thead><tr>" + "".join(f"<th>{escape(str(c))}</th>" for c in columns) + "</tr></thead>",
        "<tbody>",
    ]
    for row in rows:
        lines.append(
            "<tr>"
            + "".join(f"<td>{escape(_format_value(row.get(col, '')))}</td>" for col in columns)
            + "</tr>"
        )
    lines.extend(
        [
            "</tbody>",
            "</table>",
            f"<p>Data freshness / source: {escape(_DETERMINISTIC_SOURCE_FOOTER)}</p>",
            "</body>",
            "</html>",
            "",
        ]
    )
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
    sums: dict[int, float] = {}
    for row in rows:
        y = int(row["year"])
        sums[y] = sums.get(y, 0.0) + float(row.get("gross_sales", 0.0))
    if y0 in sums and y1 in sums:
        d = sums[y1] - sums[y0]
        return f"Comparison {y0} -> {y1}: gross_sales delta is {d:.2f}."
    return ""


def _build_registry(normalized_root: Path | None = None) -> ReportRegistry:
    registry = ReportRegistry()
    registry.register("electra.sales_summary", lambda years: run_sales_summary(years, normalized_root=normalized_root))
    registry.register("electra.sales_by_agency", lambda years: run_sales_by_agency(years, normalized_root=normalized_root))
    registry.register("electra.sales_by_month", lambda years: run_sales_by_month(years, normalized_root=normalized_root))
    registry.register(
        "electra.top_agencies",
        lambda years: run_top_agencies(years, top_n=5, normalized_root=normalized_root),
    )
    registry.register("electra.direct_share", lambda years: run_direct_share(years, normalized_root=normalized_root))
    return registry


def answer_question(text: str, normalized_root: Path | None = None, output_format: str = "markdown") -> str:
    """
    Parse question -> execute report -> render deterministic answer.
    """

    spec = parse_electra_query(text)
    if spec.source == "reconcile":
        from ai_deney.reports.reconcile_reports import answer_from_spec

        return answer_from_spec(spec, normalized_root=normalized_root, output_format=output_format)
    if spec.source == "mapping":
        from ai_deney.reports.mapping_reports import answer_from_spec

        return answer_from_spec(spec, normalized_root=normalized_root, output_format=output_format)

    ensure_normalized_data(spec.years, reports=[spec.report], normalized_root=normalized_root)
    registry = _build_registry(normalized_root=normalized_root)
    executor = registry.get(spec.registry_key)
    df = executor(spec.years)
    rows = _df_records(df)

    years_label = ", ".join(str(y) for y in spec.years)
    key = spec.analysis or spec.report
    title_map = {
        "sales_summary": f"Sales Summary ({years_label})",
        "sales_by_agency": f"Sales By Agency ({years_label})",
        "sales_by_month": f"Sales By Month ({years_label})",
        "top_agencies": f"Top Agencies ({years_label})",
        "direct_share": f"Direct vs Agency Share ({years_label})",
    }
    notes_map = {
        "sales_summary": f"Sales summary totals for years: {years_label}.",
        "sales_by_agency": f"Sales categorized by agencies for years: {years_label}.",
        "sales_by_month": f"Monthly sales totals for years: {years_label}.",
        "top_agencies": f"Top agencies by gross sales for years: {years_label}.",
        "direct_share": f"Direct channel share versus agency channels for years: {years_label}.",
    }
    title = title_map[key]
    notes = notes_map[key]

    if spec.compare:
        comp = _comparison_note(spec.years, rows, spec.report)
        if comp:
            notes = f"{notes} {comp}"

    sort_by: str | list[str] | None = None
    if key == "sales_summary":
        sort_by = ["year"]
    elif key == "sales_by_agency":
        sort_by = ["year", "agency_id"]
    elif key == "sales_by_month":
        sort_by = ["year", "month"]
    elif key == "top_agencies":
        sort_by = ["year", "rank"]
    elif key == "direct_share":
        sort_by = ["year"]

    if output_format == "markdown":
        return render_markdown(df, title=title, notes=notes, sort_by=sort_by, descending=False)
    if output_format == "html":
        return render_html(df, title=title, notes=notes, sort_by=sort_by, descending=False)
    raise ValueError(f"unsupported output_format: {output_format}")
