#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="/Users/omer/ai-deney/week1"
PLIST_NAME="com.ai_deney.inbox_watcher.plist"
SRC_PLIST="$REPO_ROOT/config/$PLIST_NAME"
TARGET_DIR="$HOME/Library/LaunchAgents"
TARGET_PLIST="$TARGET_DIR/$PLIST_NAME"
LOG_DIR="$REPO_ROOT/outputs/_watcher_logs"
RUNS_DIR="$REPO_ROOT/outputs/inbox_runs"

mkdir -p "$TARGET_DIR" "$LOG_DIR" "$RUNS_DIR"

if [[ ! -f "$SRC_PLIST" ]]; then
  echo "install: missing plist template at $SRC_PLIST" >&2
  exit 1
fi

cp "$SRC_PLIST" "$TARGET_PLIST"

launchctl unload "$TARGET_PLIST" >/dev/null 2>&1 || true
launchctl load "$TARGET_PLIST"

echo "launchd_installed=$TARGET_PLIST"
echo "check_status=launchctl list | grep com.ai_deney.inbox_watcher"
echo "manual_run=launchctl start com.ai_deney.inbox_watcher"
echo "stdout_log=$LOG_DIR/inbox_watcher.out.log"
echo "stderr_log=$LOG_DIR/inbox_watcher.err.log"
