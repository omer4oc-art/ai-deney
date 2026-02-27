#!/usr/bin/env bash
set -euo pipefail

EXPECTED_ROOT="/Users/omer/ai-deney/week1"
FIX_CMD="cd /Users/omer/ai-deney/week1 && source .venv/bin/activate"

_fail() {
  echo "dev_check: $1" >&2
  echo "Fix: $FIX_CMD" >&2
  exit 1
}

CURRENT_DIR="$(pwd -P)"
if [[ "$CURRENT_DIR" != "$EXPECTED_ROOT" ]]; then
  _fail "wrong directory: $CURRENT_DIR (expected: $EXPECTED_ROOT)"
fi

if [[ ! -f "batch_agent.py" || ! -f "pytest.ini" || ! -d "src/ai_deney" ]]; then
  _fail "repo root markers missing (need batch_agent.py, pytest.ini, src/ai_deney/)"
fi

EXPECTED_VENV="$EXPECTED_ROOT/.venv"
if [[ ! -d "$EXPECTED_VENV" || ! -x "$EXPECTED_VENV/bin/python3" ]]; then
  _fail "missing virtual environment at $EXPECTED_VENV"
fi

ACTIVE_VENV="${VIRTUAL_ENV:-}"
if [[ -z "$ACTIVE_VENV" ]]; then
  _fail "virtual environment is not active"
fi

ACTIVE_VENV_REAL="$(cd "$ACTIVE_VENV" 2>/dev/null && pwd -P || true)"
EXPECTED_VENV_REAL="$(cd "$EXPECTED_VENV" && pwd -P)"
if [[ "$ACTIVE_VENV_REAL" != "$EXPECTED_VENV_REAL" ]]; then
  _fail "wrong virtual environment: $ACTIVE_VENV_REAL (expected: $EXPECTED_VENV_REAL)"
fi

echo "dev_check: OK"
