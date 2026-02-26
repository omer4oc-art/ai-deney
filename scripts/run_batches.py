#!/usr/bin/env python3
import argparse
import json
import re
import html
import subprocess
from pathlib import Path

KNOWN_GATE_KEYS = [
    "PY_COMPILE_FAILED",
    "EXPECT_MISSING",
    "EXPECT_FORBID_HIT",
    "AST_TODO_FOUND",
    "AST_PASS_ONLY_FUNCTION",
    "AST_NO_DEFS_OR_CLASSES",
    "AST_COMMENTED_OUT_DUPLICATE_DEF",
]


def _slug(name: str, max_len: int = 40) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return (s[:max_len] or "task").rstrip("-")


def _load_gate_counts(outdir: Path) -> dict[str, int]:
    p = outdir / "gate_report.json"
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}
    gc = data.get("gate_counts", {})
    out: dict[str, int] = {}
    if isinstance(gc, dict):
        for k, v in gc.items():
            try:
                out[str(k)] = int(v)
            except Exception:
                continue
    return out


def _with_known_keys(gates: dict[str, int]) -> dict[str, int]:
    out = {k: int(gates.get(k, 0)) for k in KNOWN_GATE_KEYS}
    for k, v in (gates or {}).items():
        if k not in out:
            out[k] = int(v)
    return out


