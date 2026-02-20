import argparse
import json
import os
from datetime import datetime

from ollama_client import OllamaNotRunning, generate
from agent_json import run as run_json_agent
from memory_agent import run as run_memory_agent
from memory import add_memory, memory_as_context, list_memory
from run_logger import log_run, read_last, search


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


def main():
    parser = argparse.ArgumentParser(description="Local agent CLI (chat + json + memory + router).")
    parser.add_argument("task", nargs="?", default="", help="Task to run (wrap in quotes).")

    # Modes
    parser.add_argument("--chat", action="store_true", help="Plain text response (no JSON).")
    parser.add_argument("--use-memory", action="store_true", help="Ground answer strictly in saved memory.")
    parser.add_argument("--router", action="store_true", help="Auto: use memory only when --memory-query is provided and returns context.")

    # Quality controls
    parser.add_argument("--strict", action="store_true", help="Do not guess facts; say unknown/varies when unsure.")
    parser.add_argument("--verify", action="store_true", help="Add claims_to_verify + how_to_verify fields (self-audit).")

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

    args = parser.parse_args()

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
        print("Provide a task, or use --show-memory / --add-memory / --show-log.")
        return

    # Build memory context if requested
    q = args.memory_query.strip() or None
    ctx = memory_as_context(query=q, limit=args.memory_limit)

    saved_path = ""

    # Chat mode (plain text)
    if args.chat:
        text = generate(args.task, stream=False)
        print(text)
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
            mode = "router->memory"
            title = printable.get("title", "Result")
        else:
            data = run_json_agent(args.task, strict=args.strict, verify=args.verify)
            print(json.dumps(data, indent=2))
            mode = "router->json"
            title = data.get("title", "Result")

        if args.save and isinstance(data, dict):
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

        if args.save:
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

    if args.save:
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