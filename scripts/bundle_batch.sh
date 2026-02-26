#!/usr/bin/env bash
set -euo pipefail

# Bundle a batch directory into a deterministic single text file for copy/paste review.
# Usage:
#   scripts/bundle_batch.sh outputs/batch-YYYYMMDD-HHMMSS
#   scripts/bundle_batch.sh --latest

MAX_BYTES_PER_FILE="${MAX_BYTES_PER_FILE:-200000}"   # 200 KB cap per file section
MAX_FILES="${MAX_FILES:-2000}"                       # cap for generated tree
WARN_BUNDLE_BYTES="${WARN_BUNDLE_BYTES:-5000000}"    # warn if bundle exceeds 5 MB
MAP_REFS_FILE=""
EMITTED_RELS_FILE=""

pick_latest_batch() {
  ls -1d outputs/batch-* 2>/dev/null | sort | tail -n 1
}

if [[ "${1:-}" == "--latest" ]]; then
  BATCH_DIR="$(pick_latest_batch)"
  shift
else
  BATCH_DIR="${1:-}"
fi

if [[ -z "${BATCH_DIR:-}" ]]; then
  echo "ERROR: provide a batch dir or use --latest" >&2
  echo "Failure mode: no batch dir argument and no latest batch found." >&2
  exit 2
fi

if [[ ! -d "$BATCH_DIR" ]]; then
  echo "ERROR: not a directory: $BATCH_DIR" >&2
  echo "Failure mode: batch directory missing." >&2
  exit 2
fi

OUT="$BATCH_DIR/bundle.txt"

is_probably_text_file() {
  local f="$1"
  [[ ! -f "$f" ]] && return 1
  # Empty files are considered text for bundling.
  [[ ! -s "$f" ]] && return 0
  grep -Iq . "$f"
}

emit_file() {
  local f="$1"
  local rel="${f#$BATCH_DIR/}"
  local summary="${2:-}"
  if [[ -z "$summary" ]]; then
    summary="$(lookup_gate_summary "$rel")"
  fi
  if already_emitted_rel "$rel"; then
    return 0
  fi

  local size
  size="$(wc -c < "$f" | tr -d ' ')"

  echo ""
  if [[ -n "$summary" ]]; then
    echo "GATE_SUMMARY: $summary"
  fi
  echo "===== FILE: $rel (bytes=$size) ====="

  if ! is_probably_text_file "$f"; then
    echo "[SKIPPED: binary or non-text file]"
    mark_emitted_rel "$rel"
    return 0
  fi

  if (( size > MAX_BYTES_PER_FILE )); then
    echo "[SKIPPED: file too large > ${MAX_BYTES_PER_FILE} bytes]"
    mark_emitted_rel "$rel"
    return 0
  fi

  cat "$f"
  mark_emitted_rel "$rel"
}

already_emitted_rel() {
  local rel="$1"
  [[ -f "$EMITTED_RELS_FILE" ]] || return 1
  grep -Fqx "$rel" "$EMITTED_RELS_FILE"
}

mark_emitted_rel() {
  local rel="$1"
  [[ -n "$rel" ]] || return 0
  if ! already_emitted_rel "$rel"; then
    printf "%s\n" "$rel" >> "$EMITTED_RELS_FILE"
  fi
}

