"""Deterministic toy portal sales reports from natural-language questions."""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Literal

from ai_deney.intent.toy_intent import ToyQuerySpec, parse_toy_query
from tools.toy_hotel_portal.db import default_db_path

OutputFormat = Literal["markdown", "html"]
_SOURCE_FOOTER = "Source: toy_portal SQLite data; generated deterministically from query."


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _resolve_db_path(db_path: Path | None) -> Path:
    if db_path is not None:
        return db_path.resolve()
    return default_db_path(_repo_root()).resolve()


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _format_money(value: float) -> str:
    return f"{float(value):.2f}"


def _month_label(year: int, month: int) -> str:
    return datetime(year=year, month=month, day=1).strftime("%B %Y")


def _run_aggregates(spec: ToyQuerySpec, db_path: Path) -> dict[str, object]:
    start, end = spec.resolved_range()
    params = (start.isoformat(), end.isoformat())

    with _connect(db_path) as conn:
        totals_row = conn.execute(
            """
            SELECT
                COALESCE(SUM(total_paid), 0.0) AS total_sales,
                COUNT(*) AS reservation_count
            FROM reservations
            WHERE check_in >= ? AND check_in <= ?
            """,
            params,
        ).fetchone()

        total_sales = float(totals_row["total_sales"]) if totals_row is not None else 0.0
        reservation_count = int(totals_row["reservation_count"]) if totals_row is not None else 0

        if spec.group_by == "source_channel":
            rows = conn.execute(
                """
                SELECT
                    source_channel AS source_channel,
                    COUNT(*) AS reservations,
                    ROUND(SUM(total_paid), 2) AS total_sales
                FROM reservations
                WHERE check_in >= ? AND check_in <= ?
                GROUP BY source_channel
                ORDER BY total_sales DESC, source_channel ASC
                """,
                params,
            ).fetchall()
            columns = ["source_channel", "reservations", "total_sales"]
            detail_rows = [
                {
                    "source_channel": str(row["source_channel"] or ""),
                    "reservations": int(row["reservations"] or 0),
                    "total_sales": float(row["total_sales"] or 0.0),
                }
                for row in rows
            ]
        elif spec.group_by == "agency":
            rows = conn.execute(
                """
                SELECT
                    CASE
                        WHEN TRIM(agency_name) != '' THEN agency_name
                        WHEN TRIM(agency_id) != '' THEN agency_id
                        ELSE '(none)'
                    END AS agency,
                    COUNT(*) AS reservations,
                    ROUND(SUM(total_paid), 2) AS total_sales
                FROM reservations
                WHERE check_in >= ? AND check_in <= ?
                GROUP BY agency
                ORDER BY total_sales DESC, agency ASC
                """,
                params,
            ).fetchall()
            columns = ["agency", "reservations", "total_sales"]
            detail_rows = [
                {
                    "agency": str(row["agency"] or ""),
                    "reservations": int(row["reservations"] or 0),
                    "total_sales": float(row["total_sales"] or 0.0),
                }
                for row in rows
            ]
        else:
            rows = conn.execute(
                """
                SELECT
                    check_in AS day,
                    COUNT(*) AS reservations,
                    ROUND(SUM(total_paid), 2) AS total_sales
                FROM reservations
                WHERE check_in >= ? AND check_in <= ?
                GROUP BY check_in
                ORDER BY check_in ASC
                """,
                params,
            ).fetchall()
            columns = ["day", "reservations", "total_sales"]
            detail_rows = [
                {
                    "day": str(row["day"] or ""),
                    "reservations": int(row["reservations"] or 0),
                    "total_sales": float(row["total_sales"] or 0.0),
                }
                for row in rows
            ]

    if spec.query_type == "sales_month" and spec.year and spec.month:
        title = f"Toy Portal Sales Report ({_month_label(spec.year, spec.month)})"
    else:
        title = f"Toy Portal Sales Report ({start.isoformat()} to {end.isoformat()})"

    notes = (
        "Sales definition: SUM(total_paid) for reservations whose check_in date falls within "
        "the selected date range."
    )
    if spec.redact_pii:
        notes += " Redaction requested; this report is aggregated and contains no guest PII."

    return {
        "title": title,
        "notes": notes,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "group_by": spec.group_by or "day",
        "total_sales": round(total_sales, 2),
        "reservation_count": reservation_count,
        "columns": columns,
        "rows": detail_rows,
    }


