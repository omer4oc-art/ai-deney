#!/usr/bin/env python3
"""Generate deterministic offline Electra + HotelRunner truth-pack reports."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


QUESTIONS = [
    "get me the sales data of 2025",
    "get me the sales data of 2026",
    "get me the sales data of 2026 and 2025",
    "get me the sales categorized by agencies for 2025",
    "get me the sales categorized by agencies for 2026",
    "compare 2025 vs 2026 by agency",
    "sales by month for 2025",
    "sales by month for 2026",
    "top agencies in 2026",
    "share of direct vs agencies in 2025",
    "compare electra vs hotelrunner for 2025",
    "compare electra vs hotelrunner for 2026",
    "where do electra and hotelrunner differ in 2025",
    "where do electra and hotelrunner differ in 2026",
]


def _slug(i: int, question: str) -> str:
    raw = question.lower()
    out = []
    for ch in raw:
        if ch.isalnum():
            out.append(ch)
        elif ch in {" ", "-", "_"}:
            out.append("_")
    slug = "".join(out).strip("_")
    while "__" in slug:
        slug = slug.replace("__", "_")
    return f"{i:02d}_{slug[:48]}"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate deterministic Electra + HotelRunner truth-pack reports.")
    parser.add_argument(
        "--outdir",
        "--out",
        dest="outdir",
        default="outputs/_truth_pack",
        help="Output directory inside repo (default: outputs/_truth_pack)",
    )
    return parser.parse_args()


def _assert_within_repo(path: Path, repo_root: Path) -> None:
    try:
        path.resolve().relative_to(repo_root.resolve())
    except Exception as exc:
        raise ValueError(f"path escapes repo root: {path}") from exc


def main() -> int:
    args = _parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    src_root = repo_root / "src"
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    if str(src_root) not in sys.path:
        sys.path.insert(0, str(src_root))
    from ai_deney.reports.electra_reports import answer_question

    outdir = Path(args.outdir)
    if not outdir.is_absolute():
        outdir = repo_root / outdir
    outdir = outdir.resolve()
    _assert_within_repo(outdir, repo_root)
    outdir.mkdir(parents=True, exist_ok=True)
    normalized_root = outdir / "_normalized"

    entries: list[dict] = []
    for i, question in enumerate(QUESTIONS, start=1):
        slug = _slug(i, question)
        md_path = outdir / f"{slug}.md"
        html_path = outdir / f"{slug}.html"
        md_path.write_text(
            answer_question(question, normalized_root=normalized_root, output_format="markdown"),
            encoding="utf-8",
        )
        html_path.write_text(
            answer_question(question, normalized_root=normalized_root, output_format="html"),
            encoding="utf-8",
        )
        entries.append({"question": question, "md": md_path.name, "html": html_path.name})

    index_lines = ["# Hotel Truth Pack v1", "", "Deterministic Electra + HotelRunner mock report pack.", ""]
    for idx, entry in enumerate(entries, start=1):
        index_lines.append(f"## Q{idx}")
        index_lines.append(f"- question: {entry['question']}")
        index_lines.append(f"- md: [{entry['md']}]({entry['md']})")
        index_lines.append(f"- html: [{entry['html']}]({entry['html']})")
        index_lines.append("")
    index_path = outdir / "index.md"
    index_path.write_text("\n".join(index_lines).strip() + "\n", encoding="utf-8")

    bundle_lines = ["# Truth Pack Bundle", "", f"Included reports: {len(entries)}", ""]
    ordered = [index_path] + [outdir / e["md"] for e in entries] + [outdir / e["html"] for e in entries]
    for path in ordered:
        rel = path.relative_to(outdir)
        bundle_lines.append(f"===== FILE: {rel} =====")
        bundle_lines.append(path.read_text(encoding="utf-8"))
        bundle_lines.append("")
    bundle_path = outdir / "bundle.txt"
    bundle_path.write_text("\n".join(bundle_lines).strip() + "\n", encoding="utf-8")

    print(f"WROTE: {index_path.resolve()}")
    print(f"WROTE: {bundle_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
