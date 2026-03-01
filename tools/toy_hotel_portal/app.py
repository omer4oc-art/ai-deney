"""Toy hotel portal backend serving static pages + local SQLite APIs."""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Literal
from urllib.parse import parse_qs

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, StrictBool

from tools.toy_hotel_portal.db import (
    ROOM_COUNT,
    default_db_path,
    export_rows_in_window,
    init_db,
    insert_reservation,
    next_reservation_id,
    occupancy_days,
    occupancy_pct,
    reservations_in_window,
    to_csv,
)


def _repo_root_from_here() -> Path:
    return Path(__file__).resolve().parents[2]


class AskRequest(BaseModel):
    question: str
    format: Literal["md", "html"] = "md"
    redact_pii: StrictBool = False


def _debug_trace_enabled(query_debug: int) -> bool:
    env_enabled = str(os.getenv("AI_DENEY_TOY_DEBUG_TRACE", "")).strip() == "1"
    return int(query_debug) == 1 or env_enabled


def _parse_iso_date(value: str, *, field: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"invalid {field}, expected YYYY-MM-DD") from exc


def _parse_nonempty_str(payload: dict[str, object], field: str) -> str:
    value = str(payload.get(field, "")).strip()
    if not value:
        raise HTTPException(status_code=422, detail=f"{field} is required")
    return value


def _parse_optional_str(payload: dict[str, object], field: str, default: str = "") -> str:
    value = payload.get(field, default)
    if value is None:
        return default
    return str(value).strip()


def _parse_int(payload: dict[str, object], field: str, *, default: int, min_value: int = 0) -> int:
    raw = payload.get(field, default)
    if raw in ("", None):
        raw = default
    try:
        value = int(raw)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"{field} must be an integer") from exc
    if value < min_value:
        raise HTTPException(status_code=422, detail=f"{field} must be >= {min_value}")
    return value


def _parse_float(payload: dict[str, object], field: str, *, default: float, min_value: float = 0.0) -> float:
    raw = payload.get(field, default)
    if raw in ("", None):
        raw = default
    try:
        value = float(raw)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"{field} must be a number") from exc
    if value < min_value:
        raise HTTPException(status_code=422, detail=f"{field} must be >= {min_value}")
    return value


async def _load_payload(request: Request) -> dict[str, object]:
    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    raw = await request.body()

    if content_type == "application/json":
        if not raw:
            return {}
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            raise HTTPException(status_code=400, detail="invalid JSON body") from exc
        if not isinstance(parsed, dict):
            raise HTTPException(status_code=400, detail="JSON body must be an object")
        return parsed

    if content_type == "application/x-www-form-urlencoded":
        parsed_qs = parse_qs(raw.decode("utf-8"), keep_blank_values=True)
        return {k: v[-1] for k, v in parsed_qs.items()}

    # Best-effort fallback for clients that omit content-type.
    text = raw.decode("utf-8").strip()
    if text.startswith("{"):
        try:
            parsed = json.loads(text)
        except Exception as exc:
            raise HTTPException(status_code=400, detail="invalid body") from exc
        if not isinstance(parsed, dict):
            raise HTTPException(status_code=400, detail="body must be an object")
        return parsed
    if "=" in text:
        parsed_qs = parse_qs(text, keep_blank_values=True)
        return {k: v[-1] for k, v in parsed_qs.items()}

    raise HTTPException(
        status_code=415,
        detail="unsupported content type; use application/json or application/x-www-form-urlencoded",
    )


