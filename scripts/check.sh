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
  export PY
fi

if [[ "${AI_DENEY_VERBOSE:-0}" == "1" ]]; then
  echo "python_path=$PY"
  "$PY" -V
fi

"$PY" -m pytest -q

bash scripts/run_eval_pack.sh
