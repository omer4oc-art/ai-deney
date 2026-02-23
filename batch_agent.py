import argparse
import json
import re
import shlex
import subprocess
import py_compile
from datetime import datetime
from pathlib import Path

from ollama_client import generate, OllamaNotRunning
from agent_json import run as run_json_agent
from memory_agent import run as run_memory_agent
from memory import memory_as_context
from run_logger import log_run
from file_tools import read_text



CODE_CONTRACT_PY = """Output ONLY valid Python code. No markdown. No prose. No triple backticks.
Requirements:
- Include docstring + type hints.
- Include input validation (raise ValueError/TypeError).
- If you are unsure about an API, do NOT guess. Prefer the simplest correct approach.
- If you cannot complete the task, output a Python file that raises RuntimeError explaining what is missing.
"""

def _slug(s: str, max_len: int = 60) -> str:
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return (s[:max_len].rstrip("-")) or "task"


def _parse_task_line(line: str) -> tuple[str | None, str]:
    """
    Supports:
      - normal task line
      - FILE=path task...
      - WRITE=relpath task...
    Returns: (directive_or_none, task_text)
      directive is one of:
        - None
        - "FILE:<path>"
        - "WRITE:<relpath>"
    """
    line = line.strip()
    if not line or line.startswith("#"):
        return None, ""

    parts = shlex.split(line)
    if not parts:
        return None, ""

    head = parts[0].strip()

    if head.startswith("WRITE="):
        rel = head.split("=", 1)[1].strip()
        if rel.endswith(":"):
            rel = rel[:-1]
        task_text = " ".join(parts[1:]).strip() or "Write the requested file."
        return f"WRITE:{rel}", task_text

    if head.startswith("FILE="):
        path = head.split("=", 1)[1].strip()
        if path.endswith(":"):
            path = path[:-1]
        task_text = " ".join(parts[1:]).strip() or "Summarize the file."
        return f"FILE:{path}", task_text

    return None, line


def _load_tasks(path: str) -> list[tuple[str | None, str]]:
    text = read_text(path, max_chars=300_000)
    tasks: list[tuple[str | None, str]] = []
    for raw in text.splitlines():
        directive, task = _parse_task_line(raw)
        if task:
            tasks.append((directive, task))
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
    root = Path("outputs")
    if not root.exists():
        return ""
    batches = sorted(root.glob("batch-*"), key=lambda p: p.name, reverse=True)
    for b in batches:
        cand = b / "next_tasks.txt"
        if cand.exists():
            return str(cand)
    return ""


def _write_generated_file(outdir: Path, rel_path: str, content: str) -> Path:
    rel = rel_path.strip().lstrip("/").replace("..", "_")
    gen_root = outdir / "generated"
    target = gen_root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content.rstrip() + "\n", encoding="utf-8")
    return target


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
        return True, f"low keyword overlap ({len(overlap)}/{len(task_keys)}); drift: {', '.join(drift_hits[:6])}"
    return False, f"ok overlap ({len(overlap)}/{len(task_keys)})"



def _lint_python_file(py_path: Path) -> tuple[bool, str]:
    """Return (ok, message)."""
    try:
        py_compile.compile(str(py_path), doraise=True)
        return True, "py_compile ok"
    except Exception as e:
        return False, str(e)


def _strip_code_fences(text: str) -> str:
    """
    Remove common markdown code fences from model output.
    Handles:
      ```python
      ...
      ```
    and ``` ... ```
    """
    s = text.strip()
    s = re.sub(r"^\s*```[a-zA-Z0-9_-]*\s*\n", "", s)
    s = re.sub(r"\n\s*```\s*$", "", s)
    return s.strip() + "\n"


def _maybe_run_pytest(project_root: Path) -> tuple[bool, str]:
    """
    Runs pytest if tests/ exists and pytest is installed.
    Returns (ok, message). If skipped, ok=True with a skip message.
    """
    tests_dir = project_root / "tests"
    if not tests_dir.exists():
        return True, "pytest skipped (no tests/ folder)"

    try:
        import pytest  # noqa: F401
    except Exception:
        return True, "pytest skipped (pytest not installed)"

    env = dict(**__import__("os").environ)
    # If you use src/ layout, this helps imports like `from ai_deney...`
    src_dir = project_root / "src"
    if src_dir.exists():
        env["PYTHONPATH"] = str(src_dir) + (":" + env.get("PYTHONPATH", "") if env.get("PYTHONPATH") else "")

    try:
        r = subprocess.run(["pytest", "-q"], cwd=str(project_root), env=env, capture_output=True, text=True)
        if r.returncode == 0:
            return True, "pytest ok"
        # include a short tail of output
        out = (r.stdout + "\n" + r.stderr).strip()
        tail = "\n".join(out.splitlines()[-25:])
        return False, "pytest failed:\n" + tail
    except Exception as e:
        return False, f"pytest error: {e}"