build_index_reference_map() {
  local index_file="$BATCH_DIR/index.md"
  [[ ! -f "$index_file" ]] && return 0

  : > "$MAP_REFS_FILE"
  awk '
    BEGIN { task=0; summary="" }
    /^## / { task++; summary=""; next }
    /- gate-summary: `/ {
      if (match($0, /`[^`]*`/)) {
        summary = substr($0, RSTART + 1, RLENGTH - 2)
      } else {
        summary = ""
      }
      next
    }
    /- output: `/ || /- wrote: `/ {
      ref = ""
      if (match($0, /`[^`]*`/)) {
        ref = substr($0, RSTART + 1, RLENGTH - 2)
      }
      if (ref != "") {
        print ref "\t" summary
      }
      next
    }
  ' "$index_file" > "$MAP_REFS_FILE"
}

lookup_gate_summary() {
  local rel="$1"
  [[ -f "$MAP_REFS_FILE" ]] || return 0
  awk -F'\t' -v key="$rel" '$1 == key { print $2; exit }' "$MAP_REFS_FILE"
}

emit_index_referenced_outputs() {
  local index_file="$BATCH_DIR/index.md"
  [[ -f "$index_file" ]] || return 0

  while IFS= read -r line; do
    case "$line" in
      *"- output: "*|*"- wrote: "*)
        local ref
        ref="$(printf "%s\n" "$line" | sed -n 's/.*`\(.*\)`.*/\1/p' | head -n 1)"
        [[ -z "$ref" ]] && continue
        local summary
        summary="$(lookup_gate_summary "$ref")"
        if [[ -f "$BATCH_DIR/$ref" ]]; then
          emit_file "$BATCH_DIR/$ref" "$summary"
        else
          echo ""
          if [[ -n "$summary" ]]; then
            echo "GATE_SUMMARY: $summary"
          fi
          echo "===== FILE: $ref (bytes=0) ====="
          echo "[SKIPPED: referenced output missing]"
        fi
        ;;
    esac
  done < "$index_file"
}

index_tasks_file() {
  local index_file="$BATCH_DIR/index.md"
  [[ -f "$index_file" ]] || return 0
  sed -n "s/^- tasks file: \`\\(.*\\)\`/\\1/p" "$index_file" | head -n 1
}

index_mode() {
  local index_file="$BATCH_DIR/index.md"
  [[ -f "$index_file" ]] || return 0
  sed -n "s/^- mode: \`\\(.*\\)\`/\\1/p" "$index_file" | head -n 1
}

index_task_count() {
  local index_file="$BATCH_DIR/index.md"
  [[ -f "$index_file" ]] || { echo "0"; return 0; }
  grep -c '^## ' "$index_file" || true
}

generated_file_count() {
  if [[ -d "$BATCH_DIR/generated" ]]; then
    find "$BATCH_DIR/generated" -type f | wc -l | tr -d ' '
  else
    echo "0"
  fi
}

cleanup_tmp_files() {
  [[ -n "$MAP_REFS_FILE" && -f "$MAP_REFS_FILE" ]] && rm -f "$MAP_REFS_FILE" || true
  [[ -n "$EMITTED_RELS_FILE" && -f "$EMITTED_RELS_FILE" ]] && rm -f "$EMITTED_RELS_FILE" || true
}

MAP_REFS_FILE="$(mktemp)"
EMITTED_RELS_FILE="$(mktemp)"
trap cleanup_tmp_files EXIT
build_index_reference_map

{
  echo "BATCH_BUNDLE v1"
  echo "batch_dir=$BATCH_DIR"
  echo "generated_at=$(date -Iseconds)"
  echo "tasks_file=$(index_tasks_file)"
  echo "mode=$(index_mode)"
  echo "number_of_tasks=$(index_task_count)"
  echo "number_of_generated_files=$(generated_file_count)"
  echo "max_bytes_per_file=$MAX_BYTES_PER_FILE"
  echo "max_files=$MAX_FILES"
  echo ""

  # 1) index.md first
  if [[ -f "$BATCH_DIR/index.md" ]]; then
    emit_file "$BATCH_DIR/index.md"
  else
    echo ""
    echo "===== FILE: index.md (bytes=0) ====="
    echo "[SKIPPED: missing index.md]"
  fi

  # 2) top-level output files referenced by index.md in order
  emit_index_referenced_outputs

  # 3) generated tree in sorted path order (text files only)
  count=0
  if [[ -d "$BATCH_DIR/generated" ]]; then
    while IFS= read -r -d '' f; do
      emit_file "$f"
      count=$((count+1))
      if (( count >= MAX_FILES )); then
        echo ""
        echo "===== NOTE: reached MAX_FILES=$MAX_FILES, stopping ====="
        break
      fi
    done < <(find "$BATCH_DIR/generated" \
      -type f \
      ! -path "*/__pycache__/*" \
      -print0 | sort -z)
  fi

  echo ""
  echo "END_BUNDLE"
} > "$OUT"

bundle_size="$(wc -c < "$OUT" | tr -d ' ')"
if (( bundle_size > WARN_BUNDLE_BYTES )); then
  echo "WARNING: bundle is large (${bundle_size} bytes)." >&2
  echo "Failure mode: large bundle may be slow to open/copy, but file was written." >&2
fi

echo "Wrote $OUT"
