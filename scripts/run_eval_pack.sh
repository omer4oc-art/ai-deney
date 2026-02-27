#!/usr/bin/env bash
set -euo pipefail

VERBOSE=0
KEEP_ARTIFACTS=0
JUNIT_PATH=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --verbose) VERBOSE=1; shift ;;
    --keep-artifacts) KEEP_ARTIFACTS=1; shift ;;
    --junit) JUNIT_PATH="${2:-}"; shift 2 ;;
    *)
      echo "Unknown arg: $1" >&2
      exit 2
      ;;
  esac
done

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

if ! "$PY" -c "import pytest" >/dev/null 2>&1; then
  echo "pytest not found for interpreter: $PY" >&2
  exit 2
fi

PYTEST_CMD=("$PY" -m pytest)
ARGS=(-q tests/eval_pack)
if [[ "$VERBOSE" == "1" ]]; then
  ARGS=(-q -vv tests/eval_pack)
fi
if [[ -n "$JUNIT_PATH" ]]; then
  ARGS+=(--junitxml "$JUNIT_PATH")
fi

START_TS="$(date +%s)"
PYTEST_LOG="$(mktemp)"
if "${PYTEST_CMD[@]}" "${ARGS[@]}" >"$PYTEST_LOG" 2>&1; then
  RC=0
else
  RC=$?
fi
END_TS="$(date +%s)"
DUR="$((END_TS - START_TS))"
cat "$PYTEST_LOG"

STATUS="FAIL"
if [[ "$RC" -eq 0 ]]; then
  STATUS="PASS"
fi

echo "eval_pack_status=$STATUS"
echo "duration_seconds=$DUR"
echo "pytest_exit_code=$RC"

if [[ "$RC" -ne 0 && "$KEEP_ARTIFACTS" == "1" ]]; then
  TS="$(date +%Y%m%d-%H%M%S)"
  DEST="outputs/eval_failures/$TS"
  mkdir -p "$DEST"
  cp "$PYTEST_LOG" "$DEST/pytest_stdout_stderr.log" || true
  if [[ -d tests/_tmp_tasks/eval_pack ]]; then
    cp -R tests/_tmp_tasks/eval_pack "$DEST/" || true
  fi
  find . -maxdepth 2 -type d -name "case*" -path "*/pytest-*/*" -print0 2>/dev/null | while IFS= read -r -d '' d; do
    cp -R "$d" "$DEST/" || true
  done
  echo "artifacts_saved_to=$DEST"
fi

rm -f "$PYTEST_LOG"
exit "$RC"
