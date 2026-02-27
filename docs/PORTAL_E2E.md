# Portal E2E: Download -> Inbox -> Truth Pack

This flow runs a full local loop:

1. Start/reuse the Electra Test Portal
2. Download Electra exports through Playwright
3. Copy them into inbox naming convention
4. Run inbox-based truth-pack generation
5. Copy outputs and logs into a dated run directory

## Dependencies

Install in your `.venv`:

```bash
python3 -m pip install fastapi uvicorn python-multipart playwright
python3 -m playwright install chromium
```

## Run

Default run:

```bash
bash scripts/portal_to_inbox_truth_pack.sh
```

Useful options:

```bash
bash scripts/portal_to_inbox_truth_pack.sh \
  --variant messy \
  --include-2026 \
  --keep-portal
```

## What It Writes

Inbox files:

- `data/inbox/electra/electra_sales_summary_2025-06-25.csv`
- `data/inbox/electra/electra_sales_by_agency_2025-06-25.csv`
- `data/inbox/hotelrunner/hotelrunner_daily_sales_2025-06-25.csv` (bootstrapped if missing)

Run artifacts:

- `outputs/inbox_runs/YYYY-MM-DD_HHMM_portal/`
- `outputs/inbox_runs/YYYY-MM-DD_HHMM_portal/index.md`
- `outputs/inbox_runs/YYYY-MM-DD_HHMM_portal/bundle.txt`
- `outputs/inbox_runs/YYYY-MM-DD_HHMM_portal/manifest.json` (if inbox ingest produced one)
- `outputs/inbox_runs/YYYY-MM-DD_HHMM_portal/portal_stdout.log`
- `outputs/inbox_runs/YYYY-MM-DD_HHMM_portal/truth_pack_stdout.log`

The command prints:

```text
PORTAL_TO_INBOX_RUN_DIR=...
```

Use that path to inspect logs, manifest, and copied truth-pack reports.
