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
from file_tools import read_text


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

    if parts[0].startswith("WRITE="):
        write_path = parts[0].split("=", 1)[1].strip()
        if write_path.endswith(":"):
            write_path = write_path[:-1]
        task_text = " ".join(parts[1:]).strip() or "Write the requested file."
        # return write path in file_path slot, prefixed to distinguish
        return "WRITE:" + write_path, task_text

    if parts[0].startswith("FILE="):
        file_path = parts[0].split("=", 1)[1].strip()
        # tolerate accidental trailing colon: FILE=foo.md:
        if file_path.endswith(":"):
            file_path = file_path[:-1]
        task_text = " ".join(parts[1:]).strip() or "Summarize the file."
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
    title = (title or "").strip()
    lines = []
    if title:
        lines.append(f"# {title}")
        lines.append("")
    for b in bullets or []:
        b = str(b).strip()
        if b:
            lines.append(f"- {b}")
    return "\n".join(lines).strip() + "\n"


def _extract_from_md(md_text: str) -> tuple[str, list[str]]:
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


def _find_latest_next_tasks() -> str:
    """
    Find newest outputs/batch-*/next_tasks.txt (by folder name).
    Returns "" if none found.
    """
    root = Path("outputs")
    if not root.exists():
        return ""
    batches = sorted(root.glob("batch-*"), key=lambda p: p.name, reverse=True)
    for b in batches:
        candidate = b / "next_tasks.txt"
        if candidate.exists():
            return str(candidate)
    return ""


# ----------------------------
# Topic guard (heuristic)
# ----------------------------
STOPWORDS = {
    "the","a","an","and","or","to","of","in","on","for","with","is","are","was","were",
    "be","as","at","by","from","this","that","it","its","your","you","we","our","i",
    "explain","summarize","rewrite","provide","include","add","make","give","why","how",
    "simple","terms","bullets","bullet","points","point","paragraph","use","uses","usage",
    "compare","difference","differences","between","about"
}

DRIFT_WORDS = {
    "ingredient","ingredients","nutrition","nutritional","calorie","calories","sugar",
    "caffeine","aspartame","hfcs","corn syrup","allergen","allergens","preservative",
    "label","packaging","mg","grams","serving"
}

def _keywords(text: str) -> set[str]:
    text = text.lower()
    words = re.findall(r"[a-z0-9]+", text)
    return {w for w in words if len(w) >= 3 and w not in STOPWORDS}

def topic_guard(task_text: str, output_title: str, output_bullets: list[str]) -> tuple[bool, str]:
    task_keys = _keywords(task_text)
    out_text = (output_title or "") + " " + " ".join(output_bullets or [])
    out_text_l = out_text.lower()
    out_keys = _keywords(out_text)

    if not task_keys:
        return False, "no task keywords"

    overlap = task_keys.intersection(out_keys)
    overlap_ratio = len(overlap) / max(1, len(task_keys))
    drift_hits = [w for w in DRIFT_WORDS if w in out_text_l]

    too_low_overlap = overlap_ratio < 0.15 and len(overlap) <= 1
    has_drift = len(drift_hits) >= 2

    if too_low_overlap and has_drift:
        return True, f"low keyword overlap ({len(overlap)}/{len(task_keys)}); drift words: {', '.join(drift_hits[:6])}"
    return False, f"ok overlap ({len(overlap)}/{len(task_keys)})"



def _write_generated_file(outdir: Path, rel_path: str, content: str) -> Path:
    """Write generated content under outdir/generated/<rel_path>."""
    safe_rel = rel_path.strip().lstrip("/").replace("..", "_")
    gen_root = outdir / "generated"
    target = gen_root / safe_rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content.rstrip() + "\n", encoding="utf-8")
    return target

