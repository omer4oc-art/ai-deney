import json
import os
from datetime import datetime
from typing import Any, Dict, Optional

LOG_DIR = "runs"
LOG_PATH = os.path.join(LOG_DIR, "runs.jsonl")  # newline-delimited JSON

def log_run(event: Dict[str, Any]) -> str:
    """
    Append one event to runs/runs.jsonl and return the path.
    """
    os.makedirs(LOG_DIR, exist_ok=True)

    # Ensure timestamp
    event = dict(event)
    event.setdefault("ts", datetime.now().isoformat(timespec="seconds"))

    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")

    return LOG_PATH

def read_last(n: int = 20) -> list[dict]:
    if not os.path.exists(LOG_PATH):
        return []
    out = []
    with open(LOG_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    return out[-n:]
