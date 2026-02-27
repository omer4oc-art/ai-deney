#!/usr/bin/env bash
set -euo pipefail

bash scripts/dev_check.sh
pytest -q
bash scripts/run_eval_pack.sh
python3 scripts/generate_truth_pack.py --out outputs/_truth_pack

echo "truth_pack_index=$(pwd -P)/outputs/_truth_pack/index.md"
