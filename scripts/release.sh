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
if ! [[ "$TAG" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "Invalid tag format: $TAG (expected vX.Y.Z)" >&2
  exit 2
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -n "$(git status --porcelain)" ]]; then
  echo "Working tree is dirty. Commit/stash changes before release." >&2
  exit 1
fi

if git rev-parse -q --verify "refs/tags/$TAG" >/dev/null; then
  if [[ "$DRY_RUN" == "1" ]]; then
    echo "warning: tag already exists ($TAG); dry-run exits without changes"
    exit 0
  fi
  echo "Tag already exists: $TAG" >&2
  exit 1
fi

if [[ -f CHANGELOG.md ]] && grep -Fq "## $TAG - " CHANGELOG.md; then
  if [[ "$DRY_RUN" == "1" ]]; then
    echo "warning: changelog already has entry for $TAG; dry-run exits without changes"
    exit 0
  fi
  echo "CHANGELOG.md already contains heading for $TAG" >&2
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
  set +e
  SOAK_OUT="$(bash -lc "$SOAK_CMD" 2>&1)"
  SOAK_RC=$?
  set -e
  printf '%s\n' "$SOAK_OUT"
  if [[ "$SOAK_RC" -ne 0 ]]; then
    echo "Soak command failed with exit code $SOAK_RC" >&2
    exit "$SOAK_RC"
  fi
  SOAK_FAILS="$(printf '%s\n' "$SOAK_OUT" | sed -n 's/.*failures=\([0-9][0-9]*\).*/\1/p' | tail -n1)"
  if [[ -n "$SOAK_FAILS" && "$SOAK_FAILS" != "0" ]]; then
    echo "Soak detected failures=$SOAK_FAILS; failing release." >&2
    exit 1
  fi
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
LAST_TAG="$(git describe --tags --abbrev=0 2>/dev/null || true)"
if [[ -n "$LAST_TAG" ]]; then
  COMMITS="$(git log "${LAST_TAG}..HEAD" --pretty='- %s (%h)' | head -n 20 || true)"
else
  COMMITS="$(git log -n 20 --pretty='- %s (%h)' || true)"
fi
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
