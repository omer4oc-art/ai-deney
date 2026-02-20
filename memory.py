import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

MEMORY_PATH = "memory.json"

def _load() -> Dict[str, Any]:
    if not os.path.exists(MEMORY_PATH):
        return {"items": []}
    with open(MEMORY_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def _save(mem: Dict[str, Any]) -> None:
    with open(MEMORY_PATH, "w", encoding="utf-8") as f:
        json.dump(mem, f, indent=2)

def add_memory(text: str, tags: Optional[List[str]] = None, source: str = "manual") -> Dict[str, Any]:
    mem = _load()
    item = {
        "id": f"m_{len(mem['items'])+1:04d}",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "text": text.strip(),
        "tags": tags or [],
        "source": source,
    }
    mem["items"].append(item)
    _save(mem)
    return item

def list_memory(limit: int = 50) -> List[Dict[str, Any]]:
    mem = _load()
    return mem["items"][-limit:]

def search_memory(query: str, limit: int = 10) -> List[Dict[str, Any]]:
    q = query.lower().strip()
    mem = _load()
    out = []
    for it in mem["items"]:
        hay = (it.get("text", "") + " " + " ".join(it.get("tags", []))).lower()
        if q in hay:
            out.append(it)
    return out[-limit:]

def memory_as_context(query: Optional[str] = None, limit: int = 10) -> str:
    items = search_memory(query, limit=limit) if query else list_memory(limit=limit)
    if not items:
        return ""
    lines = []
    for it in items:
        tag_str = f" [tags: {', '.join(it['tags'])}]" if it.get("tags") else ""
        lines.append(f"- ({it['id']}) {it['text']}{tag_str}")
    return "\n".join(lines)