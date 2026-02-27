#!/usr/bin/env python3
"""Developer CLI: ask deterministic Electra reports from natural language."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ask Electra mock reports from plain-English questions.")
    parser.add_argument("question", nargs="+", help="Question text, e.g. 'get me the sales data of 2026 and 2025'")
    parser.add_argument("--out", required=True, help="Output report path (must be inside repo root)")
    parser.add_argument("--format", choices=["md", "html"], default="md", help="Output format (default: md)")
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
    from ai_deney.reports.electra_reports import answer_question

    question = " ".join(args.question).strip()
    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = repo_root / out_path
    out_path = out_path.resolve()

    _assert_within_repo(out_path, repo_root)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    output_format = "markdown" if args.format == "md" else "html"
    normalized_root = out_path.parent / "_normalized"
    rendered = answer_question(question, normalized_root=normalized_root, output_format=output_format)
    out_path.write_text(rendered, encoding="utf-8")
    print(f"WROTE: {out_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
