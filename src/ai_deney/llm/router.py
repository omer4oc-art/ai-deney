"""Placeholder LLM router scaffold for future staged routing."""

from __future__ import annotations

import os


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

