#!/usr/bin/env bash
set -euo pipefail

TAG="${1:-}"
if [[ -z "$TAG" ]]; then
  echo "Usage: bash scripts/release_notes.sh vX.Y.Z" >&2
  exit 2
fi

ROOT="${AI_DENEY_REPO_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "$ROOT"

if [[ -f CHANGELOG.md ]]; then
  SECTION="$(awk -v tag="$TAG" '
    BEGIN { cap=0; start=0 }
    $0 ~ "^##[[:space:]]+" tag "([[:space:]]+-.*)?$" { cap=1; start=NR }
    cap && NR > start && $0 ~ "^##[[:space:]]+" { exit }
    cap { print }
  ' CHANGELOG.md)"
  if [[ -n "${SECTION}" ]]; then
    printf '%s\n' "$SECTION"
    exit 0
  fi
fi

if ! git rev-parse --git-dir >/dev/null 2>&1; then
  echo "- Automated release"
  exit 0
fi

RANGE=""
if git rev-parse -q --verify "refs/tags/$TAG" >/dev/null 2>&1; then
  PREV_TAG="$(git describe --tags --abbrev=0 "${TAG}^" 2>/dev/null || true)"
  if [[ -n "$PREV_TAG" ]]; then
    RANGE="${PREV_TAG}..${TAG}"
  else
    RANGE="${TAG}"
  fi
else
  PREV_TAG="$(git describe --tags --abbrev=0 2>/dev/null || true)"
  if [[ -n "$PREV_TAG" ]]; then
    RANGE="${PREV_TAG}..HEAD"
  fi
fi

if [[ -n "$RANGE" ]]; then
  NOTES="$(git log --pretty='- %s (%h)' $RANGE | head -n 20 || true)"
else
  NOTES="$(git log -n 20 --pretty='- %s (%h)' || true)"
fi

if [[ -z "$NOTES" ]]; then
  echo "- Automated release"
else
  printf '%s\n' "$NOTES"
fi
