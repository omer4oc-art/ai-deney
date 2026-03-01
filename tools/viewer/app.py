"""Thin local viewer for truth pack and inbox run artifacts."""

from __future__ import annotations

import difflib
import hashlib
import html
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import quote, urlencode

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse

try:
    import markdown as md_pkg
except Exception:  # pragma: no cover - optional dependency
    md_pkg = None


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8010

ALLOWED_VIEW_SUFFIXES = {".md", ".html", ".txt", ".json"}
COMPARE_SUFFIXES = {".md", ".html", ".txt", ".json"}
TEXT_DIFF_SUFFIXES = {".md", ".txt", ".json"}

MAX_DIFF_LINES = 500
MAX_DIFF_CHARS = 30_000


@dataclass(frozen=True)
class ViewerRoots:
    repo_root: Path
    truth_pack_root: Path
    inbox_runs_root: Path
    raw_root: Path


@dataclass(frozen=True)
class RunInfo:
    run_id: str
    label: str
    path: Path
    exists: bool
    kind: str


def _repo_root_from_here() -> Path:
    return Path(__file__).resolve().parents[2]


def _resolve_under(root: Path, rel_path: str) -> Path:
    rel = Path(rel_path)
    if rel.is_absolute():
        raise HTTPException(status_code=400, detail="absolute paths are not allowed")
    resolved_root = root.resolve()
    resolved_path = (resolved_root / rel).resolve()
    try:
        resolved_path.relative_to(resolved_root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="path traversal is not allowed") from exc
    return resolved_path


def _is_valid_run_id(run_id: str) -> bool:
    return bool(run_id) and run_id not in {".", ".."} and "/" not in run_id and "\\" not in run_id


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(8192)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _render_markdown_fallback(text: str) -> str:
    lines = text.splitlines()
    out: list[str] = []

    paragraph: list[str] = []
    code_block: list[str] = []
    table_block: list[str] = []
    in_code = False

    def flush_paragraph() -> None:
        if paragraph:
            content = " ".join(part.strip() for part in paragraph if part.strip())
            if content:
                out.append(f"<p>{html.escape(content)}</p>")
        paragraph.clear()

    def flush_table() -> None:
        if table_block:
            out.append(f"<pre>{html.escape(chr(10).join(table_block))}</pre>")
        table_block.clear()

    def flush_code() -> None:
        if code_block:
            code = "\n".join(code_block)
            out.append(f"<pre><code>{html.escape(code)}</code></pre>")
        code_block.clear()

    for raw in lines:
        line = raw.rstrip("\n")
        stripped = line.strip()

        if stripped.startswith("```"):
            flush_paragraph()
            flush_table()
            if in_code:
                flush_code()
                in_code = False
            else:
                in_code = True
            continue

        if in_code:
            code_block.append(line)
            continue

        if not stripped:
            flush_paragraph()
            flush_table()
            continue

        if "|" in line:
            flush_paragraph()
            table_block.append(line)
            continue

        flush_table()
        if stripped.startswith("#"):
            hashes = len(stripped) - len(stripped.lstrip("#"))
            if 1 <= hashes <= 6 and len(stripped) > hashes and stripped[hashes] == " ":
                flush_paragraph()
                header_text = stripped[hashes + 1 :].strip()
                out.append(f"<h{hashes}>{html.escape(header_text)}</h{hashes}>")
                continue
        paragraph.append(line)

    flush_paragraph()
    flush_table()
    if in_code:
        flush_code()
    return "\n".join(out)


def _render_markdown(text: str) -> str:
    if md_pkg is not None:
        return str(md_pkg.markdown(text, extensions=["fenced_code", "tables"], output_format="html5"))
    return _render_markdown_fallback(text)


def _page(title: str, body: str) -> str:
    safe_title = html.escape(title)
    return (
        "<!doctype html>"
        "<html><head><meta charset='utf-8'>"
        f"<title>{safe_title}</title>"
        "<style>"
        "body{font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;max-width:1100px;"
        "margin:24px auto;padding:0 16px;line-height:1.5;color:#141414;}"
        "h1,h2,h3{line-height:1.2;}"
        "a{color:#0f4fa8;text-decoration:none;}a:hover{text-decoration:underline;}"
        "code{background:#f2f4f8;padding:1px 4px;border-radius:4px;}"
        "pre{background:#f2f4f8;padding:12px;border-radius:6px;overflow-x:auto;}"
        "table{border-collapse:collapse;}th,td{border:1px solid #d6dbe4;padding:6px 8px;}"
        ".muted{color:#666;font-size:0.95em;}"
        ".grid{display:grid;grid-template-columns:1fr 1fr;gap:20px;}"
        "ul{padding-left:20px;}li{margin:4px 0;}"
        "input,select{padding:6px 8px;margin-right:8px;}"
        "button{padding:6px 10px;}"
        "</style>"
        "</head><body>"
        f"{body}"
        "</body></html>"
    )


