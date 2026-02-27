#!/usr/bin/env python3
"""Generate deterministic offline Electra + HotelRunner truth-pack reports."""

from __future__ import annotations

import argparse
import re
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
    "electra vs hotelrunner monthly reconciliation for 2025",
    "electra vs hotelrunner monthly reconciliation for 2026",
    "where do electra and hotelrunner differ by agency in 2025",
    "where do electra and hotelrunner differ by agency in 2026",
    "monthly reconciliation by agency 2025 electra hotelrunner",
    "monthly reconciliation by agency 2026 electra hotelrunner",
    "any anomalies by agency in 2025",
    "any anomalies by agency in 2026",
    "mapping health report 2025",
    "mapping health report 2026",
    "which agencies are unmapped in 2026",
    "agency drift electra vs hotelrunner 2025",
    "mapping explain agency 2025",
    "mapping explain agency 2026",
    "mapping unknown rate improvement 2025",
    "mapping unknown rate improvement 2026",
]

REQUIRED_INBOX_REPORT_KEYS = (
    ("electra", "sales_summary"),
    ("electra", "sales_by_agency"),
    ("hotelrunner", "daily_sales"),
)


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
    parser.add_argument(
        "--use-inbox",
        type=int,
        default=0,
        choices=[0, 1],
        help="Use inbox drop-folder ingestion when set to 1; behavior depends on --inbox-policy.",
    )
    parser.add_argument(
        "--inbox-root",
        default="",
        help="Optional custom inbox root (defaults to data/inbox under repo root).",
    )
    parser.add_argument(
        "--max-inbox-mb",
        type=float,
        default=25.0,
        help="Max accepted inbox file size in MB (default: 25).",
    )
    parser.add_argument(
        "--inbox-policy",
        default="strict",
        choices=["strict", "partial"],
        help=(
            "Inbox coverage policy when --use-inbox=1. "
            "'strict' requires all years used by truth-pack questions; "
            "'partial' ingests complete years only and skips unsupported questions."
        ),
    )
    return parser.parse_args()


def _assert_within_repo(path: Path, repo_root: Path) -> None:
    try:
        path.resolve().relative_to(repo_root.resolve())
    except Exception as exc:
        raise ValueError(f"path escapes repo root: {path}") from exc


def _extract_years(text: str) -> list[int]:
    return sorted({int(m) for m in re.findall(r"\b(20\d{2})\b", text)})


def _question_years(questions: list[str]) -> list[int]:
    years: set[int] = set()
    for question in questions:
        years.update(_extract_years(question))
    if not years:
        raise ValueError("unable to infer requested years from truth-pack questions")
    return sorted(years)


def _filter_questions_for_years(
    questions: list[str],
    allowed_years: set[int],
) -> tuple[list[str], list[dict[str, object]]]:
    selected: list[str] = []
    skipped: list[dict[str, object]] = []
    for question in questions:
        q_years = _extract_years(question)
        if q_years and not set(q_years).issubset(allowed_years):
            skipped.append({"question": question, "required_years": q_years})
            continue
        selected.append(question)
    return selected, skipped


def _format_years(years: list[int]) -> str:
    uniq = sorted({int(y) for y in years})
    return "[" + ", ".join(str(y) for y in uniq) + "]"


