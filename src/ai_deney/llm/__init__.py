"""LLM-related scaffolding (disabled by default)."""

from .router import is_llm_router_enabled, route_task

__all__ = ["is_llm_router_enabled", "route_task"]

