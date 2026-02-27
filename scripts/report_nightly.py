#!/usr/bin/env python3
import argparse
import json
from datetime import datetime
from pathlib import Path
from urllib import request


def _load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    if not path.exists():
        return rows
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        s = raw.strip()
        if not s:
            continue
        try:
            rows.append(json.loads(s))
        except Exception:
            continue
    return rows


def _aggregate_gate_counts(runs_dir: Path) -> dict[str, int]:
    out: dict[str, int] = {}
    for p in sorted(runs_dir.glob("iter-*/gate_report.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        gc = data.get("gate_counts", {})
        if not isinstance(gc, dict):
            continue
        for k, v in gc.items():
            try:
                out[str(k)] = out.get(str(k), 0) + int(v)
            except Exception:
                continue
    return out


def _model_tags_snippet() -> str:
    url = "http://127.0.0.1:11434/api/tags"
    try:
        with request.urlopen(url, timeout=1.0) as resp:
            if getattr(resp, "status", None) != 200:
                return "ollama_tags=unavailable"
            body = resp.read().decode("utf-8", errors="replace")
        data = json.loads(body)
        models = data.get("models", [])
        if not isinstance(models, list) or not models:
            return "ollama_tags=none"
        names: list[str] = []
        for m in models[:5]:
            if isinstance(m, dict):
                n = str(m.get("name", "")).strip()
                if n:
                    names.append(n)
        return "ollama_tags=" + (", ".join(names) if names else "none")
    except Exception:
        return "ollama_tags=unreachable"


def main() -> int:
    ap = argparse.ArgumentParser(description="Write nightly soak/real-lane report.")
    ap.add_argument("--soak-dir", required=True)
    ap.add_argument("--real-outdir", default="")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    soak_dir = Path(args.soak_dir)
    summary_path = soak_dir / "soak_summary.jsonl"
    rows = _load_jsonl(summary_path)
    total = len(rows)
    failures = sum(1 for r in rows if str(r.get("status", "")).upper() == "FAIL")
    gate_counts = _aggregate_gate_counts(soak_dir / "runs")
    top = sorted(gate_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:10]

    lines: list[str] = []
    lines.append(f"timestamp={datetime.now().isoformat()}")
    lines.append(f"soak_dir={soak_dir}")
    lines.append(f"iterations={total}")
    lines.append(f"failures={failures}")
    lines.append("top_gates:")
    if top:
        for k, v in top:
            lines.append(f"- {k}: {v}")
    else:
        lines.append("- none")

    if args.real_outdir:
        real = Path(args.real_outdir)
        index_path = real / "index.md"
        bundle_path = real / "bundle.txt"
        transcript_path = real / "transcript.jsonl"
        gate_path = real / "gate_report.json"
        passed = index_path.exists() and bundle_path.exists() and transcript_path.exists()
        if any(real.glob("*.error.txt")):
            passed = False
        lines.append(f"real_outdir={real}")
        lines.append(f"real_passed={1 if passed else 0}")
        lines.append(f"real_index={index_path if index_path.exists() else 'missing'}")
        lines.append(f"real_bundle={bundle_path if bundle_path.exists() else 'missing'}")
        lines.append(f"real_transcript={transcript_path if transcript_path.exists() else 'missing'}")
        lines.append(f"real_gate_report={gate_path if gate_path.exists() else 'missing'}")
        lines.append(_model_tags_snippet())

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