def main():
    parser = argparse.ArgumentParser(description="Batch runner for your local agent.")
    parser.add_argument("tasks_file", nargs="?", default="", help="Tasks file. Optional if --run-latest-next.")
    parser.add_argument("--run-latest-next", action="store_true", help="Use newest outputs/batch-*/next_tasks.txt.")

    parser.add_argument("--chat", action="store_true", help="Plain text mode.")
    parser.add_argument("--use-memory", action="store_true", help="Force memory mode.")
    parser.add_argument("--router", action="store_true", help="Router mode (uses memory only if --memory-query matches).")

    parser.add_argument("--memory-query", default="", help="Filter memory context by keyword.")
    parser.add_argument("--memory-limit", type=int, default=10, help="How many memory items to include.")
    parser.add_argument("--strict", action="store_true", help="Don't guess facts (JSON modes).")
    parser.add_argument("--verify", action="store_true", help="Add claims_to_verify/how_to_verify (JSON modes).")
    parser.add_argument("--bullets", type=int, default=0, help="Force bullet count (0 = model decides).")

    parser.add_argument("--outdir", default="", help="Output directory. Default outputs/batch-<timestamp>/")
    parser.add_argument("--format", choices=["json", "md"], default="md", help="Output format for JSON modes.")

    parser.add_argument("--review", action="store_true", help="Generate review.md.")
    parser.add_argument("--review-bullets", type=int, default=7, help="Bullets per section in review.")
    parser.add_argument("--next-tasks", action="store_true", help="Generate next_tasks.txt (requires --review).")
    parser.add_argument("--next-tasks-n", type=int, default=8, help="How many lines for next_tasks.txt.")
    parser.add_argument("--topic-guard", action="store_true", help="Flag likely off-topic outputs.")
    parser.add_argument("--open", action="store_true", help="Open index/review/next_tasks in VS Code.")
    args = parser.parse_args()

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

    if args.outdir:
        outdir = Path(args.outdir)
    else:
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        outdir = Path(f"outputs/batch-{ts}")
    outdir.mkdir(parents=True, exist_ok=True)

    tasks = _load_tasks(args.tasks_file)
    if not tasks:
        print("No tasks found.")
        return

    q = args.memory_query.strip() or None
    ctx = memory_as_context(query=q, limit=args.memory_limit)

    index_lines = [f"# Batch run: {outdir.name}", ""]
    index_lines.append(f"- tasks file: `{args.tasks_file}`")
    index_lines.append(f"- mode: `{'chat' if args.chat else ('router' if args.router else ('memory' if args.use_memory else 'json'))}`")
    index_lines.append(f"- strict: `{args.strict}` | verify: `{args.verify}` | bullets: `{bullets_n if bullets_n is not None else 'variable'}`")
    index_lines.append("")

    produced_files: list[tuple[str, Path]] = []

    for i, (directive, task) in enumerate(tasks, start=1):
        base = f"{i:03d}-{_slug(task)}"

        # Decide mode
        if args.chat:
            mode = "chat"
        elif args.use_memory:
            mode = "memory"
        elif args.router:
            mode = "router->memory" if (args.memory_query.strip() and ctx.strip()) else "router->json"
        else:
            mode = "json"

        # Handle WRITE tasks first: write + continue (no JSON run)
        if isinstance(directive, str) and directive.startswith("WRITE:"):
            rel = directive.split(":", 1)[1]
            label = f"{task} (WRITE={rel})"
            try:
                prompt = task
                if rel.lower().endswith('.py'):
                    prompt = CODE_CONTRACT_PY + "\n\n" + task
                text = generate(prompt, stream=False)
                if rel.lower().endswith('.py'):
                    text = _strip_code_fences(text)
                gen_path = _write_generated_file(outdir, rel, text)
                # Auto-lint: if we wrote a .py file, run py_compile
                if gen_path.suffix == ".py":
                    ok, msg = _lint_python_file(gen_path)
                    if not ok:
                        warn_path = outdir / f"{base}.warning.txt"
                        warn_path.write_text("PYTHON SYNTAX WARNING\n" + msg + "\n", encoding="utf-8")
                        index_lines.append(f"- ⚠️ python syntax: `{warn_path.name}`")
                        index_lines.append("")
                        log_run({"mode": "batch->lint_warning", "task": label, "title": "py_compile failed", "saved_to": str(warn_path)})

                index_lines.append(f"## {i}. {label}")
                index_lines.append(f"- wrote: `generated/{rel}`")
                index_lines.append("")
                produced_files.append((label, gen_path))
                ok_pytest, msg_pytest = _maybe_run_pytest(Path("."))
                if not ok_pytest:
                    warn_path2 = outdir / f"{base}.pytest.warning.txt"
                    warn_path2.write_text("PYTEST WARNING\n" + msg_pytest + "\n", encoding="utf-8")
                    index_lines.append(f"- ⚠️ pytest: `{warn_path2.name}`")
                    index_lines.append("")
                    log_run({"mode": "batch->pytest", "task": label, "title": "pytest failed", "saved_to": str(warn_path2)})
                else:
                    log_run({"mode": "batch->pytest", "task": label, "title": msg_pytest, "saved_to": str(outdir)})

                log_run({"mode": "batch->write", "task": label, "title": f"wrote {rel}", "saved_to": str(gen_path)})
            except Exception as e:
                err_path = outdir / f"{base}.error.txt"
                err_path.write_text(str(e) + "\n", encoding="utf-8")
                index_lines.append(f"## {i}. {label}")
                index_lines.append(f"- ERROR: `{err_path.name}`")
                index_lines.append("")
                log_run({"mode": "batch->error", "task": label, "title": "write error", "saved_to": str(err_path)})
            continue

        # Build task, injecting file content if FILE=...
        full_task = task
        label = task
        if isinstance(directive, str) and directive.startswith("FILE:"):
            path = directive.split(":", 1)[1]
            label = f"{task} (FILE={path})"
            try:
                file_text = read_text(path)
                full_task = task + "\n\n[FILE CONTENT]\n" + file_text
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
                produced_files.append((label, saved_path))
                log_run({"mode": "batch->chat", "task": label, "title": text[:60], "saved_to": str(saved_path)})
                continue

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

            if args.topic_guard:
                title = str(printable.get("title", "")).strip()
                bullets = printable.get("bullets", [])
                if not isinstance(bullets, list):
                    bullets = []
                bullets = [str(b).strip() for b in bullets if str(b).strip()]
                off, reason = topic_guard(label, title, bullets)
                if off:
                    warn_path = outdir / f"{base}.warning.txt"
                    warn_path.write_text(f"OFF-TOPIC WARNING\nTask: {label}\nReason: {reason}\nOutput: {saved_path.name}\n", encoding="utf-8")
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

    index_path = outdir / "index.md"
    index_path.write_text("\n".join(index_lines).strip() + "\n", encoding="utf-8")

    review_path = None
    next_tasks_path = None

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

        if not digests:
            review_text = f"# Batch Run Review: {outdir.name}\n\nNo runnable outputs were produced (all tasks failed or wrote empty files).\n"
        else:
            review_prompt = f"""Write a markdown review of this batch run.

Use ONLY the digest below. Do NOT invent facts.
Do NOT mention CLI flags. Do NOT output fake paths like /path/to/...

Format:
# Batch Run Review: {outdir.name}

## Key takeaways
- Max {args.review_bullets} bullets

## Action items
- Max {args.review_bullets} bullets (each should be a runnable tasks_file line)

## Risks / things to verify
- If none, write: None.

## Suggested next batch tasks
- Output up to {args.review_bullets} runnable task lines (no numbering, no bullets).
- Only use FILE= if that exact filename appears in the digest.

Digest:
{json.dumps(digests, indent=2)}
"""
            review_text = generate(review_prompt, stream=False).strip() + "\n"

        review_path = outdir / "review.md"
        review_path.write_text(review_text, encoding="utf-8")
        log_run({"mode": "batch->review", "task": f"review for {outdir.name}", "title": "batch review", "saved_to": str(review_path)})

        if args.next_tasks and digests:
            next_prompt = f"""Create the NEXT batch tasks file.

Rules:
- Output plain text ONLY.
- One runnable task per line.
- No numbering, no bullets, no headers.
- Do NOT invent syntaxes like TEXT=.
- FILE= is ONLY for reading existing files and MUST be at the start of the line.
- Never output /path/to/... or FILE=/home/... placeholders.
- Default to variable-length bullets unless an exact count clearly helps.

Review text:
{review_text}

Digest:
{json.dumps(digests, indent=2)}
"""
            nxt = generate(next_prompt, stream=False).strip()
            lines = []
            for line in nxt.splitlines():
                line = line.strip()
                if not line:
                    continue
                if line.lower().startswith("here are"):
                    continue
                if "TEXT=" in line:
                    continue
                if line.startswith("FILE=/") or line.startswith("FILE=~") or "/path/to/" in line:
                    continue
                line = re.sub(r"^[-*]\s+", "", line)
                line = re.sub(r"^\d+\.\s+", "", line)
                line = re.sub(r"^task:\s*", "", line, flags=re.IGNORECASE)
                line = re.sub(r"^rewrite task:\s*", "", line, flags=re.IGNORECASE)
                line = re.sub(r"^rewrite:\s*", "", line, flags=re.IGNORECASE)
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
