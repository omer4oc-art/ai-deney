import argparse
import json
import os
from datetime import datetime

from ollama_client import OllamaNotRunning, generate
from json_agent import run as run_json
from memory_agent import run as run_memory
from memory import add_memory, list_memory, memory_as_context


def save_json(data: dict, out: str = "") -> str:
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
    parser.add_argument("--json", action="store_true", help="Structured JSON response (title + 5 bullets).")
    parser.add_argument("--use-memory", action="store_true", help="Ground answer strictly in saved memory.")
    parser.add_argument("--router", action="store_true", help="Auto: use memory if available, else normal JSON.")

    # Memory controls
    parser.add_argument("--memory-query", default="", help="Filter memory context by keyword (e.g., week1).")
    parser.add_argument("--memory-limit", type=int, default=10, help="How many memory items to include.")
    parser.add_argument("--show-memory", action="store_true", help="Print memory and exit.")
    parser.add_argument("--add-memory", default="", help="Add a memory note (string).")
    parser.add_argument("--tags", default="", help="Comma-separated tags for --add-memory (e.g., week1,setup).")

    # Output
    parser.add_argument("--save", action="store_true", help="Save JSON output to outputs/.")
    parser.add_argument("--out", default="", help="Custom JSON output path.")

    args = parser.parse_args()

    # Memory admin
    if args.add_memory:
        tags = [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else []
        item = add_memory(args.add_memory, tags=tags, source="manual")
        print(f"Saved memory: ({item['id']}) {item['text']}")
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
        print("Provide a task, or use --show-memory / --add-memory.")
        return

    # Chat mode
    if args.chat:
        print(generate(args.task, stream=False))
        return

    # Build memory context if needed
    q = args.memory_query.strip() or None
    ctx = memory_as_context(query=q, limit=args.memory_limit)

    # Router mode: if memory exists, use memory agent; otherwise normal JSON agent
    if args.router:
        if ctx.strip():
            data = run_memory(args.task, context=ctx)
        else:
            data = run_json(args.task)
        print(json.dumps({k: v for k, v in data.items() if k != "memory_to_save"}, indent=2))
        if args.save:
            path = save_json(data, args.out)
            print(f"\nSaved to: {path}")
        return

    # Explicit memory mode
    if args.use_memory:
        data = run_memory(args.task, context=ctx)
        print(json.dumps({k: v for k, v in data.items() if k != "memory_to_save"}, indent=2))
        if args.save:
            path = save_json(data, args.out)
            print(f"\nSaved to: {path}")
        return

    # Default: JSON mode (unless user forced otherwise)
    # If --json is provided, do JSON (same default behavior)
    data = run_json(args.task)
    print(json.dumps(data, indent=2))
    if args.save:
        path = save_json(data, args.out)
        print(f"\nSaved to: {path}")


if __name__ == "__main__":
    try:
        main()
    except OllamaNotRunning as e:
        print(str(e))
        raise SystemExit(1)