def _run_file_items(root: Path) -> list[str]:
    items: list[str] = []
    if not root.exists():
        return items
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix.lower() in ALLOWED_VIEW_SUFFIXES:
            items.append(path.relative_to(root).as_posix())
    return items


def _compare_file_map(root: Path) -> dict[str, tuple[Path, str]]:
    out: dict[str, tuple[Path, str]] = {}
    if not root.exists():
        return out
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in COMPARE_SUFFIXES:
            continue
        rel = path.relative_to(root).as_posix()
        out[rel] = (path, _sha256(path))
    return out


def _list_runs(roots: ViewerRoots) -> list[RunInfo]:
    entries: list[RunInfo] = [
        RunInfo(
            run_id="truth_pack",
            label="Truth Pack (current)",
            path=roots.truth_pack_root,
            exists=roots.truth_pack_root.is_dir(),
            kind="truth_pack",
        )
    ]

    inbox_dirs: list[Path] = []
    if roots.inbox_runs_root.is_dir():
        inbox_dirs = [p for p in roots.inbox_runs_root.iterdir() if p.is_dir()]
    inbox_dirs.sort(key=lambda p: (p.stat().st_mtime, p.name), reverse=True)
    for path in inbox_dirs:
        entries.append(
            RunInfo(
                run_id=path.name,
                label=f"Inbox Run {path.name}",
                path=path,
                exists=True,
                kind="inbox_run",
            )
        )
    return entries


def _run_by_id(roots: ViewerRoots, run_id: str) -> RunInfo:
    if run_id == "truth_pack":
        info = RunInfo(
            run_id="truth_pack",
            label="Truth Pack (current)",
            path=roots.truth_pack_root,
            exists=roots.truth_pack_root.is_dir(),
            kind="truth_pack",
        )
        if not info.exists:
            raise HTTPException(status_code=404, detail="truth pack is not available")
        return info

    if not _is_valid_run_id(run_id):
        raise HTTPException(status_code=400, detail="invalid run id")

    run_path = _resolve_under(roots.inbox_runs_root, run_id)
    if not run_path.is_dir():
        raise HTTPException(status_code=404, detail=f"run not found: {run_id}")
    return RunInfo(
        run_id=run_id,
        label=f"Inbox Run {run_id}",
        path=run_path,
        exists=True,
        kind="inbox_run",
    )


def _audit_manifests(roots: ViewerRoots) -> list[Path]:
    manifests: list[Path] = []
    if not roots.raw_root.is_dir():
        return manifests
    for path in roots.raw_root.rglob("manifest.json"):
        if path.is_file():
            manifests.append(path)
    manifests.sort(key=lambda p: (p.stat().st_mtime, str(p)), reverse=True)
    return manifests


def _normalize_for_diff(path: Path) -> list[str]:
    text = _read_text(path)
    if path.suffix.lower() == ".json":
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return text.splitlines()
        text = json.dumps(parsed, indent=2, sort_keys=True)
    return text.splitlines()


def _limited_diff(
    run_a: str,
    file_a: Path,
    run_b: str,
    file_b: Path,
    rel_path: str,
) -> tuple[str, bool]:
    left = _normalize_for_diff(file_a)
    right = _normalize_for_diff(file_b)
    lines = list(
        difflib.unified_diff(
            left,
            right,
            fromfile=f"{run_a}/{rel_path}",
            tofile=f"{run_b}/{rel_path}",
            lineterm="",
        )
    )
    truncated = False
    if len(lines) > MAX_DIFF_LINES:
        lines = lines[:MAX_DIFF_LINES]
        truncated = True

    text = "\n".join(lines)
    if len(text) > MAX_DIFF_CHARS:
        text = text[:MAX_DIFF_CHARS]
        truncated = True
    return text, truncated


def _link_list(items: Iterable[str], run_id: str) -> str:
    links = []
    for rel in items:
        href = f"/file/{quote(run_id, safe='')}/{quote(rel, safe='/')}"
        links.append(f"<li><a href='{href}'>{html.escape(rel)}</a></li>")
    if not links:
        return "<p class='muted'>No supported files found.</p>"
    return "<ul>" + "".join(links) + "</ul>"


