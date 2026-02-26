#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -x "$ROOT/.venv/bin/python3" ]]; then
  PY="$ROOT/.venv/bin/python3"
  export PATH="$ROOT/.venv/bin:$PATH"
else
  PY="python3"
fi

$PY -m pytest -q

bash scripts/run_eval_pack.sh
