#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -z "${VIRTUAL_ENV:-}" ]]; then
  echo "No active virtualenv detected. Activate with: source .venv/bin/activate" >&2
  echo "Continuing with repository interpreter fallback." >&2
fi

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

echo "Seeding deterministic toy portal DB for E2E lane..."
"$PY" -m tools.toy_hotel_portal.seed \
  --db "$ROOT/data/toy_portal/toy.db" \
  --rows 3000 \
  --seed 42 \
  --date-start 2025-01-01 \
  --date-end 2025-12-31 \
  --hot-range 2025-06-19:2025-06-25 \
  --hot-occupancy 0.75 \
  --reset

echo "Running integration tests..."
"$PY" -m pytest -q -m integration

echo "E2E artifacts directory: $ROOT/outputs/_e2e"
