#!/usr/bin/env bash
set -euo pipefail

MINUTES=""
ITERATIONS="200"
SLEEP_SECONDS="1"
STOP_ON_FAIL="1"
MAX_RUNS_KEPT="50"
OUTBASE="outputs/soak_runs"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --minutes) MINUTES="${2:-}"; shift 2 ;;
    --iterations) ITERATIONS="${2:-}"; shift 2 ;;
    --sleep-seconds) SLEEP_SECONDS="${2:-}"; shift 2 ;;
    --stop-on-fail) STOP_ON_FAIL="1"; shift ;;
    --no-stop-on-fail) STOP_ON_FAIL="0"; shift ;;
    --max-runs-kept) MAX_RUNS_KEPT="${2:-}"; shift 2 ;;
    --outbase) OUTBASE="${2:-}"; shift 2 ;;
    *)
      echo "Unknown arg: $1" >&2
      exit 2
      ;;
  esac
done

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

TS="$(date +%Y%m%d-%H%M%S)"
SOAK_DIR="$OUTBASE/$TS"
RUNS_DIR="$SOAK_DIR/runs"
SUMMARY_JSONL="$SOAK_DIR/soak_summary.jsonl"
mkdir -p "$RUNS_DIR"

START_EPOCH="$(date +%s)"
FAILURES=0
ITER=0
STOP_REQUESTED=0

on_interrupt() {
  STOP_REQUESTED=1
  echo ""
  echo "Interrupted. iterations=$ITER failures=$FAILURES summary=$SUMMARY_JSONL"
}
trap on_interrupt INT TERM

json_escape() {
  printf '%s' "${1:-}" | sed 's/\\/\\\\/g; s/"/\\"/g'
}

should_continue() {
  if [[ "$STOP_REQUESTED" == "1" ]]; then
    return 1
  fi
  if [[ -n "$MINUTES" ]]; then
    local now elapsed max_s
    now="$(date +%s)"
    elapsed="$((now - START_EPOCH))"
    max_s="$((MINUTES * 60))"
    [[ "$elapsed" -lt "$max_s" ]]
    return
  fi
  [[ "$ITER" -lt "$ITERATIONS" ]]
}

rotate_runs() {
  local dirs=()
  while IFS= read -r d; do
    dirs+=("$d")
  done < <(find "$RUNS_DIR" -mindepth 1 -maxdepth 1 -type d | sort)
  local n="${#dirs[@]}"
  if (( n <= MAX_RUNS_KEPT )); then
    return 0
  fi
  local to_del=$((n - MAX_RUNS_KEPT))
  local i=0
  while (( i < to_del )); do
    rm -rf "${dirs[$i]}"
    i=$((i + 1))
  done
}

while should_continue; do
  ITER=$((ITER + 1))
  RUN_DIR="$RUNS_DIR/iter-$(printf '%04d' "$ITER")"
  mkdir -p "$RUN_DIR"
  RUN_DIR_REL="runs/iter-$(printf '%04d' "$ITER")"
  LOG_PATH_REL="$RUN_DIR_REL/pytest.log"
  RUN_LOG="$RUN_DIR/pytest.log"
  T0="$(date +%s)"

  if bash scripts/run_eval_pack.sh --keep-artifacts >"$RUN_LOG" 2>&1; then
    RC=0
    STATUS="PASS"
  else
    RC=$?
    STATUS="FAIL"
    FAILURES=$((FAILURES + 1))
  fi
  T1="$(date +%s)"
  DUR="$((T1 - T0))"
  printf '%s\n' "$RC" > "$RUN_DIR/exit_code.txt"
  printf '%s\n' "$DUR" > "$RUN_DIR/duration_seconds.txt"

  FAILURE_ARTIFACTS=""
  if [[ "$STATUS" == "FAIL" ]]; then
    saved_line="$(grep -E '^artifacts_saved_to=' "$RUN_LOG" | tail -n 1 || true)"
    if [[ -n "$saved_line" ]]; then
      FAILURE_ARTIFACTS="${saved_line#artifacts_saved_to=}"
    else
      latest_fail="$(ls -1dt outputs/eval_failures/* 2>/dev/null | head -n 1 || true)"
      if [[ -n "$latest_fail" ]]; then
        FAILURE_ARTIFACTS="$latest_fail"
      fi
    fi
    if [[ -n "$FAILURE_ARTIFACTS" ]]; then
      cp "$RUN_LOG" "$FAILURE_ARTIFACTS/pytest.log" || true
      printf '%s\n' "$RC" > "$FAILURE_ARTIFACTS/exit_code.txt" || true
    fi
  fi

  FAILURE_ESC="$(json_escape "$FAILURE_ARTIFACTS")"
  LOG_ESC="$(json_escape "$LOG_PATH_REL")"
  RUN_ESC="$(json_escape "$RUN_DIR_REL")"
  printf '{"iteration":%d,"status":"%s","duration_seconds":%d,"exit_code":%d,"failure_artifacts":"%s","run_dir":"%s","log_path":"%s"}\n' \
    "$ITER" "$STATUS" "$DUR" "$RC" "$FAILURE_ESC" "$RUN_ESC" "$LOG_ESC" >> "$SUMMARY_JSONL"

  if [[ -f gate_report.json ]]; then
    cp gate_report.json "$RUN_DIR/" || true
  fi
  rotate_runs

  if [[ "$STATUS" == "FAIL" && "$STOP_ON_FAIL" == "1" ]]; then
    echo "Stopping on failure at iteration $ITER"
    echo "summary=$SUMMARY_JSONL"
    exit 1
  fi

  sleep "$SLEEP_SECONDS"
done

echo "Completed. iterations=$ITER failures=$FAILURES summary=$SUMMARY_JSONL"
exit 0
