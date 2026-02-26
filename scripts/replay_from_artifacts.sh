#!/usr/bin/env bash
set -euo pipefail

ART_DIR="${1:-}"
TASK_FILE_INPUT="${2:-}"
if [[ -z "$ART_DIR" ]]; then
  echo "Usage: scripts/replay_from_artifacts.sh <artifact_dir> [taskfile]" >&2
  exit 2
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -d "$ART_DIR" ]]; then
  echo "artifact_dir not found: $ART_DIR" >&2
  exit 2
fi

TRANSCRIPT="$(python3 - "$ART_DIR" <<'PY'
import sys
from pathlib import Path

root = Path(sys.argv[1])
cands = [p for p in root.rglob("transcript.jsonl") if p.is_file()]
if not cands:
    print("")
    raise SystemExit(0)
cands.sort(key=lambda p: (p.stat().st_mtime, str(p)))
print(str(cands[-1]))
PY
)"

if [[ -z "$TRANSCRIPT" ]]; then
  echo "No transcript.jsonl found under: $ART_DIR" >&2
  echo "Action: download/extract CI artifact and ensure transcript.jsonl is present." >&2
  exit 1
fi

TASK_FILE="$TASK_FILE_INPUT"
if [[ -z "$TASK_FILE" ]]; then
  TASK_FILE="$(python3 - "$ART_DIR" <<'PY'
import sys
from pathlib import Path

root = Path(sys.argv[1])
candidates = sorted(
    [p for p in root.rglob("*.md") if "_tmp_tasks" in p.as_posix()],
    key=lambda p: (p.stat().st_mtime, str(p)),
)
if candidates:
    print(str(candidates[-1]))
    raise SystemExit(0)
repo_fallback = sorted((Path("tests") / "eval_pack" / "tasks").glob("*.md"))
print(str(repo_fallback[0]) if repo_fallback else "")
PY
)"
fi

if [[ -z "$TASK_FILE" ]]; then
  echo "No taskfile provided and no candidate task files found." >&2
  echo "Action: pass an explicit taskfile path as second argument." >&2
  exit 1
fi
if [[ ! -f "$TASK_FILE" ]]; then
  echo "taskfile not found: $TASK_FILE" >&2
  exit 2
fi

TASK_FILE_ABS="$(python3 - "$TASK_FILE" <<'PY'
import os, sys
print(os.path.realpath(sys.argv[1]))
PY
)"
ROOT_ABS="$(python3 - "$ROOT" <<'PY'
import os, sys
print(os.path.realpath(sys.argv[1]))
PY
)"

TASK_FILE_USE="$TASK_FILE_ABS"
case "$TASK_FILE_ABS" in
  "$ROOT_ABS"/*) ;;
  *)
    AUTO_TASK_DIR="$ROOT/tests/_tmp_tasks/replay_from_artifacts_auto"
    mkdir -p "$AUTO_TASK_DIR"
    TASK_FILE_USE="$AUTO_TASK_DIR/$(basename "$TASK_FILE_ABS")"
    cp "$TASK_FILE_ABS" "$TASK_FILE_USE"
    ;;
esac

OUTDIR="$ART_DIR/replay_out"
REPAIR_RETRIES="${REPLAY_REPAIR_RETRIES:-2}"
set +e
python3 batch_agent.py --chat --tasks-format blocks --repair-retries "$REPAIR_RETRIES" --replay-transcript "$TRANSCRIPT" --outdir "$OUTDIR" "$TASK_FILE_USE"
RC=$?
set -e

echo "transcript_path=$TRANSCRIPT"
echo "taskfile_path=$TASK_FILE_USE"
echo "repair_retries=$REPAIR_RETRIES"
echo "outdir=$OUTDIR"
echo "exit_code=$RC"
exit "$RC"
