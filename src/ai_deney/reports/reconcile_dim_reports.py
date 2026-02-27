"""Dimension-aware reconciliation reports for Electra vs HotelRunner."""

from __future__ import annotations

from html import escape
from pathlib import Path

from ai_deney.intent.query_spec import QuerySpec
from ai_deney.reconcile.electra_vs_hotelrunner import (
    detect_anomalies_daily_by_dim,
    detect_anomalies_monthly_by_dim,
    reconcile_by_dim_daily,
    reconcile_by_dim_monthly,
)
from ai_deney.reports.reconcile_reports import ensure_normalized_data
from ai_deney.reports.registry import ReportRegistry

_DETERMINISTIC_SOURCE_FOOTER = "Source: Electra + HotelRunner mock fixtures; Generated: deterministic run."


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _default_normalized_root() -> Path:
    return _repo_root() / "data" / "normalized"


def _df_records(df) -> list[dict]:
    if hasattr(df, "to_dict"):
        return [dict(r) for r in df.to_dict("records")]
    raise TypeError("unsupported dataframe-like object")


def _format_value(value) -> str:
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def run_reconcile_daily_by_agency(years: list[int], normalized_root: Path | None = None):
    normalized = (normalized_root or _default_normalized_root()).resolve()
    return reconcile_by_dim_daily(
        years=years,
        dim="agency",
        normalized_root_electra=normalized,
        normalized_root_hr=normalized,
    )


def run_reconcile_monthly_by_agency(years: list[int], normalized_root: Path | None = None):
    normalized = (normalized_root or _default_normalized_root()).resolve()
    return reconcile_by_dim_monthly(
        years=years,
        dim="agency",
        normalized_root_electra=normalized,
        normalized_root_hr=normalized,
    )


def run_reconcile_anomalies_agency(years: list[int], normalized_root: Path | None = None):
    normalized = (normalized_root or _default_normalized_root()).resolve()
    return detect_anomalies_daily_by_dim(
        years=years,
        dim="agency",
        normalized_root_electra=normalized,
        normalized_root_hr=normalized,
    )


def _summary_values(reconcile_rows: list[dict]) -> dict:
    mismatches = [r for r in reconcile_rows if str(r.get("status")) == "MISMATCH"]
    return {
        "row_count": len(reconcile_rows),
        "mismatch_count": len(mismatches),
        "total_abs_mismatch": round(sum(abs(float(r.get("delta", 0.0))) for r in mismatches), 2),
    }


def _top_mismatch_contributors(reconcile_rows: list[dict], limit: int = 5) -> list[dict]:
    by_dim: dict[str, float] = {}
    for row in reconcile_rows:
        dim_value = str(row.get("dim_value", ""))
        by_dim[dim_value] = by_dim.get(dim_value, 0.0) + abs(float(row.get("delta", 0.0)))
    out = [
        {"dim_value": dim_value, "abs_mismatch_total": round(total, 2)}
        for dim_value, total in by_dim.items()
        if total > 0
    ]
    out.sort(key=lambda r: (-float(r["abs_mismatch_total"]), str(r["dim_value"])))
    return out[:limit]


def _top_anomalies(anomaly_rows: list[dict], limit: int = 10) -> list[dict]:
    rows = [dict(r) for r in anomaly_rows]
    rows.sort(
        key=lambda r: (
            -float(r.get("severity_score", 0.0)),
            str(r.get("period", "")),
            str(r.get("dim_value", "")),
            str(r.get("anomaly_type", "")),
        )
    )
    return rows[:limit]


def _render_table_markdown(rows: list[dict]) -> list[str]:
    if not rows:
        return ["_No rows_"]
    cols = list(rows[0].keys())
    out = ["| " + " | ".join(cols) + " |", "| " + " | ".join(["---"] * len(cols)) + " |"]
    for row in rows:
        out.append("| " + " | ".join(_format_value(row.get(c, "")) for c in cols) + " |")
    return out


def _render_table_html(rows: list[dict]) -> list[str]:
    if not rows:
        return ["<p><em>No rows</em></p>"]
    cols = list(rows[0].keys())
    out = [
        "<table>",
        "<thead><tr>" + "".join(f"<th>{escape(str(c))}</th>" for c in cols) + "</tr></thead>",
        "<tbody>",
    ]
    for row in rows:
        out.append("<tr>" + "".join(f"<td>{escape(_format_value(row.get(c, '')))}</td>" for c in cols) + "</tr>")
    out.extend(["</tbody>", "</table>"])
    return out


def render_markdown(
    main_rows: list[dict],
    reconcile_rows: list[dict],
    anomaly_rows: list[dict],
    title: str,
    notes: str,
) -> str:
    summary = _summary_values(reconcile_rows)
    top_mismatch = _top_mismatch_contributors(reconcile_rows, limit=5)
    top_anomalies = _top_anomalies(anomaly_rows, limit=10)

    lines = [f"# {title}", "", "## Summary"]
    lines.append(f"- row_count: {summary['row_count']}")
    lines.append(f"- mismatch_count: {summary['mismatch_count']}")
    lines.append(f"- total_abs_mismatch: {summary['total_abs_mismatch']:.2f}")
    lines.extend(["", "## Top mismatch contributors"])
    lines.extend(_render_table_markdown(top_mismatch))
    lines.extend(["", "## Top anomalies"])
    lines.extend(_render_table_markdown(top_anomalies))
    lines.extend(["", notes, "", "## Data"])
    lines.extend(_render_table_markdown(main_rows))
    lines.extend(["", f"Data freshness / source: {_DETERMINISTIC_SOURCE_FOOTER}", ""])
    return "\n".join(lines)


