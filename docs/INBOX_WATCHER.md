# Inbox Watcher (launchd)

The inbox watcher runs the inbox truth pack on a launchd schedule using partial inbox policy and snapshots each run into a dated folder.

## Install

```bash
bash scripts/install_inbox_watcher_launchd.sh
```

This installs `config/com.ai_deney.inbox_watcher.plist` to `~/Library/LaunchAgents/com.ai_deney.inbox_watcher.plist` and loads it.

## Uninstall

```bash
bash scripts/uninstall_inbox_watcher_launchd.sh
```

This unloads the LaunchAgent and removes the installed plist from `~/Library/LaunchAgents`.

## Change interval

1. Edit `StartInterval` in `config/com.ai_deney.inbox_watcher.plist`.
2. Reinstall to apply changes:

```bash
bash scripts/install_inbox_watcher_launchd.sh
```

Default is `3600` seconds (hourly).

## View logs

Launchd stdout/stderr logs:

- `outputs/_watcher_logs/inbox_watcher.out.log`
- `outputs/_watcher_logs/inbox_watcher.err.log`

Latest lines:

```bash
tail -n 100 outputs/_watcher_logs/inbox_watcher.out.log
tail -n 100 outputs/_watcher_logs/inbox_watcher.err.log
```

Per-run watcher command output is also saved as:

- `outputs/inbox_runs/YYYY-MM-DD_HHMM*/truth_pack_stdout.log`

## Run once manually

```bash
bash scripts/inbox_watch_once.sh
```

The script prints a final grep-friendly line:

- `WATCHER_RUN_DIR=/Users/omer/ai-deney/week1/outputs/inbox_runs/YYYY-MM-DD_HHMM...`

## Safety notes

- Script is pinned to repo root: `/Users/omer/ai-deney/week1`.
- Script activates repo venv: `.venv/bin/activate`.
- Script runs `bash scripts/dev_check.sh` before generating outputs.
- Script always runs partial inbox policy:
  - `bash scripts/run_inbox_truth_pack.sh --inbox-policy partial`
- Dated output snapshots are written only under repo:
  - `outputs/inbox_runs/YYYY-MM-DD_HHMM*/`
- If inbox ingest writes a manifest, watcher copies it as:
  - `outputs/inbox_runs/YYYY-MM-DD_HHMM*/manifest.json`
