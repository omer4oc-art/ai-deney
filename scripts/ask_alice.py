#!/usr/bin/env python3
"""Developer CLI: ask deterministic toy portal sales questions in plain English."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ask deterministic toy portal sales reports from natural language.")
    parser.add_argument("question", nargs="+", help="Question text, e.g. 'march 2025 sales data'")
    parser.add_argument("--out", required=True, help="Output report path (must be inside repo root)")
    parser.add_argument("--format", choices=["md", "html"], default="md", help="Output format (default: md)")
    parser.add_argument("--db", default=None, help="Optional path to toy portal SQLite db")
    parser.add_argument("--redact-pii", action="store_true", help="Set redact_pii=1 when executing the query")
    return parser.parse_args()


def _assert_within_repo(path: Path, repo_root: Path) -> None:
    try:
        path.resolve().relative_to(repo_root.resolve())
    except Exception as exc:
        raise ValueError(f"output path escapes repo root: {path}") from exc


def main() -> int:
    args = _parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    src_root = repo_root / "src"
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    if str(src_root) not in sys.path:
        sys.path.insert(0, str(src_root))

    from ai_deney.reports.toy_reports import answer_with_metadata

    question = " ".join(args.question).strip()
    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = repo_root / out_path
    out_path = out_path.resolve()
    _assert_within_repo(out_path, repo_root)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    db_path = None
    if args.db:
        db_path = Path(args.db)
        if not db_path.is_absolute():
            db_path = repo_root / db_path
        db_path = db_path.resolve()

    output_format = "markdown" if args.format == "md" else "html"
    result = answer_with_metadata(
        question,
        db_path=db_path,
        output_format=output_format,
        redact_pii=bool(args.redact_pii),
    )
    out_path.write_text(str(result["report"]), encoding="utf-8")
    print(f"WROTE: {out_path}")
    print(f"QUERY_TYPE: {result['metadata']['query_type']}")
    print(f"RANGE: {result['metadata']['start']}..{result['metadata']['end']}")
    print(f"TOTAL_SALES: {result['metadata']['total_sales']:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
