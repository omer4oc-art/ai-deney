"""Deterministic toy portal reports from validated QuerySpec input."""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import replace
from datetime import date, datetime
from html import escape
from pathlib import Path
from typing import Literal

from ai_deney.intent.toy_intent import (
    QuerySpec,
    ToyLLMRouter,
    parse_toy_query_plan_with_trace,
    resolve_intent_mode,
)
from tools.toy_hotel_portal.db import (
    ROOM_COUNT,
    default_db_path,
    export_rows_in_window,
    get_sales_totals_for_dates,
    occupancy_days,
    occupancy_pct,
    reservations_in_window,
)

OutputFormat = Literal["markdown", "html"]
AskFormat = Literal["md", "html"]
_SOURCE_FOOTER = "Source: toy_portal SQLite data; generated deterministically from QuerySpec."
_RESERVATION_LIST_LIMIT = 200


def _normalize_question_for_trace(text: str) -> str:
    return " ".join(str(text or "").strip().lower().split())


def _sanitize_trace_params(params: dict[str, object]) -> dict[str, object]:
    safe: dict[str, object] = {}
    for key in sorted(params.keys()):
        lowered = str(key).strip().lower()
        if not lowered or lowered == "guest_name" or "guest_name" in lowered:
            continue
        value = params[key]
        if isinstance(value, (str, int, float, bool)) or value is None:
            safe[str(key)] = value
        elif isinstance(value, tuple):
            safe[str(key)] = list(value)
        elif isinstance(value, list):
            safe[str(key)] = list(value)
        else:
            safe[str(key)] = str(value)
    return safe


def _append_query_trace(
    query_trace: list[dict[str, object]] | None,
    *,
    name: str,
    params: dict[str, object],
    row_count: int,
) -> None:
    if query_trace is None:
        return
    query_trace.append(
        {
            "name": str(name),
            "params": _sanitize_trace_params(params),
            "row_count": int(row_count),
        }
    )


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


def _format_guest_name(name: str, redact: bool) -> str:
    if not redact:
        return name
    digest = hashlib.sha256(str(name).encode("utf-8")).hexdigest()[:12]
    return f"REDACTED_{digest}"


