#!/usr/bin/env bash
set -euo pipefail

PORT="${VIEWER_PORT:-8010}"
URL="${1:-http://127.0.0.1:${PORT}/}"

if command -v open >/dev/null 2>&1; then
  open "$URL"
else
  echo "open command not available. Visit: $URL"
fi
