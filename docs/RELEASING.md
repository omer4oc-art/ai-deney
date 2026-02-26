# Releasing

## Local Dry Run
From repo root:

```bash
bash scripts/release.sh --tag v0.0.1 --dry-run
```

This runs `check.sh` and `run_eval_pack.sh`, validates tag format, and prints planned release actions without creating tags or changing files.

## Local Release
Use a clean working tree first, then:

```bash
bash scripts/release.sh --tag vX.Y.Z
```

Release script actions:
- runs `scripts/check.sh`
- runs `scripts/run_eval_pack.sh`
- updates `VERSION` to `X.Y.Z`
- prepends `CHANGELOG.md` entry `## vX.Y.Z - YYYY-MM-DD`
- creates local git tag `vX.Y.Z`

## Release With Soak

```bash
bash scripts/release.sh --tag vX.Y.Z --soak-minutes 30
```

This additionally runs:
- `scripts/soak_eval_pack.sh --minutes 30 --max-runs-kept 50 --no-stop-on-fail`

If soak reports any failures, release exits nonzero.

## Push After Local Release
Release script does not push.
Push manually when ready:

```bash
git push
git push origin vX.Y.Z
```