def create_app(
    *,
    repo_root: Path | None = None,
    truth_pack_root: Path | None = None,
    inbox_runs_root: Path | None = None,
    raw_root: Path | None = None,
) -> FastAPI:
    root = (repo_root or _repo_root_from_here()).resolve()
    roots = ViewerRoots(
        repo_root=root,
        truth_pack_root=(truth_pack_root or (root / "outputs" / "_truth_pack")).resolve(),
        inbox_runs_root=(inbox_runs_root or (root / "outputs" / "inbox_runs")).resolve(),
        raw_root=(raw_root or (root / "data" / "raw")).resolve(),
    )

    app = FastAPI(title="Truth Pack Thin Viewer", version="0.1.0")
    app.state.viewer_roots = roots

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"ok": "true"}

    @app.get("/", response_class=HTMLResponse)
    def home() -> str:
        current_roots: ViewerRoots = app.state.viewer_roots
        runs = _list_runs(current_roots)
        existing_runs = [run for run in runs if run.exists]

        run_items: list[str] = []
        for run in runs:
            run_link = f"/run/{quote(run.run_id, safe='')}"
            status = "" if run.exists else " <span class='muted'>(missing)</span>"
            run_items.append(f"<li><a href='{run_link}'>{html.escape(run.label)}</a>{status}</li>")

        options = []
        for run in existing_runs:
            options.append(f"<option value='{html.escape(run.run_id)}'>{html.escape(run.label)}</option>")
        form_html = (
            "<form action='/compare' method='get'>"
            "<label>Run A <select name='run_a'>"
            f"{''.join(options)}"
            "</select></label>"
            "<label>Run B <select name='run_b'>"
            f"{''.join(options)}"
            "</select></label>"
            "<button type='submit'>Compare</button>"
            "</form>"
        )

        manifest_items = []
        for manifest in _audit_manifests(current_roots):
            rel = manifest.relative_to(current_roots.raw_root).as_posix()
            href = f"/raw-manifest/{quote(rel, safe='/')}"
            manifest_items.append(f"<li><a href='{href}'>{html.escape(rel)}</a></li>")
        manifests_html = (
            "<ul>" + "".join(manifest_items) + "</ul>" if manifest_items else "<p class='muted'>No manifests found.</p>"
        )

        body = (
            "<h1>Truth Pack + Inbox Runs Viewer</h1>"
            "<p class='muted'>Local, deterministic viewer for existing artifacts. No report generation.</p>"
            "<h2>Runs</h2>"
            "<ul>"
            f"{''.join(run_items)}"
            "</ul>"
            "<h2>Compare Runs</h2>"
            f"{form_html}"
            "<h2>Audit Trail Manifests</h2>"
            f"{manifests_html}"
        )
        return _page("Truth Pack Viewer", body)

    @app.get("/run/{run_id}", response_class=HTMLResponse)
    def run_view(run_id: str) -> str:
        current_roots: ViewerRoots = app.state.viewer_roots
        run = _run_by_id(current_roots, run_id)
        files = _run_file_items(run.path)
        compare_note = ""
        if run.run_id != "truth_pack":
            qs = urlencode({"run_a": run.run_id, "run_b": "truth_pack"})
            compare_note = f"<p><a href='/compare?{qs}'>Compare this run with Truth Pack</a></p>"
        body = (
            f"<p><a href='/'>Back</a></p>"
            f"<h1>{html.escape(run.label)}</h1>"
            f"{compare_note}"
            f"{_link_list(files, run.run_id)}"
        )
        return _page(run.label, body)

    @app.get("/raw-manifest/{manifest_rel:path}", response_class=HTMLResponse)
    def raw_manifest_view(manifest_rel: str) -> str:
        current_roots: ViewerRoots = app.state.viewer_roots
        manifest_path = _resolve_under(current_roots.raw_root, manifest_rel)
        if manifest_path.name != "manifest.json":
            raise HTTPException(status_code=400, detail="only manifest.json files are allowed")
        if not manifest_path.is_file():
            raise HTTPException(status_code=404, detail="manifest not found")

        text = _read_text(manifest_path)
        try:
            pretty = json.dumps(json.loads(text), indent=2, sort_keys=True)
        except json.JSONDecodeError:
            pretty = text

        rel = manifest_path.relative_to(current_roots.raw_root).as_posix()
        body = (
            "<p><a href='/'>Back</a></p>"
            f"<h1>Raw Manifest: {html.escape(rel)}</h1>"
            f"<pre>{html.escape(pretty)}</pre>"
        )
        return _page(f"Raw Manifest {rel}", body)

    @app.get("/file/{run_id}/{rel_path:path}", response_class=HTMLResponse)
    def file_view(run_id: str, rel_path: str) -> HTMLResponse:
        current_roots: ViewerRoots = app.state.viewer_roots
        run = _run_by_id(current_roots, run_id)
        file_path = _resolve_under(run.path, rel_path)
        if not file_path.is_file():
            raise HTTPException(status_code=404, detail="file not found")

        suffix = file_path.suffix.lower()
        if suffix not in ALLOWED_VIEW_SUFFIXES:
            raise HTTPException(status_code=415, detail=f"unsupported file type: {suffix}")

        if suffix == ".html":
            return HTMLResponse(content=_read_text(file_path))

        file_text = _read_text(file_path)
        file_rel = file_path.relative_to(run.path).as_posix()

        if suffix == ".md":
            rendered = _render_markdown(file_text)
            body = (
                f"<p><a href='/run/{quote(run_id, safe='')}'>Back to run</a></p>"
                f"<h1>{html.escape(file_rel)}</h1>"
                f"{rendered}"
            )
            return HTMLResponse(content=_page(file_rel, body))

        if suffix == ".json":
            try:
                pretty = json.dumps(json.loads(file_text), indent=2, sort_keys=True)
            except json.JSONDecodeError:
                pretty = file_text
            body = (
                f"<p><a href='/run/{quote(run_id, safe='')}'>Back to run</a></p>"
                f"<h1>{html.escape(file_rel)}</h1>"
                f"<pre>{html.escape(pretty)}</pre>"
            )
            return HTMLResponse(content=_page(file_rel, body))

        body = (
            f"<p><a href='/run/{quote(run_id, safe='')}'>Back to run</a></p>"
            f"<h1>{html.escape(file_rel)}</h1>"
            f"<pre>{html.escape(file_text)}</pre>"
        )
        return HTMLResponse(content=_page(file_rel, body))

    @app.get("/compare", response_class=HTMLResponse)
    def compare_view(
        run_a: str = Query(...),
        run_b: str = Query(...),
        file: str | None = Query(default=None, alias="file"),
    ) -> str:
        current_roots: ViewerRoots = app.state.viewer_roots
        left = _run_by_id(current_roots, run_a)
        right = _run_by_id(current_roots, run_b)

        map_a = _compare_file_map(left.path)
        map_b = _compare_file_map(right.path)

        keys_a = set(map_a.keys())
        keys_b = set(map_b.keys())
        only_a = sorted(keys_a - keys_b)
        only_b = sorted(keys_b - keys_a)

        different: list[str] = []
        for rel in sorted(keys_a & keys_b):
            if map_a[rel][1] != map_b[rel][1]:
                different.append(rel)

        links = []
        for rel in different:
            qs = urlencode({"run_a": run_a, "run_b": run_b, "file": rel})
            links.append(f"<li><a href='/compare?{qs}'>{html.escape(rel)}</a></li>")
        different_html = "<ul>" + "".join(links) + "</ul>" if links else "<p class='muted'>No differences.</p>"

        only_a_html = "<ul>" + "".join(f"<li>{html.escape(item)}</li>" for item in only_a) + "</ul>"
        if not only_a:
            only_a_html = "<p class='muted'>None</p>"
        only_b_html = "<ul>" + "".join(f"<li>{html.escape(item)}</li>" for item in only_b) + "</ul>"
        if not only_b:
            only_b_html = "<p class='muted'>None</p>"

        diff_section = "<p class='muted'>Select a changed text file to view diff.</p>"
        if file:
            if file not in map_a or file not in map_b:
                diff_section = (
                    f"<h2>Diff: {html.escape(file)}</h2>"
                    "<p class='muted'>File is not present in both runs.</p>"
                )
            elif Path(file).suffix.lower() not in TEXT_DIFF_SUFFIXES:
                diff_section = (
                    f"<h2>Diff: {html.escape(file)}</h2>"
                    "<p class='muted'>Diff view supports .md, .txt, and .json only.</p>"
                )
            else:
                diff_text, truncated = _limited_diff(run_a, map_a[file][0], run_b, map_b[file][0], file)
                trunc_note = ""
                if truncated:
                    trunc_note = "<p class='muted'>Diff output truncated for readability.</p>"
                if not diff_text:
                    diff_text = "(No textual diff.)"
                diff_section = (
                    f"<h2>Diff: {html.escape(file)}</h2>"
                    f"{trunc_note}"
                    f"<pre>{html.escape(diff_text)}</pre>"
                )

        body = (
            "<p><a href='/'>Back</a></p>"
            f"<h1>Compare {html.escape(run_a)} vs {html.escape(run_b)}</h1>"
            "<div class='grid'>"
            "<div>"
            "<h2>Only in A</h2>"
            f"{only_a_html}"
            "</div>"
            "<div>"
            "<h2>Only in B</h2>"
            f"{only_b_html}"
            "</div>"
            "</div>"
            "<h2>Different Files (sha256)</h2>"
            f"{different_html}"
            f"{diff_section}"
        )
        return _page(f"Compare {run_a} vs {run_b}", body)

    return app


app = create_app()
