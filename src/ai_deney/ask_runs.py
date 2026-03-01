"""Shared helpers for deterministic Ask Alice run persistence and comparison."""

from __future__ import annotations

import difflib
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

RUN_ID_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{6}_[a-z0-9-]{1,32}_[0-9a-f]{8}$")
_GUEST_NAME_RE_JSON = re.compile(r'("guest_name"\s*:\s*")([^"]*)(")', flags=re.IGNORECASE)
_GUEST_NAME_RE_KV = re.compile(r"(\bguest_name\s*[:=]\s*)([^\n\r]+)", flags=re.IGNORECASE)


def _assert_within_repo(path: Path, repo_root: Path) -> None:
    try:
        path.resolve().relative_to(repo_root.resolve())
    except Exception as exc:
        raise ValueError(f"path escapes repo root: {path}") from exc


def resolve_runs_root(repo_root: Path, runs_root: str | Path | None = None) -> Path:
    root = repo_root.resolve()
    raw = Path(runs_root) if runs_root is not None else (root / "outputs" / "_ask_runs")
    if not raw.is_absolute():
        raw = root / raw
    resolved = raw.resolve()
    _assert_within_repo(resolved, root)
    return resolved


def build_request_payload(
    *,
    question: str,
    ask_format: Literal["md", "html"],
    redact_pii: bool,
    debug: bool,
) -> dict[str, object]:
    return {
        "question": str(question).strip(),
        "format": "html" if str(ask_format) == "html" else "md",
        "redact_pii": bool(redact_pii),
        "debug": bool(debug),
    }


def build_shortslug(question: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(question).strip().lower()).strip("-")
    if not slug:
        return "ask"
    return slug[:32]


def build_hash8(request_payload: dict[str, object]) -> str:
    canonical = json.dumps(request_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:8]


