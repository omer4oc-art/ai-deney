# CI Debugging Quick Guide

## Find Artifacts
- Open GitHub Actions.
- Open the failed run.
- Download artifact: `ci-debug-artifacts`.
- For nightly runs, open the `Nightly` workflow run and download:
  - `nightly-report` (stub soak summary + logs)
  - `nightly-real-report` (real lane index/bundle/transcript/gate report)

## High-Value Files
- `index.md`: per-task status and errors.
- `bundle.txt`: compact bundled context for a batch.
- `gate_report.json`: per-task/attempt gate counts.
- `transcript.jsonl`: recorded model call sequence.
- `runs/iter-XXXX/pytest.log`: soak/eval iteration logs.

## Replay Locally
1. Download and unzip artifacts.
2. From repo root, run:

```bash
bash scripts/replay_from_artifacts.sh <artifact_dir> <taskfile>
```

Or let the helper auto-pick a task file:

```bash
bash scripts/replay_from_artifacts.sh <artifact_dir>
```

The script prints:
- transcript path used
- taskfile used
- replay output directory

## Replay Mismatch Debugging
- A strict replay mismatch reports:
  - `expected_hash=...`
  - `got_hash=...`
  - short expected prompt preview
  - short current prompt preview
- Expected prompt text is under transcript fixture path:
  - `<artifact_dir>/.../transcript/prompts/<hash>.txt`
- Compare with your current task prompt and retry.

## Local Dev Workflow
Run deterministic offline checks from repo root with the project virtual environment active.

```bash
cd /Users/omer/ai-deney/week1
source .venv/bin/activate
bash scripts/dev_check.sh
bash scripts/dev_run_all.sh
```

## Daily One-Command Workflow
Use this to run the full local check pack in one command.

```bash
cd /Users/omer/ai-deney/week1
source .venv/bin/activate
bash scripts/dev_run_all.sh
```

`scripts/dev_check.sh` fails fast on wrong directory or wrong venv and prints the recovery command.

`scripts/dev_run_all.sh` executes:
- `scripts/dev_check.sh`
- `pytest -q`
- `bash scripts/run_eval_pack.sh`
- `python3 scripts/generate_truth_pack.py --out outputs/_truth_pack`

Truth pack index:
- `outputs/_truth_pack/index.md`
