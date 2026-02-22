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

        review_prompt = f"""Write a concise review of this batch run.

You are reviewing the outputs of a local AI batch run. Create a markdown report with these sections:
1) Key takeaways (max {args.review_bullets} bullets)
2) Action items (max {args.review_bullets} bullets)
3) Risks / things to verify (max {args.review_bullets} bullets)
4) Suggested next batch tasks (max {args.review_bullets} bullets)

Use simple language. Be specific. Do not invent facts beyond the batch outputs.

Batch outputs digest (JSON):
{json.dumps(digests, indent=2)}
"""
        review_text = generate(review_prompt, stream=False).strip()
        review_path = outdir / "review.md"
        review_path.write_text(review_text + "\n", encoding="utf-8")

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

    if args.open:
        _open_in_vscode(index_path)
        if args.review:
            _open_in_vscode(outdir / "review.md")


if __name__ == "__main__":
    main()