def build_run_id(
    request_payload: dict[str, object],
    *,
    created_at: datetime | None = None,
    existing: set[str] | None = None,
) -> tuple[str, datetime]:
    question = str(request_payload.get("question") or "")
    shortslug = build_shortslug(question)
    hash8 = build_hash8(request_payload)
    cursor = (created_at or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(microsecond=0)
    existing_ids = existing or set()
    for _ in range(120):
        timestamp = cursor.strftime("%Y-%m-%d_%H%M%S")
        run_id = f"{timestamp}_{shortslug}_{hash8}"
        if run_id not in existing_ids:
            return run_id, cursor
        cursor = cursor + timedelta(seconds=1)
    raise ValueError("failed to allocate unique ask run id")


def sanitize_trace(trace: object) -> object:
    blocked_exact = {"rows", "raw_rows", "reservation_rows"}
    if isinstance(trace, dict):
        clean: dict[str, object] = {}
        for key, value in trace.items():
            lowered = str(key).strip().lower()
            if "guest_name" in lowered or lowered in blocked_exact:
                continue
            clean[str(key)] = sanitize_trace(value)
        return clean
    if isinstance(trace, list):
        return [sanitize_trace(item) for item in trace]
    return trace


def _render_index_markdown(
    *,
    run_id: str,
    created_at: datetime,
    request_payload: dict[str, object],
    response_payload: dict[str, object],
    output_name: str,
) -> str:
    meta = response_payload.get("meta") if isinstance(response_payload.get("meta"), dict) else {}
    lines = [
        f"# Ask Run {run_id}",
        "",
        f"- created_at_utc: {created_at.strftime('%Y-%m-%dT%H:%M:%SZ')}",
        f"- question: {request_payload.get('question', '')}",
        f"- format: {request_payload.get('format', 'md')}",
        f"- redact_pii: {bool(request_payload.get('redact_pii'))}",
        f"- debug: {bool(request_payload.get('debug'))}",
        f"- content_type: {response_payload.get('content_type', '')}",
        f"- report_type: {meta.get('report_type', '') if isinstance(meta, dict) else ''}",
        f"- range: {meta.get('start', '') if isinstance(meta, dict) else ''}..{meta.get('end', '') if isinstance(meta, dict) else ''}",
        "",
        "## Files",
        "",
        "- [request.json](request.json)",
        "- [response.json](response.json)",
        f"- [{output_name}]({output_name})",
        "- [index.md](index.md)",
        "",
    ]
    return "\n".join(lines)


def save_ask_run(
    *,
    repo_root: Path,
    request_payload: dict[str, object],
    response_payload: dict[str, object],
    output_text: str,
    runs_root: str | Path | None = None,
) -> dict[str, object]:
    root = repo_root.resolve()
    resolved_runs_root = resolve_runs_root(root, runs_root)
    resolved_runs_root.mkdir(parents=True, exist_ok=True)
    existing_ids = {p.name for p in resolved_runs_root.iterdir() if p.is_dir()}
    run_id, created_at = build_run_id(request_payload, existing=existing_ids)
    run_dir = resolved_runs_root / run_id
    run_dir.mkdir(parents=True, exist_ok=False)

    output_ext = "html" if str(request_payload.get("format")) == "html" else "md"
    output_name = f"output.{output_ext}"
    request_path = run_dir / "request.json"
    response_path = run_dir / "response.json"
    output_path = run_dir / output_name
    index_path = run_dir / "index.md"

    response_for_disk: dict[str, object] = {
        "ok": bool(response_payload.get("ok")),
        "spec": response_payload.get("spec"),
        "meta": response_payload.get("meta"),
        "content_type": response_payload.get("content_type"),
    }
    if bool(request_payload.get("debug")) and "trace" in response_payload:
        response_for_disk["trace"] = sanitize_trace(response_payload.get("trace"))

    request_path.write_text(json.dumps(request_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    response_path.write_text(json.dumps(response_for_disk, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_path.write_text(str(output_text), encoding="utf-8")
    index_path.write_text(
        _render_index_markdown(
            run_id=run_id,
            created_at=created_at,
            request_payload=request_payload,
            response_payload=response_for_disk,
            output_name=output_name,
        ),
        encoding="utf-8",
    )

    return {
        "run_id": run_id,
        "run_dir": run_dir,
        "created_at": created_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "files": {
            "request_json": request_path,
            "response_json": response_path,
            "output": output_path,
            "index_md": index_path,
        },
    }


def _parse_created_from_run_id(run_id: str) -> str:
    try:
        stamp = run_id[:17]
        created = datetime.strptime(stamp, "%Y-%m-%d_%H%M%S").replace(tzinfo=timezone.utc)
        return created.strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return ""


def _read_json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"invalid JSON object: {path}")
    return payload


def list_recent_ask_runs(
    *,
    repo_root: Path,
    runs_root: str | Path | None = None,
    limit: int = 20,
) -> list[dict[str, object]]:
    root = repo_root.resolve()
    resolved_runs_root = resolve_runs_root(root, runs_root)
    if not resolved_runs_root.exists():
        return []
    rows: list[dict[str, object]] = []
    for run_dir in sorted((p for p in resolved_runs_root.iterdir() if p.is_dir()), key=lambda p: p.name, reverse=True):
        run_id = run_dir.name
        if not RUN_ID_RE.match(run_id):
            continue
        req_path = run_dir / "request.json"
        if not req_path.exists():
            continue
        try:
            req = _read_json(req_path)
        except Exception:
            continue
        question = str(req.get("question") or "")
        rows.append(
            {
                "run_id": run_id,
                "created_at": _parse_created_from_run_id(run_id),
                "question": question,
                "question_snippet": (question[:120] + "...") if len(question) > 120 else question,
                "format": str(req.get("format") or "md"),
                "redact_pii": bool(req.get("redact_pii")),
                "debug": bool(req.get("debug")),
            }
        )
        if len(rows) >= max(1, int(limit)):
            break
    return rows


def load_ask_run(
    *,
    repo_root: Path,
    run_id: str,
    runs_root: str | Path | None = None,
) -> dict[str, object]:
    rid = str(run_id).strip()
    if not RUN_ID_RE.match(rid):
        raise ValueError(f"invalid run_id: {run_id}")
    root = repo_root.resolve()
    resolved_runs_root = resolve_runs_root(root, runs_root)
    run_dir = (resolved_runs_root / rid).resolve()
    _assert_within_repo(run_dir, root)
    if not run_dir.exists() or not run_dir.is_dir():
        raise FileNotFoundError(f"ask run not found: {rid}")

    request_path = run_dir / "request.json"
    response_path = run_dir / "response.json"
    output_md = run_dir / "output.md"
    output_html = run_dir / "output.html"
    output_path = output_md if output_md.exists() else output_html
    if not output_path.exists():
        raise FileNotFoundError(f"missing output file for ask run: {rid}")
    request_payload = _read_json(request_path)
    response_payload = _read_json(response_path)

    return {
        "run_id": rid,
        "run_dir": run_dir,
        "created_at": _parse_created_from_run_id(rid),
        "request": request_payload,
        "response": response_payload,
        "output_path": output_path,
        "output_text": output_path.read_text(encoding="utf-8"),
        "output_format": "html" if output_path.suffix.lower() == ".html" else "md",
        "files": {
            "request_json": request_path,
            "response_json": response_path,
            "output": output_path,
            "index_md": run_dir / "index.md",
        },
    }


def _redact_guest_name_fields(text: str) -> str:
    out = _GUEST_NAME_RE_JSON.sub(r'\1REDACTED\3', str(text))
    return _GUEST_NAME_RE_KV.sub(r"\1REDACTED", out)


def compare_saved_runs(
    *,
    repo_root: Path,
    run_a: str,
    run_b: str,
    ask_format: Literal["md", "html"] = "md",
    runs_root: str | Path | None = None,
) -> dict[str, object]:
    left = load_ask_run(repo_root=repo_root, run_id=run_a, runs_root=runs_root)
    right = load_ask_run(repo_root=repo_root, run_id=run_b, runs_root=runs_root)

    requested_ext = ".html" if str(ask_format) == "html" else ".md"
    left_path = left["run_dir"] / f"output{requested_ext}"
    right_path = right["run_dir"] / f"output{requested_ext}"
    left_text = left_path.read_text(encoding="utf-8") if left_path.exists() else str(left["output_text"])
    right_text = right_path.read_text(encoding="utf-8") if right_path.exists() else str(right["output_text"])

    redact = bool(left["request"].get("redact_pii")) or bool(right["request"].get("redact_pii"))
    if redact:
        left_text = _redact_guest_name_fields(left_text)
        right_text = _redact_guest_name_fields(right_text)

    left_lines = left_text.splitlines()
    right_lines = right_text.splitlines()
    diff_lines = list(
        difflib.unified_diff(
            left_lines,
            right_lines,
            fromfile=f"{left['run_id']}/output{requested_ext}",
            tofile=f"{right['run_id']}/output{requested_ext}",
            lineterm="",
        )
    )

    return {
        "ok": True,
        "run_a": left["run_id"],
        "run_b": right["run_id"],
        "diff": "\n".join(diff_lines),
        "content_type": "text/plain",
    }