def run_sales_day(
    sales_date: str,
    db_path: Path,
    *,
    query_trace: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    day = date.fromisoformat(str(sales_date)).isoformat()
    with _connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT
                COUNT(*) AS reservations,
                ROUND(COALESCE(SUM(total_paid), 0.0), 2) AS total_sales
            FROM reservations
            WHERE check_in = ?
            """,
            (day,),
        ).fetchone()
    reservations = int((row["reservations"] if row is not None else 0) or 0)
    total_sales = float((row["total_sales"] if row is not None else 0.0) or 0.0)
    _append_query_trace(
        query_trace,
        name="sales_day_total",
        params={"date": day},
        row_count=1,
    )
    return {
        "date": day,
        "reservations": reservations,
        "total_sales": round(total_sales, 2),
    }


def _run_sales_day_report(
    spec: QuerySpec,
    db_path: Path,
    *,
    query_trace: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    if not spec.start_date or not spec.end_date or spec.start_date != spec.end_date:
        raise ValueError("sales_day requires start_date == end_date")
    row = run_sales_day(spec.start_date, db_path, query_trace=query_trace)
    return {
        "title": f"Toy Portal Sales Day Total ({row['date']})",
        "notes": "Sales definition: SUM(total_paid) for reservations whose check_in date equals the target day.",
        "report_type": "sales_day",
        "start": str(row["date"]),
        "end": str(row["date"]),
        "group_by": None,
        "reservation_count": int(row["reservations"]),
        "total_sales": float(row["total_sales"]),
        "date_count": 1,
        "totals_by_date_count": 1,
        "columns": ["date", "reservations", "total_sales"],
        "rows": [row],
        "warnings": [],
    }


def execute_query_plan(
    plan: list[QuerySpec] | tuple[QuerySpec, ...],
    *,
    db_path: Path,
    compare: bool = False,
    query_trace: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    if not plan:
        raise ValueError("query plan cannot be empty")

    rows: list[dict[str, object]] = []
    for idx, step in enumerate(plan):
        if step.report_type != "sales_day":
            raise ValueError(f"unsupported plan step at index {idx}: {step.report_type}")
        if not step.start_date or not step.end_date or step.start_date != step.end_date:
            raise ValueError(f"sales_day plan step at index {idx} must have start_date == end_date")
        rows.append(run_sales_day(step.start_date, db_path, query_trace=query_trace))

    analysis_lines: list[str] = []
    if compare and len(rows) >= 2:
        first = rows[0]
        second = rows[-1]
        delta = round(float(second["total_sales"]) - float(first["total_sales"]), 2)
        base = float(first["total_sales"])
        pct_delta = round((delta / base * 100.0), 2) if base != 0 else 0.0
        analysis_lines.append(f"delta_total_sales({second['date']} - {first['date']}): {delta:.2f}")
        analysis_lines.append(f"pct_delta_total_sales: {pct_delta:.2f}%")

    total_sales_sum = round(sum(float(r["total_sales"]) for r in rows), 2)
    start = str(rows[0]["date"])
    end = str(rows[-1]["date"])
    return {
        "title": "Toy Portal Sales Totals by Planned Dates",
        "notes": "Plan execution: deterministic SUM(total_paid) for each explicit check_in date.",
        "report_type": "sales_day_plan",
        "start": start,
        "end": end,
        "group_by": None,
        "compare": bool(compare),
        "executed_count": len(rows),
        "date_count": len(rows),
        "totals_by_date_count": len(rows),
        "reservation_count": sum(int(r["reservations"]) for r in rows),
        "total_sales": total_sales_sum,
        "total_sales_sum": total_sales_sum,
        "analysis_lines": analysis_lines,
        "columns": ["date", "reservations", "total_sales"],
        "rows": rows,
        "warnings": [],
    }


def _run_sales_report(
    spec: QuerySpec,
    db_path: Path,
    *,
    query_trace: list[dict[str, object]] | None = None,
) -> dict[str, object]:
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
        _append_query_trace(
            query_trace,
            name="sales_totals_in_range",
            params={"start_date": params[0], "end_date": params[1]},
            row_count=0 if totals_row is None else 1,
        )

        total_sales = float(totals_row["total_sales"]) if totals_row is not None else 0.0
        reservation_count = int(totals_row["reservation_count"]) if totals_row is not None else 0

        if spec.group_by == "channel":
            rows = conn.execute(
                """
                SELECT
                    source_channel AS channel,
                    COUNT(*) AS reservations,
                    ROUND(SUM(total_paid), 2) AS total_sales
                FROM reservations
                WHERE check_in >= ? AND check_in <= ?
                GROUP BY source_channel
                ORDER BY total_sales DESC, channel ASC
                """,
                params,
            ).fetchall()
            columns = ["channel", "reservations", "total_sales"]
            detail_rows = [
                {
                    "channel": str(row["channel"] or ""),
                    "reservations": int(row["reservations"] or 0),
                    "total_sales": float(row["total_sales"] or 0.0),
                }
                for row in rows
            ]
            _append_query_trace(
                query_trace,
                name="sales_grouped_by_channel",
                params={"start_date": params[0], "end_date": params[1], "group_by": "channel"},
                row_count=len(detail_rows),
            )
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
            _append_query_trace(
                query_trace,
                name="sales_grouped_by_day",
                params={"start_date": params[0], "end_date": params[1], "group_by": "day"},
                row_count=len(detail_rows),
            )

    if spec.report_type == "sales_month" and spec.year and spec.month:
        title = f"Toy Portal Sales Report ({_month_label(spec.year, spec.month)})"
    elif spec.report_type == "sales_by_channel":
        title = f"Toy Portal Sales by Channel ({start.isoformat()} to {end.isoformat()})"
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
        "report_type": spec.report_type,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "group_by": spec.group_by or "day",
        "total_sales": round(total_sales, 2),
        "reservation_count": reservation_count,
        "columns": columns,
        "rows": detail_rows,
    }


def _run_occupancy_report(
    spec: QuerySpec,
    db_path: Path,
    *,
    query_trace: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    start, end = spec.resolved_range()
    days = occupancy_days(db_path, start, end)
    pct = occupancy_pct(days, room_count=ROOM_COUNT)

    rows = [
        {
            "day": str(day["date"]),
            "occupied_rooms": int(day["occupied_rooms"]),
        }
        for day in days
    ]
    _append_query_trace(
        query_trace,
        name="occupancy_days_in_range",
        params={"start_date": start.isoformat(), "end_date": end.isoformat(), "room_count": ROOM_COUNT},
        row_count=len(rows),
    )

    return {
        "title": f"Toy Portal Occupancy Report ({start.isoformat()} to {end.isoformat()})",
        "notes": "Occupancy is based on stay overlap per day (check_in <= day < check_out).",
        "report_type": spec.report_type,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "group_by": "day",
        "room_count": ROOM_COUNT,
        "occupancy_pct": pct,
        "reservation_count": sum(int(day["occupied_rooms"]) for day in rows),
        "columns": ["day", "occupied_rooms"],
        "rows": rows,
    }


def _run_reservations_list_report(
    spec: QuerySpec,
    db_path: Path,
    *,
    query_trace: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    start, end = spec.resolved_range()
    raw_rows = reservations_in_window(db_path, start, end, limit=_RESERVATION_LIST_LIMIT)

    rows: list[dict[str, object]] = []
    for row in raw_rows:
        rows.append(
            {
                "reservation_id": str(row.get("reservation_id") or ""),
                "guest_name": _format_guest_name(str(row.get("guest_name") or ""), spec.redact_pii),
                "check_in": str(row.get("check_in") or ""),
                "check_out": str(row.get("check_out") or ""),
                "room_type": str(row.get("room_type") or ""),
                "source_channel": str(row.get("source_channel") or ""),
            }
        )
    _append_query_trace(
        query_trace,
        name="reservations_in_window",
        params={
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "limit": _RESERVATION_LIST_LIMIT,
            "redact_pii": bool(spec.redact_pii),
        },
        row_count=len(rows),
    )

    return {
        "title": f"Toy Portal Reservations List ({start.isoformat()} to {end.isoformat()})",
        "notes": f"Showing up to {_RESERVATION_LIST_LIMIT} reservations that overlap the selected window.",
        "report_type": spec.report_type,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "group_by": None,
        "reservation_count": len(rows),
        "columns": ["reservation_id", "guest_name", "check_in", "check_out", "room_type", "source_channel"],
        "rows": rows,
    }


def _run_export_reservations_report(
    spec: QuerySpec,
    db_path: Path,
    *,
    query_trace: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    start, end = spec.resolved_range()
    raw_rows = export_rows_in_window(db_path, start, end)

    preview: list[dict[str, object]] = []
    total_sales = 0.0
    for row in raw_rows:
        total_sales += float(row.get("total_paid") or 0.0)
    for row in raw_rows[:20]:
        preview.append(
            {
                "reservation_id": str(row.get("reservation_id") or ""),
                "guest_name": _format_guest_name(str(row.get("guest_name") or ""), spec.redact_pii),
                "check_in": str(row.get("check_in") or ""),
                "check_out": str(row.get("check_out") or ""),
                "total_paid": round(float(row.get("total_paid") or 0.0), 2),
                "currency": str(row.get("currency") or ""),
            }
        )
    _append_query_trace(
        query_trace,
        name="export_rows_in_window",
        params={
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "preview_limit": 20,
            "redact_pii": bool(spec.redact_pii),
        },
        row_count=len(raw_rows),
    )

    redaction_note = "enabled" if spec.redact_pii else "disabled"
    return {
        "title": f"Toy Portal Export Preview ({start.isoformat()} to {end.isoformat()})",
        "notes": "Export query executed deterministically. "
        f"PII redaction is {redaction_note}. Showing first 20 rows only.",
        "report_type": spec.report_type,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "group_by": None,
        "reservation_count": len(raw_rows),
        "total_sales": round(total_sales, 2),
        "columns": ["reservation_id", "guest_name", "check_in", "check_out", "total_paid", "currency"],
        "rows": preview,
    }


def _run_sales_for_dates_report(
    spec: QuerySpec,
    db_path: Path,
    *,
    query_trace: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    dates = list(spec.dates)
    if not dates:
        raise ValueError("sales_for_dates requires at least one date")

    rows = get_sales_totals_for_dates(db_path, dates)
    _append_query_trace(
        query_trace,
        name="sales_totals_for_dates",
        params={"dates": dates, "compare": bool(spec.compare)},
        row_count=len(rows),
    )
    total_sales_sum = round(sum(float(r["total_sales"]) for r in rows), 2)
    start = str(rows[0]["date"])
    end = str(rows[-1]["date"])
    analysis_lines: list[str] = []

    if spec.compare and len(rows) == 2:
        first = rows[0]
        second = rows[1]
        delta = round(float(second["total_sales"]) - float(first["total_sales"]), 2)
        base = float(first["total_sales"])
        pct_delta = (delta / base * 100.0) if base != 0 else 0.0
        analysis_lines.append(
            f"delta_total_sales({second['date']} - {first['date']}): {delta:.2f}"
        )
        analysis_lines.append(f"pct_delta_total_sales: {pct_delta:.2f}%")
    elif spec.compare and len(rows) > 2:
        max_row = max(rows, key=lambda r: float(r["total_sales"]))
        min_row = min(rows, key=lambda r: float(r["total_sales"]))
        sales_range = round(float(max_row["total_sales"]) - float(min_row["total_sales"]), 2)
        analysis_lines.append(f"max_total_sales_date: {max_row['date']} ({float(max_row['total_sales']):.2f})")
        analysis_lines.append(f"min_total_sales_date: {min_row['date']} ({float(min_row['total_sales']):.2f})")
        analysis_lines.append(f"total_sales_range: {sales_range:.2f}")

    return {
        "title": "Toy Portal Sales Totals by Date",
        "notes": "Sales definition: SUM(total_paid) for reservations whose check_in date equals each listed date.",
        "report_type": spec.report_type,
        "start": start,
        "end": end,
        "group_by": None,
        "compare": bool(spec.compare),
        "date_count": len(dates),
        "totals_by_date_count": len(rows),
        "total_sales": total_sales_sum,
        "total_sales_sum": total_sales_sum,
        "analysis_lines": analysis_lines,
        "columns": ["date", "reservations", "total_sales"],
        "rows": rows,
        "warnings": [],
    }


def run_query_spec(
    spec: QuerySpec,
    db_path: Path,
    *,
    query_trace: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    if spec.report_type in {"sales_range", "sales_month", "sales_by_channel"}:
        return _run_sales_report(spec, db_path, query_trace=query_trace)
    if spec.report_type == "sales_day":
        return _run_sales_day_report(spec, db_path, query_trace=query_trace)
    if spec.report_type == "sales_for_dates":
        return _run_sales_for_dates_report(spec, db_path, query_trace=query_trace)
    if spec.report_type == "occupancy_range":
        return _run_occupancy_report(spec, db_path, query_trace=query_trace)
    if spec.report_type == "reservations_list":
        return _run_reservations_list_report(spec, db_path, query_trace=query_trace)
    if spec.report_type == "export_reservations":
        return _run_export_reservations_report(spec, db_path, query_trace=query_trace)
    raise ValueError(f"unsupported report_type: {spec.report_type}")


def _render_markdown(report: dict[str, object]) -> str:
    lines = [
        f"# {report['title']}",
        "",
        str(report["notes"]),
        "",
        f"- report_type: {report['report_type']}",
        f"- date_range: {report['start']}..{report['end']}",
    ]

    if report.get("group_by"):
        lines.append(f"- group_by: {report['group_by']}")
    if report.get("room_count") is not None:
        lines.append(f"- room_count: {int(report['room_count'])}")
    if report.get("occupancy_pct") is not None:
        lines.append(f"- occupancy_pct: {float(report['occupancy_pct']):.2f}")
    if report.get("reservation_count") is not None:
        lines.append(f"- reservation_count: {int(report['reservation_count'])}")
    if report.get("total_sales") is not None:
        lines.append(f"- total_sales: {_format_money(float(report['total_sales']))}")
    if report.get("date_count") is not None:
        lines.append(f"- date_count: {int(report['date_count'])}")
    if report.get("totals_by_date_count") is not None:
        lines.append(f"- totals_by_date_count: {int(report['totals_by_date_count'])}")
    if report.get("compare") is not None:
        lines.append(f"- compare: {bool(report['compare'])}")
    lines.append("")

    rows = list(report.get("rows") or [])
    columns = list(report.get("columns") or [])
    if rows and columns:
        lines.append("| " + " | ".join(columns) + " |")
        lines.append("| " + " | ".join(["---"] * len(columns)) + " |")
        for row in rows:
            cells: list[str] = []
            for key in columns:
                value = row.get(key, "")
                if key == "total_sales" or key == "total_paid":
                    cells.append(_format_money(float(value)))
                else:
                    cells.append(str(value))
            lines.append("| " + " | ".join(cells) + " |")
        lines.append("")
    else:
        lines.append("_No rows_")
        lines.append("")

    for line in list(report.get("analysis_lines") or []):
        lines.append(f"- {str(line)}")
    if list(report.get("analysis_lines") or []):
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
        f"<li>report_type: {escape(str(report['report_type']))}</li>",
        f"<li>date_range: {escape(str(report['start']))}..{escape(str(report['end']))}</li>",
    ]

    if report.get("group_by"):
        lines.append(f"<li>group_by: {escape(str(report['group_by']))}</li>")
    if report.get("room_count") is not None:
        lines.append(f"<li>room_count: {int(report['room_count'])}</li>")
    if report.get("occupancy_pct") is not None:
        lines.append(f"<li>occupancy_pct: {float(report['occupancy_pct']):.2f}</li>")
    if report.get("reservation_count") is not None:
        lines.append(f"<li>reservation_count: {int(report['reservation_count'])}</li>")
    if report.get("total_sales") is not None:
        lines.append(f"<li>total_sales: {escape(_format_money(float(report['total_sales'])))}</li>")
    if report.get("date_count") is not None:
        lines.append(f"<li>date_count: {int(report['date_count'])}</li>")
    if report.get("totals_by_date_count") is not None:
        lines.append(f"<li>totals_by_date_count: {int(report['totals_by_date_count'])}</li>")
    if report.get("compare") is not None:
        lines.append(f"<li>compare: {escape(str(bool(report['compare'])))}</li>")
    for line in list(report.get("analysis_lines") or []):
        lines.append(f"<li>{escape(str(line))}</li>")
    lines.append("</ul>")

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
                if key in {"total_sales", "total_paid"}:
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


def answer_spec_with_metadata(
    spec: QuerySpec,
    *,
    db_path: Path | None = None,
    output_format: OutputFormat | None = None,
    redact_pii: bool = False,
    include_trace: bool = False,
) -> dict[str, object]:
    effective = spec
    if redact_pii and not effective.redact_pii:
        effective = replace(effective, redact_pii=True)
    if output_format is not None:
        out_fmt = "md" if output_format == "markdown" else "html"
        if effective.format != out_fmt:
            effective = replace(effective, format=out_fmt)

    db = _resolve_db_path(db_path)
    query_trace: list[dict[str, object]] | None = [] if include_trace else None
    report_data = run_query_spec(effective, db, query_trace=query_trace)
    final_format: OutputFormat = "markdown" if effective.format == "md" else "html"
    rendered = render_report(report_data, output_format=final_format)
    result: dict[str, object] = {
        "report": rendered,
        "spec": effective.to_dict(),
        "metadata": {
            "db_path": str(db),
            "output_format": final_format,
            "report_type": effective.report_type,
            "group_by": effective.group_by,
            "start": report_data["start"],
            "end": report_data["end"],
            "reservation_count": report_data.get("reservation_count"),
            "total_sales": report_data.get("total_sales"),
            "total_sales_sum": report_data.get("total_sales_sum"),
            "date_count": report_data.get("date_count"),
            "totals_by_date_count": report_data.get("totals_by_date_count"),
            "compare": bool(report_data.get("compare", False)),
            "warnings": list(report_data.get("warnings") or []),
            "occupancy_pct": report_data.get("occupancy_pct"),
        },
    }
    if include_trace:
        result["trace_queries"] = list(query_trace or [])
    return result


def answer_ask_from_spec(
    spec: QuerySpec,
    *,
    format: AskFormat = "md",
    redact_pii: bool = False,
    db_path: Path | None = None,
    intent_mode: str = "deterministic",
    warnings: list[str] | None = None,
    include_trace: bool = False,
) -> dict[str, object]:
    output_format: OutputFormat = "markdown" if format == "md" else "html"
    result = answer_spec_with_metadata(
        spec,
        db_path=db_path,
        output_format=output_format,
        redact_pii=redact_pii,
        include_trace=include_trace,
    )
    meta = dict(result["metadata"])
    meta["intent_mode"] = intent_mode
    merged_warnings = list(meta.get("warnings") or [])
    for item in list(warnings or []):
        if item not in merged_warnings:
            merged_warnings.append(item)
    meta["warnings"] = merged_warnings
    content_type = "text/html" if format == "html" else "text/markdown"
    payload: dict[str, object] = {
        "spec": result["spec"],
        "meta": meta,
        "output": str(result["report"]),
        "content_type": content_type,
    }
    if include_trace:
        payload["_trace_queries"] = list(result.get("trace_queries") or [])
    return payload


def answer_ask_from_plan(
    plan: list[QuerySpec] | tuple[QuerySpec, ...],
    *,
    format: AskFormat = "md",
    redact_pii: bool = False,
    db_path: Path | None = None,
    intent_mode: str = "deterministic",
    warnings: list[str] | None = None,
    compare: bool = False,
    include_trace: bool = False,
) -> dict[str, object]:
    if not plan:
        raise ValueError("plan cannot be empty")

    effective_plan = list(plan)
    if redact_pii:
        effective_plan = [replace(step, redact_pii=True) if not step.redact_pii else step for step in effective_plan]
    if format in {"md", "html"}:
        effective_plan = [replace(step, format=format) if step.format != format else step for step in effective_plan]

    db = _resolve_db_path(db_path)
    query_trace: list[dict[str, object]] | None = [] if include_trace else None
    report_data = execute_query_plan(effective_plan, db_path=db, compare=compare, query_trace=query_trace)
    final_format: OutputFormat = "markdown" if format == "md" else "html"
    rendered = render_report(report_data, output_format=final_format)

    meta: dict[str, object] = {
        "db_path": str(db),
        "output_format": final_format,
        "report_type": report_data["report_type"],
        "group_by": None,
        "start": report_data["start"],
        "end": report_data["end"],
        "reservation_count": report_data.get("reservation_count"),
        "total_sales": report_data.get("total_sales"),
        "total_sales_sum": report_data.get("total_sales_sum"),
        "date_count": report_data.get("date_count"),
        "totals_by_date_count": report_data.get("totals_by_date_count"),
        "compare": bool(report_data.get("compare", False)),
        "executed_count": report_data.get("executed_count"),
        "warnings": list(report_data.get("warnings") or []),
        "occupancy_pct": report_data.get("occupancy_pct"),
    }
    for item in list(warnings or []):
        if item not in meta["warnings"]:
            meta["warnings"].append(item)
    meta["intent_mode"] = intent_mode

    payload: dict[str, object] = {
        "plan": [step.to_dict() for step in effective_plan],
        "meta": meta,
        "output": str(rendered),
        "content_type": "text/html" if format == "html" else "text/markdown",
    }
    if include_trace:
        payload["_trace_queries"] = list(query_trace or [])
    return payload


def answer_ask(
    text: str,
    *,
    format: AskFormat = "md",
    redact_pii: bool = False,
    db_path: Path | None = None,
    intent_mode: str | None = None,
    llm_router: ToyLLMRouter | None = None,
    include_trace: bool = False,
) -> dict[str, object]:
    mode = resolve_intent_mode(intent_mode)
    parsed = parse_toy_query_plan_with_trace(text, intent_mode=mode, llm_router=llm_router)

    if parsed.plan:
        result = answer_ask_from_plan(
            parsed.plan,
            format=format,
            redact_pii=redact_pii,
            db_path=db_path,
            intent_mode=mode,
            warnings=list(parsed.warnings),
            compare=bool(parsed.compare),
            include_trace=include_trace,
        )
        chosen_report_type = "sales_day_plan"
        chosen_group_by = None
        parsed_dates = [str(step.start_date or "") for step in parsed.plan]
        parsed_start = parsed_dates[0] if parsed_dates else None
        parsed_end = parsed_dates[-1] if parsed_dates else None
    else:
        if parsed.spec is None:
            raise ValueError("plan parser returned neither spec nor plan")
        result = answer_ask_from_spec(
            parsed.spec,
            format=format,
            redact_pii=redact_pii,
            db_path=db_path,
            intent_mode=mode,
            warnings=list(parsed.warnings),
            include_trace=include_trace,
        )
        chosen_report_type = parsed.spec.report_type
        chosen_group_by = parsed.spec.group_by
        parsed_dates = list(parsed.spec.dates)
        parsed_start = parsed.spec.start_date
        parsed_end = parsed.spec.end_date

    if include_trace:
        trace_queries = list(result.pop("_trace_queries", []) or [])
        cleaned = str(text or "").strip()
        result["trace"] = {
            "mode": mode,
            "parsed": {
                "start_date": parsed_start,
                "end_date": parsed_end,
                "dates": parsed_dates,
            },
            "chosen": {
                "report_type": chosen_report_type,
                "group_by": chosen_group_by,
            },
            "validation_notes": list(parsed.warnings) + ["QuerySpec validation: pass"],
            "queries": trace_queries,
        }
    return result


def answer_with_metadata(
    text: str,
    db_path: Path | None = None,
    output_format: OutputFormat = "markdown",
    redact_pii: bool = False,
    *,
    intent_mode: str | None = None,
    llm_router: ToyLLMRouter | None = None,
) -> dict[str, object]:
    ask_result = answer_ask(
        text,
        format="md" if output_format == "markdown" else "html",
        redact_pii=redact_pii,
        db_path=db_path,
        intent_mode=intent_mode,
        llm_router=llm_router,
    )
    result = {
        "report": ask_result["output"],
        "metadata": ask_result["meta"],
    }
    if "spec" in ask_result:
        result["spec"] = ask_result["spec"]
    if "plan" in ask_result:
        result["plan"] = ask_result["plan"]
    return result


def answer_question(
    text: str,
    db_path: Path | None = None,
    output_format: OutputFormat = "markdown",
    redact_pii: bool = False,
    *,
    intent_mode: str | None = None,
    llm_router: ToyLLMRouter | None = None,
) -> str:
    return str(
        answer_with_metadata(
            text,
            db_path=db_path,
            output_format=output_format,
            redact_pii=redact_pii,
            intent_mode=intent_mode,
            llm_router=llm_router,
        )["report"]
    )
