#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

bash scripts/dev_check.sh

if [[ -f "$ROOT/scripts/_py.sh" ]]; then
  # shellcheck disable=SC1091
  source "$ROOT/scripts/_py.sh"
else
  PY="python3"
  export PY
fi

"$PY" scripts/generate_truth_pack.py --out outputs/_truth_pack --use-inbox 1 "$@"

echo "truth_pack_index=$(pwd -P)/outputs/_truth_pack/index.md"
