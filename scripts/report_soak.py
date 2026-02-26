#!/usr/bin/env python3
import argparse
import json
import statistics
from pathlib import Path


def _load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        s = raw.strip()
        if not s:
            continue
        try:
            rows.append(json.loads(s))
        except Exception:
            continue
    return rows


def main() -> int:
    p = argparse.ArgumentParser(description="Summarize soak run outputs.")
    p.add_argument("soak_dir", help="Path to soak run directory")
    p.add_argument("--top", type=int, default=10, help="Top gate codes to print")
    args = p.parse_args()

    soak_dir = Path(args.soak_dir)
    summary_path = soak_dir / "soak_summary.jsonl"
    if not summary_path.exists():
        print(f"missing_summary={summary_path}")
        return 1

    rows = _load_jsonl(summary_path)
    total = len(rows)
    failures = [r for r in rows if str(r.get("status", "")).upper() == "FAIL"]
    fail_iters = [int(r.get("iteration", 0)) for r in failures if int(r.get("iteration", 0)) > 0]
    durations = [int(r.get("duration_seconds", 0)) for r in rows]
    avg_dur = round(sum(durations) / max(1, len(durations)), 3)
    med_dur = round(float(statistics.median(durations)), 3) if durations else 0.0

    slowest = None
    for r in rows:
        d = int(r.get("duration_seconds", 0))
        if slowest is None or d > int(slowest.get("duration_seconds", 0)):
            slowest = r

    print(f"total_iterations={total}")
    print(f"failures={len(failures)}")
    print("failure_iterations=" + (",".join(str(x) for x in fail_iters) if fail_iters else "none"))
    print(f"avg_duration_seconds={avg_dur}")
    print(f"median_duration_seconds={med_dur}")
    if slowest is not None:
        print(f"slowest_iteration={int(slowest.get('iteration', 0))}")
        print(f"slowest_duration_seconds={int(slowest.get('duration_seconds', 0))}")
        print(f"slowest_log_path={slowest.get('log_path', '')}")

    gate_counts: dict[str, int] = {}
    for rp in sorted((soak_dir / "runs").glob("iter-*/gate_report.json")):
        try:
            data = json.loads(rp.read_text(encoding="utf-8"))
        except Exception:
            continue
        gc = data.get("gate_counts", {})
        if not isinstance(gc, dict):
            continue
        for k, v in gc.items():
            try:
                n = int(v)
            except Exception:
                continue
            gate_counts[str(k)] = gate_counts.get(str(k), 0) + n

    if gate_counts:
        print(f"gate_total_unique={len(gate_counts)}")
        print(f"gate_total_events={sum(gate_counts.values())}")
        for code, n in sorted(gate_counts.items(), key=lambda kv: (-kv[1], kv[0]))[: max(1, args.top)]:
            print(f"GATE {code} {n}")
    else:
        print("no_gate_reports_found=1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
