#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -f "$ROOT/scripts/_py.sh" ]]; then
  # shellcheck disable=SC1091
  source "$ROOT/scripts/_py.sh"
else
  if [[ -x "$ROOT/.venv/bin/python3" ]]; then
    PY="$ROOT/.venv/bin/python3"
  else
    PY="python3"
  fi
fi

if ! "$PY" -c "import fastapi, uvicorn" >/dev/null 2>&1; then
  echo "Missing required deps for viewer." >&2
  echo "Install with: $PY -m pip install fastapi uvicorn" >&2
  exit 2
fi

if ! "$PY" -c "import markdown" >/dev/null 2>&1; then
  echo "Optional dependency 'markdown' not found; using built-in fallback renderer." >&2
  echo "For richer Markdown rendering: $PY -m pip install markdown" >&2
fi

HOST="${VIEWER_HOST:-127.0.0.1}"
PORT="${VIEWER_PORT:-8010}"

echo "viewer_url=http://${HOST}:${PORT}/"
exec "$PY" -m uvicorn tools.viewer.app:app --host "$HOST" --port "$PORT"
