#!/usr/bin/env bash
set -euo pipefail

PLIST_NAME="com.ai_deney.inbox_watcher.plist"
TARGET_PLIST="$HOME/Library/LaunchAgents/$PLIST_NAME"

launchctl unload "$TARGET_PLIST" >/dev/null 2>&1 || true
rm -f "$TARGET_PLIST"

echo "launchd_removed=$TARGET_PLIST"
