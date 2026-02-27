"""Report registry for routing QuerySpec targets to executor callables."""

from __future__ import annotations

from collections.abc import Callable

ExecutorFn = Callable[[list[int]], object]


class ReportRegistry:
    """Simple deterministic registry for report executors."""

    def __init__(self) -> None:
        self._executors: dict[str, ExecutorFn] = {}

    def register(self, key: str, fn: ExecutorFn) -> None:
        if key in self._executors:
            raise ValueError(f"registry key already exists: {key}")
        self._executors[key] = fn

    def get(self, key: str) -> ExecutorFn:
        if key not in self._executors:
            known = ", ".join(sorted(self._executors.keys()))
            raise KeyError(f"unknown report key: {key} (known: {known})")
        return self._executors[key]

    def keys(self) -> list[str]:
        return sorted(self._executors.keys())