def main():
    parser = argparse.ArgumentParser(description="Batch runner for your local agent (supports FILE=... tasks).")

    # Option A: tasks_file optional if --run-latest-next is used
    parser.add_argument("tasks_file", nargs="?", default="", help="Tasks file. Optional if --run-latest-next is used.")
    parser.add_argument("--run-latest-next", action="store_true", help="Run newest outputs/batch-*/next_tasks.txt as the tasks file.")

    # Modes
    parser.add_argument("--chat", action="store_true", help="Plain text (chat) mode.")
    parser.add_argument("--use-memory", action="store_true", help="Force memory mode (grounded).")
    parser.add_argument("--router", action="store_true", help="Router: memory used only if --memory-query yields context.")

    # Controls
    parser.add_argument("--memory-query", default="", help="Filter memory context by keyword (e.g., week1).")
    parser.add_argument("--memory-limit", type=int, default=10, help="How many memory items to include.")
    parser.add_argument("--strict", action="store_true", help="Don't guess facts (JSON modes).")
    parser.add_argument("--verify", action="store_true", help="Add claims_to_verify/how_to_verify (JSON modes).")
    parser.add_argument("--bullets", type=int, default=0, help="Force bullet count (0 = model decides).")

    # Output
    parser.add_argument("--outdir", default="", help="Output directory. Default outputs/batch-<timestamp>/")
    parser.add_argument("--format", choices=["json", "md"], default="md", help="Per-task output format for JSON modes.")

    # Review + next tasks
    parser.add_argument("--review", action="store_true", help="Generate review.md.")
    parser.add_argument("--review-bullets", type=int, default=7, help="Bullets per section in review.")
    parser.add_argument("--next-tasks", action="store_true", help="Generate next_tasks.txt (requires --review).")
    parser.add_argument("--next-tasks-n", type=int, default=8, help="How many lines for next_tasks.txt.")

    # Topic guard
    parser.add_argument("--topic-guard", action="store_true", help="Flag likely off-topic outputs (writes .warning.txt + notes in index).")

    # Convenience
    parser.add_argument("--open", action="store_true", help="Open index/review/next_tasks in VS Code.")
    args = parser.parse_args()

    # Resolve tasks file (Option A)
    if args.run_latest_next and not args.tasks_file:
        latest = _find_latest_next_tasks()
        if not latest:
            print("No next_tasks.txt found. Run a batch with --review --next-tasks first.")
            return
        args.tasks_file = latest
        print(f"Using latest next tasks file: {args.tasks_file}")

    if not args.tasks_file:
        print("Please provide a tasks_file, or use --run-latest-next.")
        return

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
        print("No tasks found.")
        return

    # Memory context
    q = args.memory_query.strip() or None
    ctx = memory_as_context(query=q, limit=args.memory_limit)

    index_lines = [f"# Batch run: {outdir.name}", ""]
    index_lines.append(f"- tasks file: `{args.tasks_file}`")
    index_lines.append(f"- mode: `{'chat' if args.chat else ('router' if args.router else ('memory' if args.use_memory else 'json'))}`")
    index_lines.append(f"- strict: `{args.strict}` | verify: `{args.verify}` | bullets: `{bullets_n if bullets_n is not None else 'variable'}`")
    index_lines.append("")

    produced_files: list[tuple[str, Path]] = []  # (label, path)

    for i, (file_path, task) in enumerate(tasks, start=1):
        label = task if not file_path else f"{task} (FILE={file_path})"
        base = f"{i:03d}-{_slug(label)}"

        # Decide mode
        if args.chat:
            mode = "chat"
        elif args.use_memory:
            mode = "memory"
        elif args.router:
            mode = "router->memory" if (args.memory_query.strip() and ctx.strip()) else "router->json"
        else:
            mode = "json"

        # Inject file content per task (UPGRADE: skip missing files without crashing)
        full_task = task
        write_target = None
        if file_path:
            # WRITE tasks: model generates file content
            if isinstance(file_path, str) and file_path.startswith("WRITE:"):
                write_target = file_path.split(":", 1)[1]
            else:
                try:
                    file_text = read_text(file_path)
                    full_task = full_task + "\n\n[FILE CONTENT]\n" + file_text
                except FileNotFoundError as e:
                    err_path = outdir / f"{base}.error.txt"
                    err_path.write_text(str(e) + "\n", encoding="utf-8")
                    index_lines.append(f"## {i}. {label}")
                    index_lines.append(f"- ERROR: `{err_path.name}` (missing file)")
                    index_lines.append("")
                    log_run({"mode": "batch->error", "task": label, "title": "missing file", "saved_to": str(err_path)})
                    continue
                except FileNotFoundError as e:
                    err_path = outdir / f"{base}.error.txt"
                    err_path.write_text(str(e) + "\n", encoding="utf-8")
                    index_lines.append(f"## {i}. {label}")
                    index_lines.append(f"- ERROR: `{err_path.name}` (missing file)")
                    index_lines.append("")
                    log_run({"mode": "batch->error", "task": label, "title": "missing file", "saved_to": str(err_path)})
                    continue

        try:
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

            # If this task requested writing a file, write it under outdir/generated/
            if write_target:
                # Use chat mode for file generation to avoid JSON constraints
                file_text_out = generate(full_task, stream=False)
                gen_path = _write_generated_file(outdir, write_target, file_text_out)
                index_lines.append(f"- wrote: `generated/{write_target}`")
                index_lines.append("")
                log_run({"mode": "batch->write", "task": label, "title": f"wrote {write_target}", "saved_to": str(gen_path)})
                log_run({"mode": "batch->chat", "task": label, "title": text[:60], "saved_to": str(saved_path)})
                continue

            # JSON/memory result
            if mode.endswith("memory"):
                data = run_memory_agent(full_task, context=ctx)
                printable = {k: v for k, v in data.items() if k != "memory_to_save"}
            else:
                printable = run_json_agent(full_task, strict=args.strict, verify=args.verify, bullets_n=bullets_n)

            # Save output
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

            # If this task requested writing a file, write it under outdir/generated/
            if write_target:
                # Use chat mode for file generation to avoid JSON constraints
                file_text_out = generate(full_task, stream=False)
                gen_path = _write_generated_file(outdir, write_target, file_text_out)
                index_lines.append(f"- wrote: `generated/{write_target}`")
                index_lines.append("")
                log_run({"mode": "batch->write", "task": label, "title": f"wrote {write_target}", "saved_to": str(gen_path)})

            # Topic guard (ONLY for structured outputs)
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
                    log_run({"mode": "batch->topic_guard", "task": label, "title": "off-topic", "saved_to": str(warn_path)})

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

    review_path: Path | None = None
    next_tasks_path: Path | None = None

    # Review (+ next tasks)
    if args.review:
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
                    title = label
                    bullets = [path.read_text(encoding="utf-8").strip()]
                digests.append({"task": label, "title": title, "bullets": bullets[:8]})
            except Exception:
                digests.append({"task": label, "title": "", "bullets": ["(could not parse output)"]})

        review_prompt = f"""Write a markdown review of this batch run.

You are reviewing the outputs of a local AI batch run. Use ONLY the digest below. Do NOT invent facts.

Hard rules:
- Do NOT mention CLI flags like --bullets, --strict, --verify, or text like BULLETS=3.
- If a task asked for N items and the output provided fewer, call that out explicitly.
- If a FILE-based task asks for more bullets than the file supports, say so.

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

## Action items
- Max {args.review_bullets} bullets
- Each action item must be runnable as a tasks_file line (no numbering, no bullets, no "Rewrite task:" prefix).

## Risks / things to verify
- Max {args.review_bullets} bullets
- If there are no risks, write exactly: "None."

## Suggested next batch tasks
- Output EXACTLY {args.review_bullets} lines.
- Each line must be a runnable tasks_file line:
  - No numbering
  - No bullets
  - No "Rewrite task:" prefix
  - If using a file, it MUST start with FILE=<path>
- Never mention non-existent files. Only use FILE= paths that appear in the digest.

Batch outputs digest (JSON):
{json.dumps(digests, indent=2)}
"""
        review_text = generate(review_prompt, stream=False).strip()
        review_path = outdir / "review.md"
        review_path.write_text(review_text + "\n", encoding="utf-8")
        log_run({"mode": "batch->review", "task": f"review for {outdir.name}", "title": "batch review", "saved_to": str(review_path)})

        if args.next_tasks:
            next_prompt = f"""You are a batch-run manager. Create the NEXT batch tasks file.

Output rules (VERY STRICT):
- Output plain text ONLY (no markdown).
- One task per line.
- No numbering, no bullets, no "Task:" prefix, no "Rewrite task:" prefix.
- Max {args.next_tasks_n} lines.

Content rules:
- Each line must be runnable as a tasks_file line.
- If a line needs a file, it MUST start with FILE=<path>.
- NEVER output FILE=... unless that exact filename appears in the digest or review text.
- Do NOT invent filenames.
- Do NOT mention CLI flags and do NOT use "BULLETS=3".
- If file content is short, do NOT demand impossible bullet counts. Prefer: "List ALL points present" or "Use as many bullets as needed".
- Default to variable-length bullets. Only request an exact bullet count when it clearly helps. Avoid repeating "exactly 7 bullets" as a default.
- IMPORTANT: Do NOT invent new syntaxes like TEXT= or use FILE= to mean "write a file". In this system, FILE= is ONLY for reading an existing file and MUST appear at the start of the line (FILE=path task...). If you cannot guarantee the file exists, do not use FILE= at all.

Review text:
{review_text}

Batch outputs digest (JSON):
{json.dumps(digests, indent=2)}
"""
            next_text = generate(next_prompt, stream=False).strip()

            lines = []
            for line in next_text.splitlines():
                line = line.strip()
                if not line:
                    continue
                line = re.sub(r"^[-*]\s+", "", line)
                line = re.sub(r"^\d+\.\s+", "", line)
                line = re.sub(r"^task:\s*", "", line, flags=re.IGNORECASE)
                line = re.sub(r"^rewrite task:\s*", "", line, flags=re.IGNORECASE)
                line = re.sub(r"^rewrite:\s*", "", line, flags=re.IGNORECASE)
                line = re.sub(r"^\(FILE=([^)]+)\)\s*", r"FILE=\1 ", line)
                line = re.sub(r"\bBULLETS\s*=\s*\d+\b", "", line, flags=re.IGNORECASE).strip()

                # drop obvious meta/rules lines
                if line.lower().startswith("here is the next batch tasks file"):
                    continue
                if "use file=" in line.lower() and "only if" in line.lower():
                    continue
                if line.startswith("FILE=/") or line.startswith("FILE=~"):
                    continue
                if line.startswith('"') and '"' in line[1:]:
                    continue
                # drop unsupported write-style lines
                if 'TEXT=' in line:
                    continue

                if line:
                    lines.append(line)
                if len(lines) >= args.next_tasks_n:
                    break

            next_tasks_path = outdir / "next_tasks.txt"
            next_tasks_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
            log_run({"mode": "batch->next_tasks", "task": f"next tasks for {outdir.name}", "title": "next_tasks", "saved_to": str(next_tasks_path)})

    print(f"Batch complete. Outputs saved to: {outdir}")
    print(f"Index: {index_path}")
    if review_path:
        print(f"Review: {review_path}")
    if next_tasks_path:
        print(f"Next tasks: {next_tasks_path}")

    if args.open:
        _open_in_vscode(index_path)
        if review_path:
            _open_in_vscode(review_path)
        if next_tasks_path:
            _open_in_vscode(next_tasks_path)


if __name__ == "__main__":
    main()