def render_html(
    main_rows: list[dict],
    reconcile_rows: list[dict],
    anomaly_rows: list[dict],
    title: str,
    notes: str,
) -> str:
    summary = _summary_values(reconcile_rows)
    top_mismatch = _top_mismatch_contributors(reconcile_rows, limit=5)
    top_anomalies = _top_anomalies(anomaly_rows, limit=10)
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
        f"<li>row_count: {int(summary['row_count'])}</li>",
        f"<li>mismatch_count: {int(summary['mismatch_count'])}</li>",
        f"<li>total_abs_mismatch: {float(summary['total_abs_mismatch']):.2f}</li>",
        "</ul>",
        "<h2>Top mismatch contributors</h2>",
    ]
    lines.extend(_render_table_html(top_mismatch))
    lines.extend(["<h2>Top anomalies</h2>"])
    lines.extend(_render_table_html(top_anomalies))
    lines.extend([f"<p>{escape(notes)}</p>", "<h2>Data</h2>"])
    lines.extend(_render_table_html(main_rows))
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
    registry.register(
        "reconcile.daily_by_agency",
        lambda years: run_reconcile_daily_by_agency(years, normalized_root=normalized_root),
    )
    registry.register(
        "reconcile.monthly_by_agency",
        lambda years: run_reconcile_monthly_by_agency(years, normalized_root=normalized_root),
    )
    registry.register(
        "reconcile.anomalies_agency",
        lambda years: run_reconcile_anomalies_agency(years, normalized_root=normalized_root),
    )
    return registry


def answer_from_spec(spec: QuerySpec, normalized_root: Path | None = None, output_format: str = "markdown") -> str:
    if spec.source != "reconcile" or spec.analysis not in {
        "reconcile_daily_by_agency",
        "reconcile_monthly_by_agency",
        "reconcile_anomalies_agency",
    }:
        raise ValueError("spec is not a dimension reconciliation query")

    ensure_normalized_data(spec.years, normalized_root=normalized_root)
    registry = _build_registry(normalized_root=normalized_root)
    normalized = (normalized_root or _default_normalized_root()).resolve()
    years_label = ", ".join(str(y) for y in spec.years)

    if spec.analysis == "reconcile_monthly_by_agency":
        reconcile_df = registry.get("reconcile.monthly_by_agency")(spec.years)
        anomaly_df = detect_anomalies_monthly_by_dim(
            years=spec.years,
            dim="agency",
            normalized_root_electra=normalized,
            normalized_root_hr=normalized,
        )
        main_rows = sorted(_df_records(reconcile_df), key=lambda r: (int(r["year"]), str(r["month"]), str(r["dim_value"])))
        title = f"Electra vs HotelRunner Monthly Reconciliation by Agency ({years_label})"
        notes = (
            f"Monthly reconciliation by agency for years: {years_label}. "
            "Status is MATCH when abs(delta) <= 1.00. "
            "Dim uses canonical mapping layer v2."
        )
    elif spec.analysis == "reconcile_anomalies_agency":
        reconcile_df = registry.get("reconcile.daily_by_agency")(spec.years)
        anomaly_df = registry.get("reconcile.anomalies_agency")(spec.years)
        main_rows = sorted(
            _df_records(anomaly_df),
            key=lambda r: (-float(r.get("severity_score", 0.0)), str(r.get("period", "")), str(r.get("dim_value", ""))),
        )
        title = f"Electra vs HotelRunner Agency Anomalies ({years_label})"
        notes = (
            f"Deterministic anomaly scan by agency for years: {years_label}. "
            "Includes spike/drop (>20%), new agencies, and top mismatch contributors. "
            "Dim uses canonical mapping layer v2."
        )
    else:
        reconcile_df = registry.get("reconcile.daily_by_agency")(spec.years)
        anomaly_df = detect_anomalies_daily_by_dim(
            years=spec.years,
            dim="agency",
            normalized_root_electra=normalized,
            normalized_root_hr=normalized,
        )
        main_rows = sorted(_df_records(reconcile_df), key=lambda r: (int(r["year"]), str(r["date"]), str(r["dim_value"])))
        title = f"Electra vs HotelRunner Daily Reconciliation by Agency ({years_label})"
        notes = (
            f"Daily reconciliation by agency for years: {years_label}. "
            "Status is MATCH when abs(delta) <= 1.00. "
            "Dim uses canonical mapping layer v2."
        )

    reconcile_rows = _df_records(reconcile_df)
    anomaly_rows = _df_records(anomaly_df)
    if output_format == "markdown":
        return render_markdown(
            main_rows=main_rows,
            reconcile_rows=reconcile_rows,
            anomaly_rows=anomaly_rows,
            title=title,
            notes=notes,
        )
    if output_format == "html":
        return render_html(
            main_rows=main_rows,
            reconcile_rows=reconcile_rows,
            anomaly_rows=anomaly_rows,
            title=title,
            notes=notes,
        )
    raise ValueError(f"unsupported output_format: {output_format}")