def _write_summary_html(outbase: Path, batches: list[dict], aggregate: dict[str, int]) -> None:
    rows = []
    for b in batches:
        status = "PASS" if int(b["exit_code"]) == 0 else f"FAIL({b['exit_code']})"
        gc = b.get("gate_counts", {}) or {}
        gc_nonzero = ", ".join(f"{k}:{v}" for k, v in sorted(gc.items()) if int(v) > 0) or "-"
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(b['name']))}</td>"
            f"<td>{html.escape(status)}</td>"
            f"<td>{html.escape(str(b['outdir']))}</td>"
            f"<td>{html.escape(str(b.get('index', '')))}</td>"
            f"<td>{html.escape(str(b.get('bundle', '')))}</td>"
            f"<td>{html.escape(str(b.get('gate_report', '')))}</td>"
            f"<td>{html.escape(str(b.get('transcript', '')))}</td>"
            f"<td>{html.escape(gc_nonzero)}</td>"
            "</tr>"
        )
    top = sorted(aggregate.items(), key=lambda kv: (-kv[1], kv[0]))[:10]
    gate_rows = "".join(
        f"<tr><td>{html.escape(k)}</td><td>{int(v)}</td></tr>"
        for k, v in top
    ) or "<tr><td colspan='2'>none</td></tr>"
    doc = (
        "<!doctype html><html><head><meta charset='utf-8'><title>Batch Summary</title>"
        "<style>body{font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Arial,sans-serif;margin:20px}"
        "table{border-collapse:collapse;width:100%}th,td{border:1px solid #ddd;padding:6px;text-align:left}"
        "th{background:#f4f4f4}</style></head><body>"
        "<h1>Batch Orchestrator Summary</h1>"
        "<h2>Batches</h2>"
        "<table><thead><tr><th>Batch</th><th>Status</th><th>Outdir</th><th>Index</th><th>Bundle</th><th>Gate report</th><th>Transcript</th><th>Gate counts</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
        "<h2>Aggregate Gates (Top 10)</h2>"
        f"<table><thead><tr><th>Gate</th><th>Count</th></tr></thead><tbody>{gate_rows}</tbody></table>"
        "</body></html>"
    )
    (outbase / "summary.html").write_text(doc, encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="Run multiple task files as separate batches.")
    ap.add_argument("tasks_dir")
    ap.add_argument("--outbase", required=True)
    ap.add_argument("--stub-model", default="")
    ap.add_argument("--repair-retries", type=int, default=0)
    ap.add_argument("--record-transcript", action="store_true")
    ap.add_argument("--bundle", action="store_true")
    fail_mode = ap.add_mutually_exclusive_group()
    fail_mode.add_argument("--continue-on-fail", action="store_true", help="Run all batches even if a batch fails.")
    fail_mode.add_argument("--fail-fast", action="store_true", help="Stop immediately when a batch fails (default behavior).")
    ap.add_argument("--html", action="store_true")
    args = ap.parse_args()

    tasks_dir = Path(args.tasks_dir)
    outbase = Path(args.outbase)
    outbase.mkdir(parents=True, exist_ok=True)
    task_files = sorted([p for p in tasks_dir.glob("*.md") if p.is_file()])
    if not task_files:
        print(f"no_task_files_found={tasks_dir}")
        return 2

    batches: list[dict] = []
    agg_gate_counts: dict[str, int] = {k: 0 for k in KNOWN_GATE_KEYS}
    any_fail = False

    stop_on_fail = args.fail_fast or (not args.continue_on_fail)

    for idx, tf in enumerate(task_files, start=1):
        outdir = outbase / f"batch_{idx:03d}_{_slug(tf.stem)}"
        cmd = [
            "python3",
            "batch_agent.py",
            "--chat",
            "--tasks-format",
            "blocks",
            "--repair-retries",
            str(args.repair_retries),
            "--outdir",
            str(outdir),
            str(tf),
        ]
        if args.stub_model:
            cmd.extend(["--stub-model", args.stub_model])
        if args.record_transcript:
            cmd.append("--record-transcript")
        if args.bundle:
            cmd.append("--bundle")

        p = subprocess.run(cmd, capture_output=True, text=True)
        code = int(p.returncode)
        if code != 0:
            any_fail = True
        gates = _with_known_keys(_load_gate_counts(outdir))
        for k, v in gates.items():
            agg_gate_counts[k] = agg_gate_counts.get(k, 0) + int(v)

        rec = {
            "name": tf.name,
            "taskfile": str(tf),
            "outdir": str(outdir),
            "exit_code": code,
            "index": str(outdir / "index.md") if (outdir / "index.md").exists() else "",
            "gate_report": str(outdir / "gate_report.json") if (outdir / "gate_report.json").exists() else "",
            "transcript": str(outdir / "transcript.jsonl") if (outdir / "transcript.jsonl").exists() else "",
            "bundle": str(outdir / "bundle.txt") if (outdir / "bundle.txt").exists() else "",
            "gate_counts": gates,
            "stdout_tail": "\n".join((p.stdout or "").splitlines()[-20:]),
            "stderr_tail": "\n".join((p.stderr or "").splitlines()[-20:]),
        }
        batches.append(rec)
        if code != 0 and stop_on_fail:
            break

    summary_json = {
        "tasks_dir": str(tasks_dir),
        "outbase": str(outbase),
        "known_gate_keys": KNOWN_GATE_KEYS,
        "batches": batches,
        "gate_counts": agg_gate_counts,
        "aggregate_gate_counts": agg_gate_counts,
    }
    (outbase / "summary.json").write_text(json.dumps(summary_json, indent=2) + "\n", encoding="utf-8")

    lines = ["# Batch Orchestrator Summary", ""]
    lines.append("| Batch | Status | Outdir | Index | Bundle | Gate Report | Transcript | Gate Counts |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for b in batches:
        status = "PASS" if int(b["exit_code"]) == 0 else f"FAIL({b['exit_code']})"
        gc = b.get("gate_counts", {}) or {}
        gc_txt = ", ".join(f"{k}:{v}" for k, v in sorted(gc.items()) if int(v) > 0) if gc else "-"
        if not gc_txt:
            gc_txt = "-"
        lines.append(
            f"| {b['name']} | {status} | {b['outdir']} | {b.get('index','')} | {b.get('bundle','')} | {b.get('gate_report','')} | {b.get('transcript','')} | {gc_txt} |"
        )
    lines.append("")
    lines.append("## Aggregate Gate Counts (Top 10)")
    top = sorted(agg_gate_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:10]
    if top:
        lines.append("| Gate | Count |")
        lines.append("|---|---|")
        for k, v in top:
            lines.append(f"| {k} | {v} |")
    else:
        lines.append("- none")
    lines.append("")
    lines.append("## Failures")
    failed = [b for b in batches if int(b.get("exit_code", 0)) != 0]
    if failed:
        for b in failed:
            lines.append(f"- {b['name']}: exit_code={b['exit_code']} outdir={b['outdir']}")
    else:
        lines.append("- none")
    (outbase / "summary.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    if args.html:
        _write_summary_html(outbase, batches, agg_gate_counts)

    return 1 if any_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
