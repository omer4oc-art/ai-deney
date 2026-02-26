#!/usr/bin/env bash
set -euo pipefail

TAG=""
SOAK_MINUTES="0"
DRY_RUN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --tag)
      TAG="${2:-}"
      shift 2
      ;;
    --soak-minutes)
      SOAK_MINUTES="${2:-0}"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    *)
      echo "Unknown arg: $1" >&2
      echo "Usage: bash scripts/release.sh --tag vX.Y.Z [--soak-minutes N] [--dry-run]" >&2
      exit 2
      ;;
  esac
done

if [[ -z "$TAG" ]]; then
  echo "Missing required --tag vX.Y.Z" >&2
  exit 2
fi
if [[ "$TAG" != v* ]]; then
  echo "Tag must start with 'v' (got: $TAG)" >&2
  exit 2
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -n "$(git status --porcelain)" ]]; then
  echo "Working tree is dirty. Commit/stash changes before release." >&2
  exit 1
fi

CHECK_CMD="${RELEASE_CHECK_CMD:-bash scripts/check.sh}"
EVAL_CMD="${RELEASE_EVAL_CMD:-bash scripts/run_eval_pack.sh}"
SOAK_CMD="${RELEASE_SOAK_CMD:-bash scripts/soak_eval_pack.sh --minutes $SOAK_MINUTES --no-stop-on-fail --max-runs-kept 50}"

echo "step=check cmd=$CHECK_CMD"
bash -lc "$CHECK_CMD"
echo "step=eval_pack cmd=$EVAL_CMD"
bash -lc "$EVAL_CMD"
if [[ "${SOAK_MINUTES}" != "0" ]]; then
  echo "step=soak cmd=$SOAK_CMD"
  bash -lc "$SOAK_CMD"
fi

if [[ "$DRY_RUN" == "1" ]]; then
  echo "dry_run=1"
  echo "would_update_version=${TAG#v}"
  echo "would_create_tag=$TAG"
  exit 0
fi

VERSION_VALUE="${TAG#v}"
printf '%s\n' "$VERSION_VALUE" > VERSION

DATE_STR="$(date +%Y-%m-%d)"
HEAD_HASH="$(git rev-parse --short HEAD)"
COMMITS="$(git log -n 10 --pretty='- %s (%h)' || true)"
if [[ -z "$COMMITS" ]]; then
  COMMITS="- Automated release"
fi

CHANGELOG_TMP="$(mktemp)"
{
  echo "## $TAG - $DATE_STR"
  echo
  echo "- commit: $HEAD_HASH"
  echo "$COMMITS"
  echo
  if [[ -f CHANGELOG.md ]]; then
    cat CHANGELOG.md
  fi
} > "$CHANGELOG_TMP"
mv "$CHANGELOG_TMP" CHANGELOG.md

git tag "$TAG"
echo "release_tag_created=$TAG"
