"""Electra vs HotelRunner reconciliation executors and deterministic rendering."""

from __future__ import annotations

import csv
from collections import Counter
from html import escape
from pathlib import Path

from ai_deney.connectors.electra_mock import ElectraMockConnector
from ai_deney.connectors.hotelrunner_mock import HotelRunnerMockConnector
from ai_deney.intent.electra_intent import parse_electra_query
from ai_deney.intent.query_spec import QuerySpec
from ai_deney.parsing.electra_sales import TOTAL_AGENCY_ID, normalize_report_files as normalize_electra_report_files
from ai_deney.parsing.hotelrunner_sales import normalize_report_files as normalize_hotelrunner_report_files
from ai_deney.reconcile.electra_vs_hotelrunner import compute_year_rollups, reconcile_daily, reconcile_monthly
from ai_deney.reports.registry import ReportRegistry

_DETERMINISTIC_SOURCE_FOOTER = "Source: Electra + HotelRunner mock fixtures; Generated: deterministic run."
_HOW_TO_READ_ITEMS = [
    ("ROUNDING", "minor rounding differences (<= $1)"),
    ("TIMING", "same money posted on adjacent days"),
    ("FEE", "delta consistent with ~3% processing fee"),
    ("UNKNOWN", "needs review; check refunds, manual adjustments, or missing postings"),
]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _default_normalized_root() -> Path:
    return _repo_root() / "data" / "normalized"


def _default_raw_root_electra() -> Path:
    return _repo_root() / "data" / "raw" / "electra_mock"


def _default_raw_root_hotelrunner() -> Path:
    return _repo_root() / "data" / "raw" / "hotelrunner_mock"


def _assert_within_repo(path: Path, repo: Path) -> None:
    try:
        path.resolve().relative_to(repo.resolve())
    except Exception as exc:
        raise ValueError(f"path escapes repo root: {path}") from exc


def _electra_year_data_flags(year: int, normalized_root: Path) -> tuple[bool, bool]:
    path = normalized_root / f"electra_sales_{int(year)}.csv"
    if not path.exists():
        return False, False

    has_summary = False
    has_agency = False
    with path.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            agency_id = str(row.get("agency_id") or "").strip()
            if agency_id == TOTAL_AGENCY_ID:
                has_summary = True
            elif agency_id:
                has_agency = True
            if has_summary and has_agency:
                break
    return has_summary, has_agency


def _hotelrunner_year_exists(year: int, normalized_root: Path) -> bool:
    return (normalized_root / f"hotelrunner_sales_{int(year)}.csv").exists()


def _df_records(df) -> list[dict]:
    if hasattr(df, "to_dict"):
        return df.to_dict("records")
    raise TypeError("unsupported dataframe-like object")


def ensure_normalized_data(
    years: list[int],
    normalized_root: Path | None = None,
    raw_root_electra: Path | None = None,
    raw_root_hotelrunner: Path | None = None,
) -> None:
    """Ensure normalized Electra + HotelRunner data exists for requested years."""
    repo = _repo_root().resolve()
    normalized = (normalized_root or _default_normalized_root()).resolve()
    raw_electra = (raw_root_electra or _default_raw_root_electra()).resolve()
    raw_hotelrunner = (raw_root_hotelrunner or _default_raw_root_hotelrunner()).resolve()
    for path in (normalized, raw_electra, raw_hotelrunner):
        _assert_within_repo(path, repo)

    years_i = sorted({int(y) for y in years})
    missing_electra_summary_years: list[int] = []
    missing_electra_agency_years: list[int] = []
    missing_hotelrunner_years: list[int] = []

    for year in years_i:
        has_summary, has_agency = _electra_year_data_flags(year, normalized)
        if not has_summary:
            missing_electra_summary_years.append(year)
        if not has_agency:
            missing_electra_agency_years.append(year)
        if not _hotelrunner_year_exists(year, normalized):
            missing_hotelrunner_years.append(year)

    if missing_electra_summary_years or missing_electra_agency_years:
        electra_conn = ElectraMockConnector(repo_root=repo, raw_root=raw_electra)
        if missing_electra_summary_years:
            electra_summary_paths = electra_conn.fetch_report("sales_summary", {"years": missing_electra_summary_years})
            normalize_electra_report_files(electra_summary_paths, report_type="sales_summary", output_root=normalized)
        if missing_electra_agency_years:
            electra_agency_paths = electra_conn.fetch_report("sales_by_agency", {"years": missing_electra_agency_years})
            normalize_electra_report_files(electra_agency_paths, report_type="sales_by_agency", output_root=normalized)

    if missing_hotelrunner_years:
        hotelrunner_conn = HotelRunnerMockConnector(repo_root=repo, raw_root=raw_hotelrunner)
        hotelrunner_paths = hotelrunner_conn.fetch_report("daily_sales", {"years": missing_hotelrunner_years})
        normalize_hotelrunner_report_files(hotelrunner_paths, output_root=normalized)


