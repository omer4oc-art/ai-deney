from __future__ import annotations
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent

class UnsafePathError(RuntimeError):
    pass

def _safe_path(rel_path: str) -> Path:
    p = (PROJECT_ROOT / rel_path).expanduser().resolve()
    if not str(p).startswith(str(PROJECT_ROOT)):
        raise UnsafePathError(f"Refusing to access outside project folder: {p}")
    return p

def read_text(rel_path: str, max_chars: int = 50_000) -> str:
    p = _safe_path(rel_path)
    if not p.exists():
        raise FileNotFoundError(f"File not found: {p}")
    text = p.read_text(encoding="utf-8", errors="replace")
    if len(text) > max_chars:
        return text[:max_chars] + "\n\n[TRUNCATED]"
    return text

def write_text(rel_path: str, content: str) -> str:
    p = _safe_path(rel_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return str(p)
