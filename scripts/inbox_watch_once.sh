#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="/Users/omer/ai-deney/week1"
TRUTH_PACK_DIR="$REPO_ROOT/outputs/_truth_pack"
RUNS_ROOT="$REPO_ROOT/outputs/inbox_runs"
WATCHER_LOG_ROOT="$REPO_ROOT/outputs/_watcher_logs"

require_within_repo() {
  local path="$1"
  case "$path" in
    "$REPO_ROOT"|"$REPO_ROOT"/*) ;;
    *)
      echo "watcher: path escapes repo: $path" >&2
      exit 1
      ;;
  esac
}

resolve_abs_path() {
  local input="$1"
  local target="$1"
  if [[ "$input" != /* ]]; then
    target="$REPO_ROOT/$input"
  fi
  local parent
  parent="$(cd "$(dirname "$target")" && pwd -P)"
  printf '%s/%s\n' "$parent" "$(basename "$target")"
}

cd "$REPO_ROOT"
mkdir -p "$RUNS_ROOT" "$WATCHER_LOG_ROOT"

if [[ ! -f "$REPO_ROOT/.venv/bin/activate" ]]; then
  echo "watcher: missing virtualenv activate script at $REPO_ROOT/.venv/bin/activate" >&2
  exit 1
fi

# shellcheck disable=SC1091
source "$REPO_ROOT/.venv/bin/activate"

bash scripts/dev_check.sh

run_stamp="$(date +%Y-%m-%d_%H%M)"
run_dir="$RUNS_ROOT/$run_stamp"
if [[ -e "$run_dir" ]]; then
  suffix=1
  while [[ -e "${run_dir}_$suffix" ]]; do
    suffix="$((suffix + 1))"
  done
  run_dir="${run_dir}_$suffix"
fi
require_within_repo "$run_dir"
mkdir -p "$run_dir"

truth_log="$run_dir/truth_pack_stdout.log"
require_within_repo "$truth_log"

bash scripts/run_inbox_truth_pack.sh --inbox-policy partial 2>&1 | tee "$truth_log"

truth_pack_index="$(sed -n 's/^truth_pack_index=//p' "$truth_log" | tail -n 1)"
if [[ -z "$truth_pack_index" ]]; then
  truth_pack_index="$TRUTH_PACK_DIR/index.md"
fi
truth_pack_index="$(resolve_abs_path "$truth_pack_index")"
require_within_repo "$truth_pack_index"

if [[ ! -f "$truth_pack_index" ]]; then
  echo "watcher: missing truth pack index at $truth_pack_index" >&2
  exit 1
fi

truth_pack_dir="$(cd "$(dirname "$truth_pack_index")" && pwd -P)"
require_within_repo "$truth_pack_dir"

bundle_path="$truth_pack_dir/bundle.txt"
if [[ ! -f "$bundle_path" ]]; then
  echo "watcher: missing bundle at $bundle_path" >&2
  exit 1
fi

cp "$truth_pack_index" "$run_dir/index.md"
cp "$bundle_path" "$run_dir/bundle.txt"

while IFS= read -r rel_path; do
  [[ -n "$rel_path" ]] || continue
  src_path="$truth_pack_dir/$rel_path"
  src_path="$(resolve_abs_path "$src_path")"
  require_within_repo "$src_path"
  if [[ -f "$src_path" ]]; then
    dst_path="$run_dir/$rel_path"
    require_within_repo "$dst_path"
    mkdir -p "$(dirname "$dst_path")"
    cp "$src_path" "$dst_path"
  fi
done < <(sed -nE 's/^- (md|html): \[[^]]+\]\(([^)]+)\)$/\2/p' "$truth_pack_index" | sed '/^$/d' | sort -u)

manifest_path="$(sed -n 's/^INBOX: manifest=//p' "$truth_log" | tail -n 1)"
if [[ -n "$manifest_path" ]]; then
  manifest_path="$(resolve_abs_path "$manifest_path")"
  require_within_repo "$manifest_path"
  if [[ -f "$manifest_path" ]]; then
    cp "$manifest_path" "$run_dir/manifest.json"
  fi
fi

echo "WATCHER_RUN_DIR=$run_dir"
