import argparse
import json
import os
from datetime import datetime

from ollama_client import OllamaNotRunning
from agent_json import run as run_json_agent
from memory_agent import run as run_memory_agent
from memory import add_memory, memory_as_context, list_memory


def main():
    parser = argparse.ArgumentParser(description="Local agent (Ollama) with optional memory.")
    parser.add_argument("task", nargs="?", default="", help="Task to run (wrap in quotes).")

    # Output options
    parser.add_argument("--chat", action="store_true", help="Return plain text instead of JSON bullets")
    parser.add_argument("--save", action="store_true", help="Save output JSON to outputs/ folder (JSON modes only).")
    parser.add_argument("--out", default="", help="Custom output filename (optional).")

    # Memory features
    parser.add_argument("--remember", action="store_true", help="Store a memory note if the task explicitly says 'save this to memory:'.")
    parser.add_argument("--use-memory", action="store_true", help="Include saved memory as context for the task.")
    parser.add_argument("--memory-query", default="", help="Search memory and include only matching items as context.")
    parser.add_argument("--show-memory", action="store_true", help="Print saved memory and exit.")
    parser.add_argument("--memory-limit", type=int, default=10, help="How many memory items to include/show.")

    args = parser.parse_args()

    # Show memory and exit
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
        print("Please provide a task, or use --show-memory.")
        return

    # Chat mode: plain text output (no JSON)
    if args.chat:
        from ollama_client import generate
        print(generate(args.task, stream=False))
        return

    # Build memory context if requested
    context = ""
    if args.use_memory:
        q = args.memory_query.strip() or None
        context = memory_as_context(query=q, limit=args.memory_limit)

    # Choose which agent to run
    if args.use_memory or args.remember:
        data = run_memory_agent(args.task, context=context)
        # Print JSON result but hide memory_to_save field
        print(json.dumps({k: v for k, v in data.items() if k != "memory_to_save"}, indent=2))

        # Save memory only when user asked for --remember AND agent produced a note
        mem_note = (data.get("memory_to_save") or "").strip()
        if args.remember and mem_note:
            item = add_memory(mem_note, tags=["auto"], source="memory_agent")
            print(f"\nSaved memory: ({item['id']}) {item['text']}")
        elif args.remember:
            print("\nNo memory saved (memory_to_save was empty).")
    else:
        data = run_json_agent(args.task)
        print(json.dumps(data, indent=2))

    # Save JSON output to file (only meaningful in JSON modes)
    if args.save:
        os.makedirs("outputs", exist_ok=True)
        if args.out:
            path = args.out
        else:
            ts = datetime.now().strftime("%Y%m%d-%H%M%S")
            path = f"outputs/{ts}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        print(f"\nSaved to: {path}")


if __name__ == "__main__":
    try:
        main()
    except OllamaNotRunning as e:
        print(str(e))
        raise SystemExit(1)