def create_app(
    *,
    repo_root: Path | None = None,
    db_path: Path | None = None,
    static_dir: Path | None = None,
) -> FastAPI:
    root = (repo_root or _repo_root_from_here()).resolve()
    database_path = (db_path or default_db_path(root)).resolve()
    static_root = (static_dir or (Path(__file__).resolve().parent / "static")).resolve()
    init_db(database_path)

    app = FastAPI(title="Toy Hotel Portal", version="0.1.0")
    app.state.db_path = database_path
    app.state.static_root = static_root
    app.mount("/static", StaticFiles(directory=str(static_root)), name="static")

    src_root = root / "src"
    if str(src_root) not in sys.path:
        sys.path.insert(0, str(src_root))

    @app.get("/health")
    def health() -> dict[str, object]:
        return {"ok": True, "service": "toy_hotel_portal"}

    @app.get("/")
    def dashboard_page() -> FileResponse:
        return FileResponse(str(static_root / "dashboard.html"))

    @app.get("/checkin")
    def checkin_page() -> FileResponse:
        return FileResponse(str(static_root / "checkin.html"))

    @app.get("/api/occupancy")
    def api_occupancy(start: str = Query(...), end: str = Query(...)) -> dict[str, object]:
        start_day = _parse_iso_date(start, field="start")
        end_day = _parse_iso_date(end, field="end")
        if end_day < start_day:
            raise HTTPException(status_code=400, detail="end must be >= start")

        days = occupancy_days(app.state.db_path, start_day, end_day)
        pct = occupancy_pct(days, room_count=ROOM_COUNT)
        return {"room_count": ROOM_COUNT, "occupancy_pct": pct, "days": days}

    @app.get("/api/reservations")
    def api_reservations(
        start: str = Query(...),
        end: str = Query(...),
        limit: int = Query(10, ge=1, le=1000),
    ) -> list[dict[str, object]]:
        start_day = _parse_iso_date(start, field="start")
        end_day = _parse_iso_date(end, field="end")
        if end_day < start_day:
            raise HTTPException(status_code=400, detail="end must be >= start")
        return reservations_in_window(app.state.db_path, start_day, end_day, limit=limit)

    @app.post("/api/checkin")
    async def api_checkin(request: Request) -> JSONResponse:
        payload = await _load_payload(request)

        guest_name = _parse_nonempty_str(payload, "guest_name")
        check_in = _parse_iso_date(_parse_nonempty_str(payload, "check_in"), field="check_in")
        check_out = _parse_iso_date(_parse_nonempty_str(payload, "check_out"), field="check_out")
        if check_out <= check_in:
            raise HTTPException(status_code=422, detail="check_out must be after check_in")

        adults = _parse_int(payload, "adults", default=1, min_value=1)
        children = _parse_int(payload, "children", default=0, min_value=0)
        nightly_rate = _parse_float(payload, "nightly_rate", default=0.0, min_value=0.0)
        total_paid = _parse_float(payload, "total_paid", default=0.0, min_value=0.0)

        reservation_id = _parse_optional_str(payload, "reservation_id", default="")
        if not reservation_id:
            reservation_id = next_reservation_id(app.state.db_path)

        record = {
            "reservation_id": reservation_id,
            "guest_name": guest_name,
            "check_in": check_in.isoformat(),
            "check_out": check_out.isoformat(),
            "room_type": _parse_optional_str(payload, "room_type", default="Standard") or "Standard",
            "adults": adults,
            "children": children,
            "source_channel": _parse_optional_str(payload, "source_channel", default="direct") or "direct",
            "agency_id": _parse_optional_str(payload, "agency_id", default=""),
            "agency_name": _parse_optional_str(payload, "agency_name", default=""),
            "nightly_rate": nightly_rate,
            "total_paid": total_paid,
            "currency": (_parse_optional_str(payload, "currency", default="USD") or "USD").upper(),
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        }

        try:
            insert_reservation(app.state.db_path, record)
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail=f"reservation_id already exists: {reservation_id}") from exc

        return JSONResponse({"ok": True, "reservation_id": reservation_id})

    @app.get("/api/export")
    def api_export(
        start: str = Query(...),
        end: str = Query(...),
        redact_pii: int = Query(0, ge=0, le=1),
    ) -> Response:
        start_day = _parse_iso_date(start, field="start")
        end_day = _parse_iso_date(end, field="end")
        if end_day < start_day:
            raise HTTPException(status_code=400, detail="end must be >= start")

        rows = export_rows_in_window(app.state.db_path, start_day, end_day)
        csv_text = to_csv(rows, redact_pii=bool(redact_pii))
        filename = f"toy_portal_{start_day.isoformat()}_{end_day.isoformat()}.csv"
        headers = {"Content-Disposition": f"attachment; filename={filename}"}
        return Response(content=csv_text, media_type="text/csv", headers=headers)

    @app.post("/api/ask")
    async def api_ask(payload: AskRequest, debug: int = Query(0, ge=0, le=1)) -> dict[str, object]:
        question = payload.question.strip()
        if not question:
            raise HTTPException(status_code=422, detail="question is required")
        include_trace = _debug_trace_enabled(debug)

        try:
            from ai_deney.reports.toy_reports import answer_ask

            result = answer_ask(
                question,
                format=payload.format,
                db_path=app.state.db_path,
                redact_pii=bool(payload.redact_pii),
                include_trace=include_trace,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        response: dict[str, object] = {
            "ok": True,
            "spec": result["spec"],
            "meta": result["meta"],
            "output": result["output"],
            "content_type": result["content_type"],
        }
        if include_trace and "trace" in result:
            response["trace"] = result["trace"]
        return response

    return app


app = create_app()
