"""Toy hotel portal backend serving static pages + local SQLite APIs."""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import date, datetime, timezone
from html import escape as html_escape
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


def _debug_trace_enabled(query_debug: bool, request: Request) -> bool:
    env_enabled = str(os.getenv("AI_DENEY_TOY_DEBUG_TRACE", "")).strip() == "1"
    raw = str(request.query_params.get("debug", "")).strip().lower()
    query_enabled = bool(query_debug) or raw in {"1", "true", "yes", "on"}
    return query_enabled or env_enabled


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

    from ai_deney.ask_runs import (
        build_request_payload,
        compare_saved_runs,
        list_recent_ask_runs,
        load_ask_run,
        resolve_runs_root,
        sanitize_trace,
        save_ask_run,
    )

    def _relative_repo_path(path: Path) -> str:
        return path.resolve().relative_to(root).as_posix()

    def _run_urls(run_id: str) -> dict[str, str]:
        return {
            "view": f"/ask-run/{run_id}",
            "index_md": f"/ask-run/{run_id}/index.md",
            "request_json": f"/ask-run/{run_id}/request.json",
            "response_json": f"/ask-run/{run_id}/response.json",
            "output_md": f"/ask-run/{run_id}/output.md",
            "output_html": f"/ask-run/{run_id}/output.html",
        }

    async def _ask_response_payload(payload: AskRequest, include_trace: bool) -> dict[str, object]:
        question = payload.question.strip()
        if not question:
            raise HTTPException(status_code=422, detail="question is required")
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
            "meta": result["meta"],
            "output": result["output"],
            "content_type": result["content_type"],
        }
        if "plan" in result:
            response["plan"] = result["plan"]
        if "spec" in result:
            response["spec"] = result["spec"]
        if include_trace:
            response["trace"] = sanitize_trace(result.get("trace", {}))
        return response

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
    async def api_ask(request: Request, payload: AskRequest, debug: bool = False) -> dict[str, object]:
        include_trace = _debug_trace_enabled(debug, request)
        return await _ask_response_payload(payload, include_trace=include_trace)

    @app.post("/api/ask/save")
    async def api_ask_save(
        request: Request,
        payload: AskRequest,
        debug: bool = False,
        runs_root: str | None = Query(default=None),
    ) -> dict[str, object]:
        include_trace = _debug_trace_enabled(debug, request)
        response_payload = await _ask_response_payload(payload, include_trace=include_trace)
        question = payload.question.strip()
        request_payload = build_request_payload(
            question=question,
            ask_format=payload.format,
            redact_pii=bool(payload.redact_pii),
            debug=bool(include_trace),
        )
        try:
            resolved_runs_root = resolve_runs_root(root, runs_root)
            saved = save_ask_run(
                repo_root=root,
                request_payload=request_payload,
                response_payload=response_payload,
                output_text=str(response_payload.get("output") or ""),
                runs_root=resolved_runs_root,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        run_id = str(saved["run_id"])
        files = saved["files"]
        urls = _run_urls(run_id)
        return {
            "ok": True,
            "run_id": run_id,
            "run_dir": _relative_repo_path(saved["run_dir"]),
            "files": {
                "request_json": _relative_repo_path(files["request_json"]),
                "response_json": _relative_repo_path(files["response_json"]),
                "output": _relative_repo_path(files["output"]),
                "index_md": _relative_repo_path(files["index_md"]),
                "index_url": urls["index_md"],
                "view_url": urls["view"],
            },
            "response": response_payload,
        }

    @app.get("/api/ask/runs")
    def api_ask_runs(limit: int = Query(default=20, ge=1, le=200), runs_root: str | None = Query(default=None)) -> dict[str, object]:
        try:
            resolved_runs_root = resolve_runs_root(root, runs_root)
            runs = list_recent_ask_runs(repo_root=root, runs_root=resolved_runs_root, limit=limit)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        rows: list[dict[str, object]] = []
        for row in runs:
            rid = str(row["run_id"])
            urls = _run_urls(rid)
            out = dict(row)
            out["run_dir"] = _relative_repo_path(resolved_runs_root / rid)
            out["index_url"] = urls["index_md"]
            out["view_url"] = urls["view"]
            rows.append(out)
        return {"ok": True, "runs": rows}

    @app.get("/ask-run/{run_id}/{filename}")
    def ask_run_file(run_id: str, filename: str, runs_root: str | None = Query(default=None)) -> FileResponse:
        allowed = {"request.json", "response.json", "output.md", "output.html", "index.md"}
        if filename not in allowed:
            raise HTTPException(status_code=404, detail="file not found")
        try:
            run = load_ask_run(repo_root=root, run_id=run_id, runs_root=runs_root)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        path = (run["run_dir"] / filename).resolve()
        try:
            path.relative_to(root.resolve())
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"path escapes repo root: {path}") from exc
        if not path.exists() or not path.is_file():
            raise HTTPException(status_code=404, detail="file not found")
        media_type = "text/plain"
        if filename.endswith(".json"):
            media_type = "application/json"
        if filename.endswith(".html"):
            media_type = "text/html"
        return FileResponse(str(path), media_type=media_type)

    @app.get("/ask-run/{run_id}")
    def ask_run_view(run_id: str, runs_root: str | None = Query(default=None)) -> Response:
        try:
            run = load_ask_run(repo_root=root, run_id=run_id, runs_root=runs_root)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        output_text = str(run["output_text"])
        output_rendered = f"<pre>{html_escape(output_text)}</pre>"
        if str(run["output_format"]) == "md":
            try:
                import markdown as mdlib

                output_rendered = mdlib.markdown(output_text, extensions=["extra", "tables"])
            except Exception:
                output_rendered = f"<pre>{html_escape(output_text)}</pre>"

        request_payload = run["request"] if isinstance(run["request"], dict) else {}
        response_payload = run["response"] if isinstance(run["response"], dict) else {}
        spec_payload = response_payload.get("spec", {})
        meta_payload = response_payload.get("meta", {})
        content_type = str(response_payload.get("content_type") or "")
        html = (
            "<!doctype html><html><head><meta charset='utf-8'>"
            f"<title>Ask Run {html_escape(run_id)}</title>"
            "<style>"
            "body{font-family:ui-monospace,Menlo,Consolas,monospace;max-width:1080px;margin:24px auto;padding:0 16px;color:#0f172a;}"
            "a{color:#0369a1;text-decoration:none;}a:hover{text-decoration:underline;}"
            "code,pre{background:#f8fafc;border:1px solid #e2e8f0;border-radius:6px;padding:10px;display:block;overflow:auto;}"
            ".card{border:1px solid #e2e8f0;border-radius:10px;padding:14px;margin:14px 0;}"
            "</style></head><body>"
            f"<h1>Ask Run {html_escape(run_id)}</h1>"
            f"<p>Created: {html_escape(str(run.get('created_at') or ''))}</p>"
            "<div class='card'><h2>Request</h2>"
            f"<pre>{html_escape(json.dumps(request_payload, indent=2, ensure_ascii=False))}</pre>"
            "</div>"
            "<div class='card'><h2>Response Summary</h2>"
            f"<p>content_type: {html_escape(content_type)}</p>"
            f"<h3>spec</h3><pre>{html_escape(json.dumps(spec_payload, indent=2, ensure_ascii=False))}</pre>"
            f"<h3>meta</h3><pre>{html_escape(json.dumps(meta_payload, indent=2, ensure_ascii=False))}</pre>"
            "</div>"
            "<div class='card'><h2>Files</h2><ul>"
            f"<li><a href='/ask-run/{html_escape(run_id)}/request.json' target='_blank' rel='noopener'>request.json</a></li>"
            f"<li><a href='/ask-run/{html_escape(run_id)}/response.json' target='_blank' rel='noopener'>response.json</a></li>"
            f"<li><a href='/ask-run/{html_escape(run_id)}/{html_escape(Path(run['output_path']).name)}' target='_blank' rel='noopener'>{html_escape(Path(run['output_path']).name)}</a></li>"
            f"<li><a href='/ask-run/{html_escape(run_id)}/index.md' target='_blank' rel='noopener'>index.md</a></li>"
            "</ul></div>"
            "<div class='card'><h2>Output</h2>"
            f"{output_rendered}"
            "</div></body></html>"
        )
        return Response(content=html, media_type="text/html")

    @app.get("/api/ask/compare")
    def api_ask_compare(
        run_a: str = Query(...),
        run_b: str = Query(...),
        format: Literal["md", "html"] = Query(default="md"),
        runs_root: str | None = Query(default=None),
    ) -> dict[str, object]:
        try:
            return compare_saved_runs(
                repo_root=root,
                run_a=run_a,
                run_b=run_b,
                ask_format=format,
                runs_root=runs_root,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    return app


app = create_app()
