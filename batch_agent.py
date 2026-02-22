import argparse
import json
import re
from datetime import datetime
from pathlib import Path

from ollama_client import generate, OllamaNotRunning
from agent_json import run as run_json_agent
from memory_agent import run as run_memory_agent
from memory import memory_as_context
from run_logger import log_run
from file_tools import read_text, write_text



def _call_json_agent(task: str, strict: bool, verify: bool, bullets_n):
    try:
        return run_json_agent(task, strict=strict, verify=verify, bullets_n=bullets_n)
    except TypeError:
        return run_json_agent(task, strict=strict, verify=verify)

def _slug(s: str, max_len: int = 60) -> str:
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return (s[:max_len].rstrip("-")) or "task"


def _load_tasks(path: str) -> list[str]:
    text = read_text(path, max_chars=300_000)
    tasks = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#"):
            continue
        tasks.append(line)
    return tasks


def _render_md(title: str, bullets: list[str]) -> str:
    lines = []
    if title:
        lines.append(f"# {title}")
        lines.append("")
    for b in bullets:
        b = str(b).strip()
        if b:
            lines.append(f"- {b}")
    return "\n".join(lines).strip() + "\n"


def main():
    parser = argparse.ArgumentParser(description="Batch runner for your local agent.")
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
    parser.add_argument("--format", choices=["json", "md"], default="json", help="Per-task output format for JSON modes.")
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

    for i, task in enumerate(tasks, start=1):
        short = _slug(task)
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

        try:
            saved_path = ""

            if mode == "chat":
                text = generate(task, stream=False)
                saved_path = str(outdir / f"{base}.txt")
                write_text(saved_path, text.strip() + "\n")

                index_lines.append(f"## {i}. {task}")
                index_lines.append(f"- output: `{Path(saved_path).name}`")
                index_lines.append("")
                index_lines.append("```")
                index_lines.append(text.strip())
                index_lines.append("```")
                index_lines.append("")

                log_run({"mode": "batch->chat", "task": task, "title": text[:60], "saved_to": saved_path})

            else:
                if mode.endswith("memory"):
                    data = run_memory_agent(task, context=ctx)
                    printable = {k: v for k, v in data.items() if k != "memory_to_save"}
                else:
                    printable = _call_json_agent(task, strict=args.strict, verify=args.verify, bullets_n=bullets_n)

                if args.format == "md":
                    saved_path = str(outdir / f"{base}.md")
                    md = _render_md(str(printable.get("title", "")).strip(), printable.get("bullets", []))
                    write_text(saved_path, md)
                else:
                    saved_path = str(outdir / f"{base}.json")
                    write_text(saved_path, json.dumps(printable, indent=2) + "\n")

                index_lines.append(f"## {i}. {task}")
                index_lines.append(f"- output: `{Path(saved_path).name}`")
                index_lines.append("")

                log_run({
                    "mode": f"batch->{mode}",
                    "task": task,
                    "title": printable.get("title", "Result"),
                    "strict": bool(args.strict),
                    "verify": bool(args.verify),
                    "memory_query": args.memory_query.strip(),
                    "saved_to": saved_path,
                })

        except OllamaNotRunning as e:
            print(str(e))
            return
        except Exception as e:
            err_path = outdir / f"{base}.error.txt"
            err_path.write_text(str(e) + "\n", encoding="utf-8")
            index_lines.append(f"## {i}. {task}")
            index_lines.append(f"- ERROR: `{err_path.name}`")
            index_lines.append("")

            log_run({"mode": "batch->error", "task": task, "title": "error", "saved_to": str(err_path)})

    index_path = outdir / "index.md"
    index_path.write_text("\n".join(index_lines).strip() + "\n", encoding="utf-8")

    print(f"Batch complete. Outputs saved to: {outdir}")
    print(f"Index: {index_path}")


if __name__ == "__main__":
    main()
