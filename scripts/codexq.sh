#!/usr/bin/env bash
set -euo pipefail

cd /Users/omer/ai-deney/week1

# shellcheck disable=SC1091
source .venv/bin/activate

echo "[codexq] Launching Codex (exit Codex to run QC)..."
codex -s workspace-write -a never

echo
echo "[codexq] Running QC: dev_run_all + git status + diffstat"
bash scripts/dev_run_all.sh

echo
git status
echo
git diff --stat || true
