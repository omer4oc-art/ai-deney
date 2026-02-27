#!/usr/bin/env python3
"""List inbox files and show newest-per-report selection."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="List inbox files and newest selection candidates.")
    parser.add_argument(
        "--years",
        default="",
        help="Comma-separated years to select (example: 2025,2026). If omitted, uses years detected in inbox.",
    )
    parser.add_argument(
        "--inbox-root",
        default="",
        help="Optional inbox root path (default: data/inbox under repo root).",
    )
    return parser.parse_args()


def _parse_years(raw: str) -> list[int]:
    cleaned = str(raw or "").strip()
    if not cleaned:
        return []
    years: list[int] = []
    for token in cleaned.split(","):
        tok = token.strip()
        if not tok:
            continue
        years.append(int(tok))
    return sorted({int(y) for y in years})


def _repo_relative(path: Path, repo_root: Path) -> str:
    return path.resolve().relative_to(repo_root.resolve()).as_posix()


def main() -> int:
    args = _parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    src_root = repo_root / "src"
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    if str(src_root) not in sys.path:
        sys.path.insert(0, str(src_root))

    from ai_deney.inbox.scan import InboxScanError, scan_inbox_candidates, select_newest_for_years

    inbox_root: Path | None = None
    if str(args.inbox_root or "").strip():
        inbox_root = Path(args.inbox_root)
        if not inbox_root.is_absolute():
            inbox_root = repo_root / inbox_root
        inbox_root = inbox_root.resolve()

    years = _parse_years(args.years)

    try:
        candidates = scan_inbox_candidates(repo_root=repo_root, inbox_root=inbox_root)
    except InboxScanError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    effective_inbox_root = (inbox_root or (repo_root / "data" / "inbox")).resolve()
    print(f"inbox_root={_repo_relative(effective_inbox_root, repo_root)}")
    print(f"detected_files={len(candidates)}")

    if not candidates:
        print("no inbox files detected")
        return 0

    by_key: dict[tuple[str, str, int], list] = {}
    for candidate in candidates:
        key = (candidate.source, candidate.report_type, int(candidate.year))
        by_key.setdefault(key, []).append(candidate)

    for key in sorted(by_key.keys()):
        source, report_type, year = key
        print(f"\n[{source}:{report_type}:{year}]")
        items = sorted(
            by_key[key],
            key=lambda c: (c.report_date.isoformat(), c.mtime_ns, c.path.name),
            reverse=True,
        )
        for item in items:
            print(
                f"- {item.report_date.isoformat()} | size={item.size_bytes} | "
                f"mtime_ns={item.mtime_ns} | path={_repo_relative(item.path, repo_root)}"
            )

    if not years:
        years = sorted({int(c.year) for c in candidates})
    print(f"\nselection_years={years}")

    try:
        selected = select_newest_for_years(candidates, years=years, require_complete=False)
    except InboxScanError as exc:
        print(f"selection_error={exc}")
        return 2

    if not selected:
        print("selected_files=0")
        return 0

    print("selected_newest:")
    for item in selected:
        print(
            f"- {item.source}:{item.report_type}:{item.year} -> "
            f"{item.report_date.isoformat()} | {_repo_relative(item.path, repo_root)}"
        )

    try:
        select_newest_for_years(candidates, years=years, require_complete=True)
        print("required_reports=complete")
    except InboxScanError as exc:
        print(f"required_reports=incomplete ({exc})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
