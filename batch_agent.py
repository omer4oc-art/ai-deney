import argparse
import json
import re
import shlex
import subprocess
from datetime import datetime
from pathlib import Path

from ollama_client import generate, OllamaNotRunning
from agent_json import run as run_json_agent
from memory_agent import run as run_memory_agent
from memory import memory_as_context
from run_logger import log_run
from file_tools import read_text, write_text


def _slug(s: str, max_len: int = 60) -> str:
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return (s[:max_len].rstrip("-")) or "task"


def _parse_task_line(line: str) -> tuple[str | None, str]:
    """
    Supports:
      - normal task line
      - FILE=path task...
      - FILE="path with spaces" task...
    Returns: (file_path_or_none, task_text)
    """
    line = line.strip()
    if not line or line.startswith("#"):
        return None, ""

    parts = shlex.split(line)
    if not parts:
        return None, ""

    file_path = None
    if parts[0].startswith("FILE="):
        file_path = parts[0].split("=", 1)[1].strip()
        task_text = " ".join(parts[1:]).strip()
        if not task_text:
            task_text = "Summarize the file."
        return file_path, task_text

    return None, line


def _load_tasks(path: str) -> list[tuple[str | None, str]]:
    text = read_text(path, max_chars=300_000)
    tasks: list[tuple[str | None, str]] = []
    for raw in text.splitlines():
        fp, task = _parse_task_line(raw)
        if task:
            tasks.append((fp, task))
    return tasks


def _render_md(title: str, bullets: list[str]) -> str:
    lines = []
    title = title.strip()
    if title:
        lines.append(f"# {title}")
        lines.append("")
    for b in bullets:
        b = str(b).strip()
        if b:
            lines.append(f"- {b}")
    return "\n".join(lines).strip() + "\n"


def _extract_from_md(md_text: str) -> tuple[str, list[str]]:
    """
    Very simple parser: first markdown heading becomes title, '- ' lines become bullets.
    """
    title = ""
    bullets: list[str] = []
    for line in md_text.splitlines():
        line = line.rstrip()
        if not title and line.startswith("#"):
            title = line.lstrip("#").strip()
        if line.startswith("- "):
            b = line[2:].strip()
            if b:
                bullets.append(b)
    return title, bullets


def _open_in_vscode(path: Path) -> None:
    try:
        subprocess.run(["code", str(path)], check=False)
    except Exception:
        pass

STOPWORDS = {
    "the","a","an","and","or","to","of","in","on","for","with","is","are","was","were",
    "be","as","at","by","from","this","that","it","its","your","you","we","our","i",
    "explain","summarize","rewrite","provide","include","add","make","give","why","how",
    "simple","terms","bullets","bullet","points","point","paragraph","use","uses","usage"
}

DRIFT_WORDS = {
    # common “product/ingredient” drift you hit earlier
    "ingredient","ingredients","nutrition","nutritional","calorie","calories","sugar",
    "caffeine","aspartame","hfcs","corn syrup","allergen","allergens","preservative",
    "label","packaging","mg","grams","serving"
}

def _keywords(text: str) -> set[str]:
    text = text.lower()
    words = re.findall(r"[a-z0-9]+", text)
    return {w for w in words if len(w) >= 3 and w not in STOPWORDS}

def topic_guard(task_text: str, output_title: str, output_bullets: list[str]) -> tuple[bool, str]:
    """
    Returns (is_off_topic, reason).
    Heuristic: if task keywords barely appear in output AND drift words appear, flag it.
    """
    task_keys = _keywords(task_text)
    out_text = (output_title or "") + " " + " ".join(output_bullets or [])
    out_text_l = out_text.lower()
    out_keys = _keywords(out_text)

    if not task_keys:
        return False, "no task keywords"

    overlap = task_keys.intersection(out_keys)
    overlap_ratio = len(overlap) / max(1, len(task_keys))

    drift_hits = [w for w in DRIFT_WORDS if w in out_text_l]

    # Thresholds tuned for short tasks
    too_low_overlap = overlap_ratio < 0.15 and len(overlap) <= 1
    has_drift = len(drift_hits) >= 2

    if too_low_overlap and has_drift:
        return True, f"low keyword overlap ({len(overlap)}/{len(task_keys)}); drift words: {', '.join(drift_hits[:6])}"

    return False, f"ok overlap ({len(overlap)}/{len(task_keys)})"

