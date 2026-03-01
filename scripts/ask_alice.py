#!/usr/bin/env python3
"""Developer CLI: ask toy portal questions with deterministic execution."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ask toy portal reports from natural language.")
    parser.add_argument("question", nargs="+", help="Question text, e.g. 'sales by channel for March 2025'")
    parser.add_argument("--out", required=True, help="Output report path (must be inside repo root)")
    parser.add_argument("--format", choices=["md", "html"], default="md", help="Output format (default: md)")
    parser.add_argument("--db", default=None, help="Optional path to toy portal SQLite db")
    parser.add_argument("--redact-pii", action="store_true", help="Force redact_pii=true when executing the query")
    parser.add_argument(
        "--record-transcript",
        default="",
        help="Optional output path for parse transcript JSON (question/raw_llm_json/validated_query_spec)",
    )
    parser.add_argument(
        "--replay-transcript",
        default="",
        help="Optional input path for parse transcript JSON (replay validated_query_spec)",
    )
    return parser.parse_args()


def _assert_within_repo(path: Path, repo_root: Path) -> None:
    try:
        path.resolve().relative_to(repo_root.resolve())
    except Exception as exc:
        raise ValueError(f"output path escapes repo root: {path}") from exc


def _load_replay_spec(transcript_path: Path, question: str):
    if not transcript_path.exists():
        raise ValueError(f"replay transcript not found: {transcript_path}")
    try:
        payload = json.loads(transcript_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"invalid replay transcript JSON: {transcript_path}") from exc
    if not isinstance(payload, dict):
        raise ValueError("replay transcript must be a JSON object")

    recorded_question = str(payload.get("question") or "")
    if recorded_question != question:
        raise ValueError(
            "REPLAY_QUESTION_MISMATCH: "
            f"expected question={recorded_question!r} got={question!r}"
        )

    validated_spec = payload.get("validated_query_spec")
    if not isinstance(validated_spec, dict):
        raise ValueError("replay transcript missing validated_query_spec JSON object")

    from ai_deney.intent.toy_intent import validate_query_spec

    return validate_query_spec(validated_spec, question_text=question)


def _write_record_transcript(path: Path, question: str, raw_llm_json: dict[str, object] | None, spec) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "question": question,
        "raw_llm_json": raw_llm_json,
        "validated_query_spec": spec.to_dict(),
    }
    path.write_text(json.dumps(row, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    args = _parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    src_root = repo_root / "src"
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    if str(src_root) not in sys.path:
        sys.path.insert(0, str(src_root))

    from ai_deney.intent.toy_intent import parse_toy_query_with_trace, resolve_intent_mode
    from ai_deney.reports.toy_reports import answer_ask_from_spec

    question = " ".join(args.question).strip()
    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = repo_root / out_path
    out_path = out_path.resolve()
    _assert_within_repo(out_path, repo_root)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if args.record_transcript and args.replay_transcript:
        raise ValueError("use only one of --record-transcript or --replay-transcript")

    db_path = None
    if args.db:
        db_path = Path(args.db)
        if not db_path.is_absolute():
            db_path = repo_root / db_path
        db_path = db_path.resolve()

    ask_format = "md" if args.format == "md" else "html"

    replay_path = Path(args.replay_transcript).resolve() if args.replay_transcript else None
    record_path = Path(args.record_transcript).resolve() if args.record_transcript else None

    if replay_path is not None:
        spec = _load_replay_spec(replay_path, question)
        raw_llm_json = None
        intent_mode = "replay"
    else:
        parsed = parse_toy_query_with_trace(question)
        spec = parsed.spec
        raw_llm_json = parsed.raw_llm_json
        intent_mode = resolve_intent_mode(None)

    result = answer_ask_from_spec(
        spec,
        format=ask_format,
        db_path=db_path,
        redact_pii=bool(args.redact_pii),
        intent_mode=intent_mode,
    )

    if record_path is not None:
        _write_record_transcript(record_path, question, raw_llm_json, spec)

    out_path.write_text(str(result["output"]), encoding="utf-8")
    print(f"WROTE: {out_path}")
    print(f"INTENT_MODE: {intent_mode}")
    print(f"REPORT_TYPE: {result['meta']['report_type']}")
    print(f"RANGE: {result['meta']['start']}..{result['meta']['end']}")
    if result["meta"].get("total_sales") is not None:
        print(f"TOTAL_SALES: {float(result['meta']['total_sales']):.2f}")
    if result["meta"].get("occupancy_pct") is not None:
        print(f"OCCUPANCY_PCT: {float(result['meta']['occupancy_pct']):.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
