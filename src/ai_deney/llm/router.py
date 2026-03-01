"""Placeholder LLM router scaffold for future staged routing."""

from __future__ import annotations

import json
import os
from pathlib import Path


def is_llm_router_enabled() -> bool:
    """
    Feature flag for future optional LLM routing.

    Disabled by default. Current deterministic pipeline does not invoke any LLM
    calls unless this env var is explicitly set to ``1``.
    """

    return os.getenv("AI_DENEY_ENABLE_LLM_ROUTER", "0").strip() == "1"


def route_task(task_type: str, payload: dict) -> str:
    """
    Placeholder router hook.

    Future direction:
    - local LLM for intent classification
    - stronger model for strategy/explanation generation
    - overseer validation pass for structured outputs

    This function intentionally remains deterministic and non-networked.
    """

    if not is_llm_router_enabled():
        raise RuntimeError("LLM router disabled (set AI_DENEY_ENABLE_LLM_ROUTER=1 to enable scaffold path)")
    _ = payload
    return f"ROUTER_STUB:{task_type}"


def _load_stub_payload(path: Path) -> dict[str, object]:
    if not path.exists():
        raise RuntimeError(f"toy router stub file not found: {path}")
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"toy router stub file is not valid JSON: {path}") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("toy router stub payload must be a JSON object")
    return {str(k): v for k, v in parsed.items()}


def route_toy_query_spec(question: str) -> dict[str, object]:
    """
    Deterministic toy-router stub for LLM intent mode.

    The stub reads JSON from one of:
    - AI_DENEY_TOY_LLM_STUB_JSON
    - AI_DENEY_TOY_LLM_STUB_FILE
    """

    _ = question
    stub_json = os.getenv("AI_DENEY_TOY_LLM_STUB_JSON", "").strip()
    stub_file = os.getenv("AI_DENEY_TOY_LLM_STUB_FILE", "").strip()

    if stub_json:
        try:
            parsed = json.loads(stub_json)
        except Exception as exc:
            raise RuntimeError("AI_DENEY_TOY_LLM_STUB_JSON is not valid JSON") from exc
        if not isinstance(parsed, dict):
            raise RuntimeError("AI_DENEY_TOY_LLM_STUB_JSON must be a JSON object")
        return {str(k): v for k, v in parsed.items()}

    if stub_file:
        return _load_stub_payload(Path(stub_file).expanduser().resolve())

    raise RuntimeError(
        "llm mode requires a stubbed router payload. "
        "Set AI_DENEY_TOY_LLM_STUB_JSON or AI_DENEY_TOY_LLM_STUB_FILE."
    )
