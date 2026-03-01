"""Deterministic toy portal reports from validated QuerySpec input."""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import replace
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Literal

from ai_deney.intent.toy_intent import (
    QuerySpec,
    ToyLLMRouter,
    parse_toy_query,
    resolve_intent_mode,
)
from tools.toy_hotel_portal.db import (
    ROOM_COUNT,
    default_db_path,
    export_rows_in_window,
    occupancy_days,
    occupancy_pct,
    reservations_in_window,
)

OutputFormat = Literal["markdown", "html"]
AskFormat = Literal["md", "html"]
_SOURCE_FOOTER = "Source: toy_portal SQLite data; generated deterministically from QuerySpec."
_RESERVATION_LIST_LIMIT = 200


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


def _run_sales_report(spec: QuerySpec, db_path: Path) -> dict[str, object]:
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


def _run_occupancy_report(spec: QuerySpec, db_path: Path) -> dict[str, object]:
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


def _run_reservations_list_report(spec: QuerySpec, db_path: Path) -> dict[str, object]:
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


def _run_export_reservations_report(spec: QuerySpec, db_path: Path) -> dict[str, object]:
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


def run_query_spec(spec: QuerySpec, db_path: Path) -> dict[str, object]:
    if spec.report_type in {"sales_range", "sales_month", "sales_by_channel"}:
        return _run_sales_report(spec, db_path)
    if spec.report_type == "occupancy_range":
        return _run_occupancy_report(spec, db_path)
    if spec.report_type == "reservations_list":
        return _run_reservations_list_report(spec, db_path)
    if spec.report_type == "export_reservations":
        return _run_export_reservations_report(spec, db_path)
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
) -> dict[str, object]:
    effective = spec
    if redact_pii and not effective.redact_pii:
        effective = replace(effective, redact_pii=True)
    if output_format is not None:
        out_fmt = "md" if output_format == "markdown" else "html"
        if effective.format != out_fmt:
            effective = replace(effective, format=out_fmt)

    db = _resolve_db_path(db_path)
    report_data = run_query_spec(effective, db)
    final_format: OutputFormat = "markdown" if effective.format == "md" else "html"
    rendered = render_report(report_data, output_format=final_format)
    return {
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
            "occupancy_pct": report_data.get("occupancy_pct"),
        },
    }


def answer_ask_from_spec(
    spec: QuerySpec,
    *,
    format: AskFormat = "md",
    redact_pii: bool = False,
    db_path: Path | None = None,
    intent_mode: str = "deterministic",
) -> dict[str, object]:
    output_format: OutputFormat = "markdown" if format == "md" else "html"
    result = answer_spec_with_metadata(spec, db_path=db_path, output_format=output_format, redact_pii=redact_pii)
    meta = dict(result["metadata"])
    meta["intent_mode"] = intent_mode
    content_type = "text/html" if format == "html" else "text/markdown"
    return {
        "spec": result["spec"],
        "meta": meta,
        "output": str(result["report"]),
        "content_type": content_type,
    }


def answer_ask(
    text: str,
    *,
    format: AskFormat = "md",
    redact_pii: bool = False,
    db_path: Path | None = None,
    intent_mode: str | None = None,
    llm_router: ToyLLMRouter | None = None,
) -> dict[str, object]:
    mode = resolve_intent_mode(intent_mode)
    spec = parse_toy_query(text, intent_mode=mode, llm_router=llm_router)
    return answer_ask_from_spec(
        spec,
        format=format,
        redact_pii=redact_pii,
        db_path=db_path,
        intent_mode=mode,
    )


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
        "spec": ask_result["spec"],
        "metadata": ask_result["meta"],
    }
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