def main():
    parser = argparse.ArgumentParser(description="Batch runner for your local agent (supports FILE=... tasks).")
    parser.add_argument("tasks_file", help="Text file with one task per line (blank lines and #comments ignored).")

    # Mode selection
    parser.add_argument("--chat", action="store_true", help="Plain text (chat) mode.")
    parser.add_argument("--use-memory", action="store_true", help="Force memory mode (grounded).")
    parser.add_argument("--router", action="store_true", help="Router: memory only used when --memory-query is provided and memory exists.")

    # Controls
    parser.add_argument("--memory-query", default="", help="Filter memory context by keyword (e.g., week1).")
    parser.add_argument("--memory-limit", type=int, default=10, help="How many memory items to include.")
    parser.add_argument("--strict", action="store_true", help="Don't guess facts (JSON modes).")
    parser.add_argument("--verify", action="store_true", help="Add claims_to_verify/how_to_verify (JSON modes).")
    parser.add_argument("--bullets", type=int, default=0, help="Force number of bullets (0 = model decides).")

    # Output
    parser.add_argument("--outdir", default="", help="Output directory (relative to project). Default outputs/batch-<timestamp>/")
    parser.add_argument("--format", choices=["json", "md"], default="md", help="Per-task output format for JSON modes.")

    # NEW: Review pass
    parser.add_argument("--review", action="store_true", help="Generate a review.md that summarizes the whole batch.")
    parser.add_argument("--review-bullets", type=int, default=7, help="How many bullets per section in review (suggested 5–10).")
    parser.add_argument("--open", action="store_true", help="Open the batch index (and review if created) in VS Code.")
    parser.add_argument("--next-tasks", action="store_true", help="Generate next_tasks.txt for the next batch run.")
    parser.add_argument("--next-tasks-n", type=int, default=8, help="How many tasks to generate for next_tasks.txt.")
    parser.add_argument("--topic-guard", action="store_true", help="Flag likely off-topic outputs (writes .warning.txt and notes in index).")
    
    args = parser.parse_args()

    bullets_n = args.bullets if args.bullets and args.bullets > 0 else None

    # Output directory
    if args.outdir:
        outdir = Path(args.outdir)
    else:
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        outdir = Path(f"outputs/batch-{ts}")
    outdir.mkdir(parents=True, exist_ok=True)

    # Load tasks
    tasks = _load_tasks(args.tasks_file)
    if not tasks:
        print("No tasks found (file empty or only comments).")
        return

    # Memory context (optional)
    q = args.memory_query.strip() or None
    ctx = memory_as_context(query=q, limit=args.memory_limit)

    index_lines = [f"# Batch run: {outdir.name}", ""]
    index_lines.append(f"- tasks file: `{args.tasks_file}`")
    index_lines.append(f"- mode: `{'chat' if args.chat else ('router' if args.router else ('memory' if args.use_memory else 'json'))}`")
    index_lines.append(f"- strict: `{args.strict}` | verify: `{args.verify}` | bullets: `{bullets_n if bullets_n is not None else 'variable'}`")
    index_lines.append("")

    # Track outputs for review
    produced_files: list[tuple[str, Path]] = []  # (label, path)

    for i, (file_path, task) in enumerate(tasks, start=1):
        label = task if not file_path else f"{task} (FILE={file_path})"
        short = _slug(label)
        base = f"{i:03d}-{short}"

        # Decide mode per task
        if args.chat:
            mode = "chat"
        elif args.use_memory:
            mode = "memory"
        elif args.router:
            mode = "router->memory" if (args.memory_query.strip() and ctx.strip()) else "router->json"
        else:
            mode = "json"

        # Inject file content if requested on this line
        full_task = task
        if file_path:
            file_text = read_text(file_path)
            full_task = full_task + "\n\n[FILE CONTENT]\n" + file_text

        try:
            saved_path: Path

            if mode == "chat":
                text = generate(full_task, stream=False)
                saved_path = outdir / f"{base}.txt"
                saved_path.write_text(text.strip() + "\n", encoding="utf-8")

                index_lines.append(f"## {i}. {label}")
                index_lines.append(f"- output: `{saved_path.name}`")
                index_lines.append("")
                index_lines.append("```")
                index_lines.append(text.strip())
                index_lines.append("```")
                index_lines.append("")

                produced_files.append((label, saved_path))
                # Topic guard (optional)
                if args.topic_guard:
                    title = str(printable.get("title", "")).strip()
                    bullets = printable.get("bullets", [])
                    if not isinstance(bullets, list):
                        bullets = []
                    bullets = [str(b).strip() for b in bullets if str(b).strip()]

                    off, reason = topic_guard(label, title, bullets)
                    if off:
                        warn_path = outdir / f"{base}.warning.txt"
                        warn_path.write_text(
                            f"OFF-TOPIC WARNING\nTask: {label}\nReason: {reason}\nOutput file: {saved_path.name}\n",
                            encoding="utf-8"
                    )
                    index_lines.append(f"- ⚠️ OFF-TOPIC: `{warn_path.name}` ({reason})")
                    index_lines.append("")
                    log_run({
                    "mode": "batch->topic_guard",
                    "task": label,
                    "title": "off-topic",
                    "saved_to": str(warn_path),
                    })
                log_run({"mode": "batch->chat", "task": label, "title": text[:60], "saved_to": str(saved_path)})

            else:
                if mode.endswith("memory"):
                    data = run_memory_agent(full_task, context=ctx)
                    printable = {k: v for k, v in data.items() if k != "memory_to_save"}
                else:
                    printable = run_json_agent(full_task, strict=args.strict, verify=args.verify, bullets_n=bullets_n)

                if args.format == "md":
                    saved_path = outdir / f"{base}.md"
                    md = _render_md(str(printable.get("title", "")).strip(), printable.get("bullets", []))
                    saved_path.write_text(md, encoding="utf-8")
                else:
                    saved_path = outdir / f"{base}.json"
                    saved_path.write_text(json.dumps(printable, indent=2) + "\n", encoding="utf-8")

                index_lines.append(f"## {i}. {label}")
                index_lines.append(f"- output: `{saved_path.name}`")
                index_lines.append("")

                produced_files.append((label, saved_path))

                log_run({
                    "mode": f"batch->{mode}",
                    "task": label,
                    "title": printable.get("title", "Result"),
                    "strict": bool(args.strict),
                    "verify": bool(args.verify),
                    "memory_query": args.memory_query.strip(),
                    "saved_to": str(saved_path),
                })

        except OllamaNotRunning as e:
            print(str(e))
            return
        except Exception as e:
            err_path = outdir / f"{base}.error.txt"
            err_path.write_text(str(e) + "\n", encoding="utf-8")
            index_lines.append(f"## {i}. {label}")
            index_lines.append(f"- ERROR: `{err_path.name}`")
            index_lines.append("")
            log_run({"mode": "batch->error", "task": label, "title": "error", "saved_to": str(err_path)})

    # Write index
    index_path = outdir / "index.md"
    index_path.write_text("\n".join(index_lines).strip() + "\n", encoding="utf-8")

    # NEW: Review pass
    if args.review:
        # Build a compact digest from produced files
        digests = []
        for label, path in produced_files:
            try:
                if path.suffix == ".json":
                    obj = json.loads(path.read_text(encoding="utf-8"))
                    title = str(obj.get("title", "")).strip()
                    bullets = obj.get("bullets", [])
                    if not isinstance(bullets, list):
                        bullets = []
                    bullets = [str(b).strip() for b in bullets if str(b).strip()]
                elif path.suffix == ".md":
                    title, bullets = _extract_from_md(path.read_text(encoding="utf-8"))
                else:
                    # txt
                    title = label
                    bullets = [path.read_text(encoding="utf-8").strip()]
                digests.append({"task": label, "title": title, "bullets": bullets[:8]})
            except Exception:
                digests.append({"task": label, "title": "", "bullets": ["(could not parse output)"]})

        review_prompt = f"""Write a markdown review of this batch run.

You are reviewing the outputs of a local AI batch run. Use ONLY the digest below. Do NOT invent facts.

Format EXACTLY like this:

# Batch Run Review: {outdir.name}

## Task-by-task assessment
For each task, include:
- **Task:** <task text>
- **Output title:** <title>
- **What it answered well:** one sentence
- **What is missing / unclear:** one sentence
- **Quoted bullets:** include up to 2 bullets EXACTLY as written (or say "no bullets")

## Key takeaways
- Max {args.review_bullets} bullets
- Each bullet must be grounded in the digest (avoid generic statements)

## Action items
- Max {args.review_bullets} bullets
- Each action item must be concrete (e.g., "Re-run task 2 with BULLETS=3" or "Add FILE=...")

## Risks / things to verify
- Max {args.review_bullets} bullets
- ONLY list items that are actually uncertain/variant-dependent based on the digest.
- If there are no risks, write exactly: "None."

## Suggested next batch tasks
- Max {args.review_bullets} bullets
- Write tasks in the same style as tasks_file lines (short imperative prompts).
- Prefer tasks that improve weak outputs from above.

Batch outputs digest (JSON):
{json.dumps(digests, indent=2)}
"""
        review_text = generate(review_prompt, stream=False).strip()
        review_path = outdir / "review.md"
        review_path.write_text(review_text + "\n", encoding="utf-8")

        # NEW: Auto-generate next_tasks.txt (only after review exists)
        if args.next_tasks:
            next_prompt = f"""You are a batch-run manager. Create the NEXT batch tasks file.

Rules:
- Output plain text ONLY (no markdown).
- One task per line.
- No numbering, no bullets.
- Max {args.next_tasks_n} lines.
- Each line must be a runnable task in the same style as tasks files.
- If a task should use a file, use FILE=<path> at the start of the line (example: FILE=sample.md Summarize in 3 bullets.)
- Prefer tasks that fix weaknesses mentioned in the review and expand on good outputs.
- Do NOT invent file names unless they already appear in the digest or review.
- NEVER output FILE=... unless that exact filename appears in the digest or review.
- Prefer rewriting tasks to include constraints directly (example: "Summarize in 3 bullets") rather than referring to CLI flags.
Review text:
{review_text}

Batch outputs digest (JSON):
{json.dumps(digests, indent=2)}
"""
            next_text = generate(next_prompt, stream=False).strip()

            # Clean up: remove empty lines and accidental bullets/numbers
            lines = []
            for line in next_text.splitlines():
                line = line.strip()
                if not line:
                    continue
                line = re.sub(r"^[-*]\s+", "", line)
                line = re.sub(r"^\d+\.\s+", "", line)
                line = re.sub(r"^task:\s*", "", line, flags=re.IGNORECASE)
                lines.append(line)
                if len(lines) >= args.next_tasks_n:
                    break

            next_tasks_path = outdir / "next_tasks.txt"
            next_tasks_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")

            log_run({
                "mode": "batch->next_tasks",
                "task": f"next tasks for {outdir.name}",
                "title": "next_tasks",
                "saved_to": str(next_tasks_path),
            })

        log_run({
            "mode": "batch->review",
            "task": f"review for {outdir.name}",
            "title": "batch review",
            "saved_to": str(review_path),
        })
    log_run({
            "mode": "batch->review",
            "task": f"review for {outdir.name}",
            "title": "batch review",
            "saved_to": str(review_path),
        })

    print(f"Batch complete. Outputs saved to: {outdir}")
    print(f"Index: {index_path}")
    if args.review:
        print(f"Review: {outdir / 'review.md'}")

    if args.next_tasks:
        print(f"Next tasks: {outdir / 'next_tasks.txt'}")

    if args.open:
        _open_in_vscode(index_path)
    if args.review:
        _open_in_vscode(outdir / "review.md")


if __name__ == "__main__":
    main()
