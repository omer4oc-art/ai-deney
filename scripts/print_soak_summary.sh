#!/usr/bin/env bash
set -euo pipefail

SOAK_DIR="${1:-}"
if [[ -z "$SOAK_DIR" || ! -d "$SOAK_DIR" ]]; then
  echo "Usage: scripts/print_soak_summary.sh <soak_dir>" >&2
  exit 2
fi

SUMMARY="$SOAK_DIR/soak_summary.jsonl"
if [[ ! -f "$SUMMARY" ]]; then
  echo "Missing summary file: $SUMMARY" >&2
  exit 2
fi

TOTAL="$(wc -l < "$SUMMARY" | tr -d ' ')"
FAILS="$(grep -c '"status":"FAIL"' "$SUMMARY" || true)"
echo "total_iterations=$TOTAL"
echo "failures=$FAILS"

# Optional aggregate from kept gate_report.json files.
TMP_CODES="$(mktemp)"
trap 'rm -f "$TMP_CODES"' EXIT
find "$SOAK_DIR/runs" -type f -name "gate_report.json" -print0 2>/dev/null | while IFS= read -r -d '' f; do
  sed -n 's/.*"\([A-Z_][A-Z0-9_]*\)":[[:space:]]*[0-9][0-9]*/\1/p' "$f" >> "$TMP_CODES" || true
done
if [[ -s "$TMP_CODES" ]]; then
  echo "gate_codes_seen:"
  sort "$TMP_CODES" | uniq -c | awk '{print $2"="$1}'
fi
