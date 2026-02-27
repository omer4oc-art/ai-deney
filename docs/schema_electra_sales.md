# Electra Sales Normalized Schema

Normalized files are written as yearly CSV files:

- `data/normalized/electra_sales_2025.csv`
- `data/normalized/electra_sales_2026.csv`

Each row uses the stable schema below.

## Fields

- `date` (`YYYY-MM-DD`): business date of the record.
- `year` (`int`): derived from `date`.
- `agency_id` (`string`):
  - channel IDs like `AG001`, `AG002`, ...
  - `DIRECT` for direct channel
  - `TOTAL` for overall summary rows.
- `agency_name` (`string`):
  - descriptive agency name
  - `Direct Channel` for `DIRECT`
  - `Overall Total` for `TOTAL`.
- `gross_sales` (`float`): non-negative gross sales amount.
- `net_sales` (`float`): net amount after adjustments; may include refund/cancellation effects.
- `currency` (`string`): currently `USD`.

## Invariants

- Required columns must exist in every normalized row.
- `gross_sales >= 0` for all rows.
- Requested year files must exist before analytics execute.
- Cross-check rule (conditional):
  - For a given year, if both of the following are present:
    - at least one `TOTAL` row
    - at least one non-`TOTAL` row
  - then `sum(non-TOTAL gross_sales) == sum(TOTAL gross_sales)` within a tiny tolerance.
  - If a year has only one side (summary-only or agency-only), the cross-check is skipped.

## Notes on TOTAL rows

- `TOTAL` rows represent daily overall totals.
- They come from `sales_summary_<year>.csv`.
- Agency rows come from `sales_by_agency_<year>.csv`.
- During normalization, both sources can be merged into the same yearly file.
