#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -f "$ROOT/.venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source "$ROOT/.venv/bin/activate"
fi

python3 - <<'PY'
import importlib.util
import sys
missing = [m for m in ("fastapi", "uvicorn", "multipart") if importlib.util.find_spec(m) is None]
if missing:
    sys.stderr.write(
        "run_electra_test_portal: missing dependencies: " + ", ".join(missing) + "\n"
    )
    if any(m in {"fastapi", "uvicorn"} for m in missing):
        sys.stderr.write("Install inside .venv: pip install fastapi uvicorn\n")
    if "multipart" in missing:
        sys.stderr.write("Install inside .venv: python3 -m pip install python-multipart\n")
    raise SystemExit(2)
PY

exec python3 -m uvicorn app:app --app-dir tools/electra_test_portal --host 127.0.0.1 --port 8008
