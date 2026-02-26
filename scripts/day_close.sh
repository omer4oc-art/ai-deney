#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

KEEP_BATCHES="${KEEP_BATCHES:-5}"       # keep newest N outputs/batch-*
KEEP_TASK_FILES="${KEEP_TASK_FILES:-8}" # keep newest N tasks_*.txt in repo root

ts="$(date +%Y%m%d-%H%M%S)"
day_dir="archive/day-closes/day-${ts}"
mkdir -p "$day_dir"

echo "[1/4] Backup handoff/"
mkdir -p archive/handoff-backups
tar -czf "archive/handoff-backups/handoff-${ts}.tar.gz" handoff

echo "[2/4] Archive old batch outputs (keep newest ${KEEP_BATCHES})"
mkdir -p "$day_dir/outputs"

# Build list of batch dirs sorted oldest->newest
batches="$(ls -1d outputs/batch-* 2>/dev/null | sort || true)"
if [[ -n "${batches}" ]]; then
  count="$(printf "%s\n" "$batches" | wc -l | tr -d ' ')"
  if (( count > KEEP_BATCHES )); then
    move_n=$((count - KEEP_BATCHES))
    printf "%s\n" "$batches" | head -n "$move_n" | while IFS= read -r b; do
      mv "$b" "$day_dir/outputs/"
    done
    echo "Moved ${move_n} batch dirs to $day_dir/outputs/"
  else
    echo "No old batch dirs to move"
  fi
else
  echo "No batch dirs found"
fi

echo "[3/4] Archive old root tasks files (keep newest ${KEEP_TASK_FILES})"
mkdir -p "$day_dir/tasks"

tasks="$(ls -1t tasks_*.txt 2>/dev/null || true)"
if [[ -n "${tasks}" ]]; then
  tcount="$(printf "%s\n" "$tasks" | wc -l | tr -d ' ')"
  if (( tcount > KEEP_TASK_FILES )); then
    printf "%s\n" "$tasks" | tail -n "$((tcount - KEEP_TASK_FILES))" | while IFS= read -r f; do
      mv "$f" "$day_dir/tasks/"
    done
    echo "Moved $((tcount - KEEP_TASK_FILES)) task files to $day_dir/tasks/"
  else
    echo "No old tasks_*.txt to move"
  fi
else
  echo "No tasks_*.txt found"
fi

echo "[4/4] Summary"
echo "Day-close archive: $day_dir"
echo "Handoff backup: archive/handoff-backups/handoff-${ts}.tar.gz"
echo "Remaining batches: $(ls -1d outputs/batch-* 2>/dev/null | wc -l | tr -d ' ')"