def run_reconcile_daily(years: list[int], normalized_root: Path | None = None):
    normalized = (normalized_root or _default_normalized_root()).resolve()
    return reconcile_daily(
        years,
        normalized_root_electra=normalized,
        normalized_root_hr=normalized,
    )


def run_reconcile_monthly(years: list[int], normalized_root: Path | None = None):
    normalized = (normalized_root or _default_normalized_root()).resolve()
    return reconcile_monthly(
        years,
        normalized_root_electra=normalized,
        normalized_root_hr=normalized,
    )


def _format_value(value) -> str:
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def _sorted_rows(rows: list[dict], sort_by: str | list[str] | None = None, descending: bool = False) -> list[dict]:
    if not rows or not sort_by:
        return rows
    keys = [sort_by] if isinstance(sort_by, str) else list(sort_by)
    return sorted(rows, key=lambda r: tuple(r.get(k) for k in keys), reverse=descending)


def _format_top_reasons(rows: list[dict], limit: int = 3) -> str:
    if not rows or "reason_code" not in rows[0]:
        return "n/a"
    mismatches = [r for r in rows if str(r.get("status")) == "MISMATCH"]
    if not mismatches:
        return "none"
    counts = Counter(str(r.get("reason_code") or "UNKNOWN") for r in mismatches)
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return ", ".join(f"{code}={count}" for code, count in ordered[:limit])


def _format_year_rollups(rollups: list[dict]) -> str:
    if not rollups:
        return "none"
    parts: list[str] = []
    for row in sorted(rollups, key=lambda r: int(r["year"])):
        parts.append(
            f"{int(row['year'])}: MATCH={int(row['match_count'])}, "
            f"MISMATCH={int(row['mismatch_count'])}, "
            f"ABS_MISMATCH={float(row['mismatch_abs_total']):.2f}"
        )
    return "; ".join(parts)


def _summary_values(rows: list[dict]) -> dict:
    mismatches = [r for r in rows if str(r.get("status")) == "MISMATCH"]
    rollups = compute_year_rollups(rows)
    return {
        "mismatched_days": len(mismatches),
        "top_reason_codes": _format_top_reasons(rows, limit=3),
        "total_mismatch_amount": round(sum(abs(float(r.get("delta", 0.0))) for r in mismatches), 2),
        "year_rollups": rollups,
        "year_rollups_text": _format_year_rollups(rollups),
    }


def _should_render_top_mismatch_days(rows: list[dict]) -> bool:
    if not rows:
        return False
    cols = set(rows[0].keys())
    required = {"date", "delta", "reason_code", "status"}
    return required.issubset(cols)


def _top_mismatch_days(rows: list[dict], limit: int = 5) -> list[dict]:
    mismatches = [r for r in rows if str(r.get("status")) == "MISMATCH"]
    ordered = sorted(
        mismatches,
        key=lambda r: (
            -abs(float(r.get("delta", 0.0))),
            str(r.get("date", "")),
            str(r.get("reason_code") or "UNKNOWN"),
        ),
    )
    top = []
    for row in ordered[:limit]:
        top.append(
            {
                "date": str(row.get("date", "")),
                "delta": round(float(row.get("delta", 0.0)), 2),
                "reason_code": str(row.get("reason_code") or "UNKNOWN"),
            }
        )
    return top