def _complete_years_from_candidates(candidates: list[object], years: list[int]) -> list[int]:
    years_i = sorted({int(y) for y in years})
    available = {
        (str(getattr(candidate, "source")), str(getattr(candidate, "report_type")), int(getattr(candidate, "year")))
        for candidate in candidates
        if int(getattr(candidate, "year")) in years_i
    }
    complete: list[int] = []
    for year in years_i:
        if all((source, report_type, year) in available for source, report_type in REQUIRED_INBOX_REPORT_KEYS):
            complete.append(year)
    return complete


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
    selected_questions = list(QUESTIONS)
    skipped_questions: list[dict[str, object]] = []
    index_notes: list[str] = []
    fallback_reason: str | None = None

    if int(args.use_inbox) == 1:
        from ai_deney.inbox.ingest import ingest_inbox_for_years
        from ai_deney.inbox.scan import InboxNoFilesError, InboxScanError, scan_inbox_candidates
        from ai_deney.inbox.validate import InboxValidationError

        years = _question_years(QUESTIONS)
        index_notes.append(f"Inbox policy: {args.inbox_policy}")
        inbox_root: Path | None = None
        if str(args.inbox_root or "").strip():
            inbox_root = Path(args.inbox_root)
            if not inbox_root.is_absolute():
                inbox_root = repo_root / inbox_root
            inbox_root = inbox_root.resolve()
            _assert_within_repo(inbox_root, repo_root)
        max_file_size_bytes = max(1, int(float(args.max_inbox_mb) * 1024 * 1024))

        if args.inbox_policy == "strict":
            try:
                ingest_result = ingest_inbox_for_years(
                    years=years,
                    repo_root=repo_root,
                    inbox_root=inbox_root,
                    max_file_size_bytes=max_file_size_bytes,
                )
                normalized_root = ingest_result.normalized_root
                print(f"INBOX: using run_id={ingest_result.run_id}")
                print(f"INBOX: manifest={ingest_result.manifest_path.resolve()}")
                index_notes.append(
                    "SOURCE: inbox; ingested years: "
                    + _format_years(years)
                    + "; skipped years: []"
                )
            except (InboxNoFilesError, InboxScanError, InboxValidationError, ValueError) as exc:
                print(f"INBOX: {exc}")
                print("INBOX: falling back to deterministic fixtures")
                fallback_reason = str(exc)
                index_notes.append("SOURCE: fixtures (inbox fallback)")
                skipped_questions = []
        else:
            complete_years: list[int] = []
            try:
                candidates = scan_inbox_candidates(repo_root=repo_root, inbox_root=inbox_root)
                complete_years = _complete_years_from_candidates(candidates=candidates, years=years)
                skipped_years = [year for year in years if year not in complete_years]

                if complete_years:
                    ingest_result = ingest_inbox_for_years(
                        years=complete_years,
                        repo_root=repo_root,
                        inbox_root=inbox_root,
                        max_file_size_bytes=max_file_size_bytes,
                    )
                    normalized_root = ingest_result.normalized_root
                    print(f"INBOX: using run_id={ingest_result.run_id}")
                    print(f"INBOX: manifest={ingest_result.manifest_path.resolve()}")
                else:
                    print("INBOX: partial policy found no complete years; skipping inbox ingestion")

                if skipped_years:
                    print(
                        "INBOX: partial policy skipped years with missing inbox files: "
                        + ", ".join(str(y) for y in skipped_years)
                    )

                index_notes.append(
                    "SOURCE: inbox; ingested years: "
                    + _format_years(complete_years)
                    + "; skipped years: "
                    + _format_years(skipped_years)
                )

                selected_questions, skipped_questions = _filter_questions_for_years(
                    QUESTIONS,
                    allowed_years=set(complete_years),
                )
                if skipped_questions:
                    print(
                        "INBOX: partial policy skipped "
                        + str(len(skipped_questions))
                        + " question(s) due to missing inbox years"
                    )
            except (InboxNoFilesError, InboxScanError, InboxValidationError, ValueError) as exc:
                print(f"INBOX: {exc}")
                print("INBOX: falling back to deterministic fixtures")
                fallback_reason = str(exc)
                index_notes.append("SOURCE: fixtures (inbox fallback)")
                selected_questions = list(QUESTIONS)
                skipped_questions = []

    entries: list[dict] = []
    for i, question in enumerate(selected_questions, start=1):
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
    if index_notes:
        index_lines.append("## Inbox Notes")
        for note in index_notes:
            index_lines.append(f"- {note}")
        if fallback_reason:
            index_lines.append(f"- Inbox fallback reason: {fallback_reason}")
        index_lines.append("")
    if skipped_questions:
        index_lines.append("## Skipped Questions")
        for skipped in skipped_questions:
            years_str = _format_years(list(skipped["required_years"]))
            index_lines.append(f"- Skipped: {skipped['question']} (requires years: {years_str})")
        index_lines.append("")
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