def _render_markdown(report: dict[str, object]) -> str:
    lines = [
        f"# {report['title']}",
        "",
        str(report["notes"]),
        "",
        f"- date_range: {report['start']}..{report['end']}",
        f"- group_by: {report['group_by']}",
        f"- reservation_count: {int(report['reservation_count'])}",
        f"- total_sales: {_format_money(float(report['total_sales']))}",
        "",
    ]

    rows = list(report.get("rows") or [])
    columns = list(report.get("columns") or [])
    if rows and columns:
        lines.append("| " + " | ".join(columns) + " |")
        lines.append("| " + " | ".join(["---"] * len(columns)) + " |")
        for row in rows:
            cells: list[str] = []
            for key in columns:
                value = row.get(key, "")
                if key == "total_sales":
                    cells.append(_format_money(float(value)))
                else:
                    cells.append(str(value))
            lines.append("| " + " | ".join(cells) + " |")
        lines.append("")
    else:
        lines.append("_No rows_")
        lines.append("")

    lines.append(f"Data freshness / source: {_SOURCE_FOOTER}")
    lines.append("")
    return "\n".join(lines)


def _render_html(report: dict[str, object]) -> str:
    rows = list(report.get("rows") or [])
    columns = list(report.get("columns") or [])
    lines = [
        "<!doctype html>",
        "<html>",
        "<head>",
        "<meta charset=\"utf-8\">",
        f"<title>{escape(str(report['title']))}</title>",
        "<style>",
        "body { font-family: sans-serif; margin: 24px; }",
        "table { border-collapse: collapse; width: 100%; }",
        "th, td { border: 1px solid #ddd; padding: 6px 8px; text-align: left; }",
        "th { background: #f5f5f5; }",
        "</style>",
        "</head>",
        "<body>",
        f"<h1>{escape(str(report['title']))}</h1>",
        f"<p>{escape(str(report['notes']))}</p>",
        "<ul>",
        f"<li>date_range: {escape(str(report['start']))}..{escape(str(report['end']))}</li>",
        f"<li>group_by: {escape(str(report['group_by']))}</li>",
        f"<li>reservation_count: {int(report['reservation_count'])}</li>",
        f"<li>total_sales: {escape(_format_money(float(report['total_sales'])))}</li>",
        "</ul>",
    ]

    if rows and columns:
        lines.extend(
            [
                "<table>",
                "<thead><tr>" + "".join(f"<th>{escape(str(c))}</th>" for c in columns) + "</tr></thead>",
                "<tbody>",
            ]
        )
        for row in rows:
            cells: list[str] = []
            for key in columns:
                value = row.get(key, "")
                if key == "total_sales":
                    value = _format_money(float(value))
                cells.append(f"<td>{escape(str(value))}</td>")
            lines.append("<tr>" + "".join(cells) + "</tr>")
        lines.extend(["</tbody>", "</table>"])
    else:
        lines.append("<p><em>No rows</em></p>")

    lines.extend(
        [
            f"<p>Data freshness / source: {escape(_SOURCE_FOOTER)}</p>",
            "</body>",
            "</html>",
            "",
        ]
    )
    return "\n".join(lines)


def render_report(report: dict[str, object], output_format: OutputFormat = "markdown") -> str:
    if output_format == "markdown":
        return _render_markdown(report)
    if output_format == "html":
        return _render_html(report)
    raise ValueError("output_format must be 'markdown' or 'html'")


def answer_with_metadata(
    text: str,
    db_path: Path | None = None,
    output_format: OutputFormat = "markdown",
    redact_pii: bool = False,
) -> dict[str, object]:
    spec = parse_toy_query(text)
    if redact_pii and not spec.redact_pii:
        spec = replace(spec, redact_pii=True)
    db = _resolve_db_path(db_path)
    report_data = _run_aggregates(spec, db)
    rendered = render_report(report_data, output_format=output_format)
    return {
        "report": rendered,
        "spec": spec.to_dict(),
        "metadata": {
            "db_path": str(db),
            "output_format": output_format,
            "query_type": spec.query_type,
            "group_by": spec.group_by,
            "start": report_data["start"],
            "end": report_data["end"],
            "reservation_count": report_data["reservation_count"],
            "total_sales": report_data["total_sales"],
        },
    }


def answer_question(
    text: str,
    db_path: Path | None = None,
    output_format: OutputFormat = "markdown",
    redact_pii: bool = False,
) -> str:
    return str(answer_with_metadata(text, db_path=db_path, output_format=output_format, redact_pii=redact_pii)["report"])
