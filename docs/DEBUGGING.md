# CI Debugging Quick Guide

## Find Artifacts
- Open GitHub Actions.
- Open the failed run.
- Download artifact: `ci-debug-artifacts`.

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
