#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -x ".venv/bin/pytest" ]]; then
  .venv/bin/pytest -q
else
  python -m pytest -q
fi

bash scripts/run_eval_pack.sh
