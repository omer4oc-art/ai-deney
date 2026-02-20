import argparse
import json
import os
import subprocess
from datetime import datetime

from ollama_client import OllamaNotRunning, generate
from agent_json import run as run_json_agent
from memory_agent import run as run_memory_agent
from memory import add_memory, memory_as_context, list_memory
from run_logger import log_run, read_last, search
from file_tools import read_text, write_text


def _save_json(data: dict, out: str = "") -> str:
    os.makedirs("outputs", exist_ok=True)
    if out:
        path = out
    else:
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = f"outputs/{ts}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return path


def _find_last_saved_path(limit: int = 5000) -> str:
    events = read_last(limit)
    for e in reversed(events):
        p = (e.get("saved_to") or "").strip()
        if p:
            return p
    return ""


def _find_last_saved_path_by_query(query: str, limit: int = 5000) -> str:
    hits = search(query, limit)
    for e in reversed(hits):
        p = (e.get("saved_to") or "").strip()
        if p:
            return p
    return ""


def _print_json_file(path: str) -> None:
    if not os.path.exists(path):
        print(f"File not found: {path}")
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        print(json.dumps(data, indent=2))
    except json.JSONDecodeError:
        with open(path, "r", encoding="utf-8") as f:
            print(f.read())


def _open_file(path: str) -> None:
    if not os.path.exists(path):
        print(f"File not found: {path}")
        return

    # Try VS Code CLI
    try:
        subprocess.run(["code", path], check=False)
        return
    except Exception:
        pass

    # Fallback: macOS open
    try:
        subprocess.run(["open", path], check=False)
    except Exception as e:
        print(f"Could not open file: {path}\n{e}")


