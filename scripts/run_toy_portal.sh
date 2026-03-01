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

FORCE_SEED=0
SEED_ONLY=0
SEED_CONFIG_SET=0
SEED_ARGS=()

usage() {
  cat <<'EOF'
Usage: scripts/run_toy_portal.sh [--seed] [--seed-only] [seed options]

Options:
  --seed                     Force reseed before start (existing behavior).
  --seed <INT>               Force reseed and pass deterministic seed value.
  --seed-only                Only seed DB, do not start server.
  --rows <N>                 Seed row count (default 200).
  --date-start <YYYY-MM-DD>  Seed range start date (default 2025-01-01).
  --date-end <YYYY-MM-DD>    Seed range end date (default 2025-12-31).
  --hot-range <S:E>          High-occupancy range, inclusive (default 2025-06-19:2025-06-25).
  --hot-occupancy <FLOAT>    Hot-range target occupancy ratio 0..1 (default 0.75).

Examples:
  scripts/run_toy_portal.sh --seed-only
  scripts/run_toy_portal.sh --seed --rows 1000 --hot-occupancy 0.82
  scripts/run_toy_portal.sh --seed 77 --date-start 2025-01-01 --date-end 2025-12-31 --hot-range 2025-06-19:2025-06-25
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --help|-h)
      usage
      exit 0
      ;;
    --seed)
      FORCE_SEED=1
      if [[ $# -ge 2 && "$2" =~ ^-?[0-9]+$ ]]; then
        SEED_ARGS+=("--seed" "$2")
        SEED_CONFIG_SET=1
        shift
      fi
      ;;
    --seed-only)
      FORCE_SEED=1
      SEED_ONLY=1
      ;;
    --rows|--date-start|--date-end|--hot-range|--hot-occupancy)
      if [[ $# -lt 2 ]]; then
        echo "Missing value for option: $1" >&2
        usage >&2
        exit 2
      fi
      SEED_ARGS+=("$1" "$2")
      SEED_CONFIG_SET=1
      shift
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

if [[ "$SEED_CONFIG_SET" == "1" ]]; then
  FORCE_SEED=1
fi

DB_PATH="$ROOT/data/toy_portal/toy.db"
if [[ ! -f "$DB_PATH" ]]; then
  "$PY" -m tools.toy_hotel_portal.seed --db "$DB_PATH" "${SEED_ARGS[@]}"
elif [[ "$FORCE_SEED" == "1" ]]; then
  "$PY" -m tools.toy_hotel_portal.seed --db "$DB_PATH" --reset "${SEED_ARGS[@]}"
fi

if [[ "$SEED_ONLY" == "1" ]]; then
  echo "toy_portal_seed_only=1 db=$DB_PATH"
  exit 0
fi

if ! "$PY" -c "import fastapi, uvicorn, multipart" >/dev/null 2>&1; then
  echo "Missing deps for toy portal." >&2
  echo "Install with: $PY -m pip install fastapi uvicorn python-multipart" >&2
  exit 2
fi

HOST="${TOY_PORTAL_HOST:-127.0.0.1}"
PORT="${TOY_PORTAL_PORT:-8011}"

echo "toy_portal_url=http://${HOST}:${PORT}/"
exec "$PY" -m uvicorn tools.toy_hotel_portal.app:app --host "$HOST" --port "$PORT"
