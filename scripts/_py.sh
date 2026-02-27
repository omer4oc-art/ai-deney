#!/usr/bin/env bash

# Shared python selector for repo scripts.
# Prefer local venv, fall back to system python3.
if [[ -n "${ROOT:-}" ]]; then
  _AI_DENEY_ROOT="$ROOT"
else
  _AI_DENEY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fi

if [[ -x "$_AI_DENEY_ROOT/.venv/bin/python3" ]]; then
  PY="$_AI_DENEY_ROOT/.venv/bin/python3"
else
  PY="python3"
fi
export PY