def main():
    parser = argparse.ArgumentParser(description="Local agent CLI (chat + json + memory + router) with logging.")
    parser.add_argument("task", nargs="?", default="", help="Task to run (wrap in quotes).")

    # Modes
    parser.add_argument("--chat", action="store_true", help="Plain text response (no JSON).")
    parser.add_argument(
        "--use-memory",
        action="store_true",
        help="Ground answer strictly in saved memory."
    )
    parser.add_argument(
        "--router",
        action="store_true",
        help="Auto: use memory only when --memory-query is provided and returns context."
    )

    # Quality controls
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Do not guess facts; say unknown/varies when unsure."
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Add claims_to_verify + how_to_verify fields (self-audit)."
    )

    # Memory controls
    parser.add_argument("--memory-query", default="", help="Filter memory context by keyword (e.g., week1).")
    parser.add_argument("--memory-limit", type=int, default=10, help="How many memory items to include.")
    parser.add_argument("--show-memory", action="store_true", help="Print memory and exit.")
    parser.add_argument("--add-memory", default="", help="Add a memory note (string).")
    parser.add_argument("--tags", default="", help="Comma-separated tags for --add-memory (e.g., week1,setup).")

    # Output
    parser.add_argument("--save", action="store_true", help="Save JSON output to outputs/. (JSON modes only)")
    parser.add_argument("--out", default="", help="Custom JSON output path.")

    # Logging
    parser.add_argument("--show-log", action="store_true", help="Show last N runs and exit.")
    parser.add_argument("--log-limit", type=int, default=20, help="How many runs to show with --show-log.")
    parser.add_argument("--search-log", default="", help="Search run log by keyword.")
    parser.add_argument("--last-run", action="store_true", help="Print the most recent run log entry (full JSON) and exit.")

    # Last output helpers
    parser.add_argument("--last-output", action="store_true", help="Print the most recently saved JSON output and exit.")
    parser.add_argument("--open-last", action="store_true", help="Open the most recently saved JSON output and exit.")

    # Open last saved output matching a keyword
    parser.add_argument("--open-log", default="", help="Open the most recent saved output matching a keyword (task/title/mode).")

    # File tools
    parser.add_argument("--from-file", default="", help="Read a file (relative to project) and include it in the task context.")
    parser.add_argument("--to-file", default="", help="Write the output to a file (relative to project).")
    parser.add_argument("--to-file-format", default="md", choices=["md","json"], help="Format for --to-file: md or json.")

    args = parser.parse_args()

    FILE_CONTEXT = ""
    if args.from_file:
        FILE_CONTEXT = read_text(args.from_file)
        if not args.task:
            args.task = "Summarize the file."

    def _maybe_write_to_file(output_text: str, output_json: dict | None = None):
        if not args.to_file:
            return
        if args.to_file_format == 'json':
            if output_json is None:
                output_json = {'text': output_text}
            write_text(args.to_file, json.dumps(output_json, indent=2))
        else:
            write_text(args.to_file, output_text)
        print(f"\nWrote to: {args.to_file}")


    # Print the last run log entry (full JSON)
    if args.last_run:
        events = read_last(1)
        if not events:
            print("No runs logged yet.")
            return
        print(json.dumps(events[0], indent=2))
        return

    # Open last saved output matching keyword
    if args.open_log:
        path = _find_last_saved_path_by_query(args.open_log, limit=5000)
        if not path:
            print(f"No saved outputs found matching '{args.open_log}'. Try --show-log --search-log <keyword> first.")
            return
        _open_file(path)
        return

    # Print/open the most recent saved JSON output
    if args.last_output or args.open_last:
        last_path = _find_last_saved_path()
        if not last_path:
            print("No saved outputs found in run log yet. Run a command with --save first.")
            return
        if args.open_last:
            _open_file(last_path)
        else:
            _print_json_file(last_path)
        return

    # Show log and exit
    if args.show_log:
        events = search(args.search_log, args.log_limit) if args.search_log else read_last(args.log_limit)
        if not events:
            print("No runs logged yet.")
            return
        for e in events:
            mode = e.get("mode", "?")
            title = e.get("title", "")
            task = e.get("task", "")
            ts = e.get("ts", "")
            saved = e.get("saved_to", "")
            tail = f" | saved: {saved}" if saved else ""
            print(f"- {ts} | {mode} | {title} | {task}{tail}")
        return

    # Memory admin
    if args.add_memory:
        tags = [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else []
        item = add_memory(args.add_memory, tags=tags, source="manual")
        print(f"Saved memory: ({item['id']}) {item['text']}")
        log_run({
            "mode": "add-memory",
            "task": args.add_memory,
            "title": "memory add",
            "tags": tags,
        })
        return

    if args.show_memory:
        items = list_memory(limit=args.memory_limit)
        if not items:
            print("No saved memory yet.")
            return
        for it in items:
            tag_str = f" [tags: {', '.join(it.get('tags', []))}]" if it.get("tags") else ""
            print(f"- ({it['id']}) {it['text']}{tag_str}")
        return

    if not args.task:
        print("Provide a task, or use --show-memory / --add-memory / --show-log / --last-output.")
        return

    # Task + file context
    if FILE_CONTEXT:
        args.task = args.task + "\n\n[FILE CONTENT]\n" + FILE_CONTEXT

    # Build memory context if requested
    q = args.memory_query.strip() or None
    ctx = memory_as_context(query=q, limit=args.memory_limit)

    saved_path = ""

    # Chat mode (plain text)
    if args.chat:
        text = generate(args.task, stream=False)
        print(text)
        _maybe_write_to_file(text)
        log_run({
            "mode": "chat",
            "task": args.task,
            "title": (text[:60] + "…") if len(text) > 60 else text,
            "strict": bool(args.strict),
            "verify": bool(args.verify),
        })
        return

    # Router: only use memory if memory-query is provided AND returns context
    if args.router:
        if args.memory_query.strip() and ctx.strip():
            data = run_memory_agent(args.task, context=ctx)
            printable = {k: v for k, v in data.items() if k != "memory_to_save"}
            print(json.dumps(printable, indent=2))
            _maybe_write_to_file(json.dumps(printable, indent=2), printable)
            mode = "router->memory"
            title = printable.get("title", "Result")
        else:
            data = run_json_agent(args.task, strict=args.strict, verify=args.verify)
            print(json.dumps(data, indent=2))
            _maybe_write_to_file(json.dumps(data, indent=2), data)
            mode = "router->json"
            title = data.get("title", "Result")

        if (args.save or args.verify) and isinstance(data, dict):
            saved_path = _save_json(data, args.out)
            print(f"\nSaved to: {saved_path}")

        log_run({
            "mode": mode,
            "task": args.task,
            "title": title,
            "strict": bool(args.strict),
            "verify": bool(args.verify),
            "memory_query": args.memory_query.strip(),
            "saved_to": saved_path,
        })
        return

    # Explicit memory mode
    if args.use_memory:
        data = run_memory_agent(args.task, context=ctx)
        printable = {k: v for k, v in data.items() if k != "memory_to_save"}
        print(json.dumps(printable, indent=2))
        _maybe_write_to_file(json.dumps(printable, indent=2), printable)

        if args.save or args.verify:
            saved_path = _save_json(data, args.out)
            print(f"\nSaved to: {saved_path}")

        log_run({
            "mode": "memory",
            "task": args.task,
            "title": printable.get("title", "Result"),
            "memory_query": args.memory_query.strip(),
            "saved_to": saved_path,
        })
        return

    # Default: JSON agent (with optional strict/verify)
    data = run_json_agent(args.task, strict=args.strict, verify=args.verify)
    print(json.dumps(data, indent=2))
    _maybe_write_to_file(json.dumps(data, indent=2), data)

    if args.save or args.verify:
        saved_path = _save_json(data, args.out)
        print(f"\nSaved to: {saved_path}")

    log_run({
        "mode": "json",
        "task": args.task,
        "title": data.get("title", "Result"),
        "strict": bool(args.strict),
        "verify": bool(args.verify),
        "saved_to": saved_path,
    })


if __name__ == "__main__":
    try:
        main()
    except OllamaNotRunning as e:
        print(str(e))
        raise SystemExit(1)