def render_markdown(
    df,
    title: str,
    notes: str,
    sort_by: str | list[str] | None = None,
    descending: bool = False,
) -> str:
    """Render dataframe-like rows as markdown with deterministic footer."""
    rows = _sorted_rows(_df_records(df), sort_by=sort_by, descending=descending)
    summary = _summary_values(rows)
    show_top_mismatch_days = _should_render_top_mismatch_days(rows)
    lines = [f"# {title}", "", "## Summary"]
    lines.append(f"- mismatched_days: {summary['mismatched_days']}")
    lines.append(f"- top_reason_codes: {summary['top_reason_codes']}")
    lines.append(f"- total_mismatch_amount: {summary['total_mismatch_amount']:.2f}")
    lines.append(f"- year_rollups: {summary['year_rollups_text']}")
    lines.extend(["", "## How to read this"])
    for code, description in _HOW_TO_READ_ITEMS:
        lines.append(f"- {code}: {description}")
    if show_top_mismatch_days:
        lines.extend(["", "## Top mismatch days"])
        top_rows = _top_mismatch_days(rows, limit=5)
        if not top_rows:
            lines.append("- none")
        else:
            lines.append("| date | delta | reason_code |")
            lines.append("| --- | --- | --- |")
            for row in top_rows:
                lines.append(
                    "| "
                    + " | ".join(
                        [
                            str(row.get("date", "")),
                            _format_value(row.get("delta", 0.0)),
                            str(row.get("reason_code", "")),
                        ]
                    )
                    + " |"
                )
    lines.extend(["", notes, ""])
    if not rows:
        lines.append("_No rows_")
        lines.append("")
        lines.append(f"Data freshness / source: {_DETERMINISTIC_SOURCE_FOOTER}")
        lines.append("")
        return "\n".join(lines)

    columns = list(rows[0].keys())
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
    summary = _summary_values(rows)
    show_top_mismatch_days = _should_render_top_mismatch_days(rows)
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
        "<h2>Summary</h2>",
        "<ul>",
        f"<li>mismatched_days: {int(summary['mismatched_days'])}</li>",
        f"<li>top_reason_codes: {escape(str(summary['top_reason_codes']))}</li>",
        f"<li>total_mismatch_amount: {float(summary['total_mismatch_amount']):.2f}</li>",
        f"<li>year_rollups: {escape(str(summary['year_rollups_text']))}</li>",
        "</ul>",
        "<h2>How to read this</h2>",
        "<ul>",
    ]
    for code, description in _HOW_TO_READ_ITEMS:
        lines.append(f"<li><strong>{escape(code)}</strong>: {escape(description)}</li>")
    lines.extend(
        [
            "</ul>",
        ]
    )
    if show_top_mismatch_days:
        top_rows = _top_mismatch_days(rows, limit=5)
        lines.extend(
            [
                "<h2>Top mismatch days</h2>",
            ]
        )
        if not top_rows:
            lines.append("<p>none</p>")
        else:
            lines.extend(
                [
                    "<table>",
                    "<thead><tr><th>date</th><th>delta</th><th>reason_code</th></tr></thead>",
                    "<tbody>",
                ]
            )
            for row in top_rows:
                lines.append(
                    "<tr>"
                    + f"<td>{escape(str(row.get('date', '')))}</td>"
                    + f"<td>{escape(_format_value(row.get('delta', 0.0)))}</td>"
                    + f"<td>{escape(str(row.get('reason_code', '')))}</td>"
                    + "</tr>"
                )
            lines.extend(["</tbody>", "</table>"])
    lines.extend(
        [
            f"<p>{escape(notes)}</p>",
        ]
    )
    if not rows:
        lines.append("<p><em>No rows</em></p>")
    else:
        columns = list(rows[0].keys())
        lines.extend(
            [
                "<table>",
                "<thead><tr>" + "".join(f"<th>{escape(str(c))}</th>" for c in columns) + "</tr></thead>",
                "<tbody>",
            ]
        )
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
            ]
        )
    lines.extend(
        [
            f"<p>Data freshness / source: {escape(_DETERMINISTIC_SOURCE_FOOTER)}</p>",
            "</body>",
            "</html>",
            "",
        ]
    )
    return "\n".join(lines)


def _build_registry(normalized_root: Path | None = None) -> ReportRegistry:
    registry = ReportRegistry()
    registry.register("reconcile.daily", lambda years: run_reconcile_daily(years, normalized_root=normalized_root))
    registry.register("reconcile.monthly", lambda years: run_reconcile_monthly(years, normalized_root=normalized_root))
    return registry


def answer_from_spec(spec: QuerySpec, normalized_root: Path | None = None, output_format: str = "markdown") -> str:
    if spec.source != "reconcile":
        raise ValueError("spec is not a reconciliation query")
    if spec.analysis in {
        "reconcile_daily_by_agency",
        "reconcile_monthly_by_agency",
        "reconcile_anomalies_agency",
    }:
        from ai_deney.reports.reconcile_dim_reports import answer_from_spec as answer_dim_from_spec

        return answer_dim_from_spec(spec, normalized_root=normalized_root, output_format=output_format)
    if spec.analysis not in {"reconcile_daily", "reconcile_monthly"}:
        raise ValueError("spec is not a reconciliation query")
    ensure_normalized_data(spec.years, normalized_root=normalized_root)
    registry = _build_registry(normalized_root=normalized_root)
    executor = registry.get(spec.registry_key)
    df = executor(spec.years)

    years_label = ", ".join(str(y) for y in spec.years)
    if spec.analysis == "reconcile_monthly":
        title = f"Electra vs HotelRunner Monthly Reconciliation ({years_label})"
        notes = (
            f"Monthly gross sales comparison for years: {years_label}. "
            "Status is MATCH when abs(delta) <= 1.00; otherwise MISMATCH."
        )
        sort_by: str | list[str] | None = ["year", "month"]
    else:
        title = f"Electra vs HotelRunner Daily Reconciliation ({years_label})"
        notes = (
            f"Daily gross sales comparison for years: {years_label}. "
            "Status is MATCH when abs(delta) <= 1.00; otherwise MISMATCH. "
            "Reason priority: ROUNDING, TIMING (offsetting adjacent deltas), FEE (~3%), UNKNOWN."
        )
        sort_by = ["year", "date"]

    if output_format == "markdown":
        return render_markdown(df, title=title, notes=notes, sort_by=sort_by, descending=False)
    if output_format == "html":
        return render_html(df, title=title, notes=notes, sort_by=sort_by, descending=False)
    raise ValueError(f"unsupported output_format: {output_format}")


def answer_question(text: str, normalized_root: Path | None = None, output_format: str = "markdown") -> str:
    """Parse reconciliation question text and render deterministic output."""
    spec = parse_electra_query(text)
    return answer_from_spec(spec, normalized_root=normalized_root, output_format=output_format)
