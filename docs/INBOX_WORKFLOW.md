# Inbox / Drop-Folder Workflow

This repository supports an offline inbox workflow for real exports.

## Required Folder Paths

Drop files into these folders:

- `data/inbox/electra/`
- `data/inbox/hotelrunner/`

The generator can ingest from these folders with:

```bash
python3 scripts/generate_truth_pack.py --out outputs/_truth_pack --use-inbox 1
```

## Accepted File Types

Supported now:

- CSV (`.csv`)

Not supported by inbox ingest right now:

- XLSX (`.xlsx`)
- PDF (`.pdf`)

## Strict Filename Convention

Filenames must match exactly.

Electra:

- `electra_sales_summary_<YYYY-MM-DD>.csv`
- `electra_sales_by_agency_<YYYY-MM-DD>.csv`

HotelRunner:

- `hotelrunner_daily_sales_<YYYY-MM-DD>.csv`

If any file in an inbox folder does not match the naming convention, ingestion refuses it.

## How "Newest" Is Selected

For each `(source, report_type, year)` the system selects one file using:

1. Highest date parsed from filename (`YYYY-MM-DD`)
2. If tied, latest file modification time (`mtime`)

Required reports per year:

- `electra:sales_summary`
- `electra:sales_by_agency`
- `hotelrunner:daily_sales`

If any required report is missing for a requested year, ingestion raises an error.

## Schema Validation

After selection, CSV headers are validated before normalization.

Expected minimum headers:

- Electra `sales_summary`: `date,gross_sales,net_sales,currency`
- Electra `sales_by_agency`: `date,agency_id,agency_name,gross_sales,net_sales,currency`
- HotelRunner `daily_sales`: `date,gross_sales,net_sales,currency` plus one of `booking_id|invoice_id` and one of `channel|agency`

## Safety Guardrails

- Path traversal is blocked: all paths must resolve under repo root.
- Oversized files are rejected (default max: 25 MB per file, configurable).
- Selected files are copied to a deterministic run folder under:
  - `data/raw/inbox_run/<run_id>/...`
- Manifest is written to:
  - `data/raw/inbox_run/<run_id>/manifest.json`

Manifest includes selected filenames, parsed dates, sizes, sha256 hashes, and normalization outputs.

## Examples

Valid:

- `data/inbox/electra/electra_sales_summary_2025-12-31.csv`
- `data/inbox/electra/electra_sales_by_agency_2025-12-31.csv`
- `data/inbox/hotelrunner/hotelrunner_daily_sales_2025-12-31.csv`

Invalid:

- `electra_sales_summary_2025_12_31.csv` (bad date format)
- `sales_summary_2025-12-31.csv` (missing `electra_` prefix)
- `hotelrunner_daily_sales_2025-12-31.xlsx` (unsupported file type)
- `electra_sales_by_agency_2025-13-01.csv` (invalid date)

## Common Errors

- "invalid inbox filename": rename file to match strict convention.
- "missing required inbox report files": provide all required report types for each requested year.
- "header mismatch": export with the expected columns.
- "inbox file too large": provide a smaller export or increase size limit intentionally.
