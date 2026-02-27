# Export Contract (Electra + HotelRunner)

This document defines the ingestion contract for realistic exports used by adapters, validators, and normalizers.

## Supported Reports

Electra:

- `sales_summary`
- `sales_by_agency`

HotelRunner:

- `daily_sales`

## Supported File Types

- Primary: CSV (`.csv`)
- Optional: XLSX/XLSM (`.xlsx`, `.xlsm`) when `openpyxl` is available in the runtime

If XLSX support is not available, ingestion fails with a clear error.

## Naming Convention

Recommended naming for inbox automation:

- `electra_sales_summary_<YYYY-MM-DD>.csv`
- `electra_sales_by_agency_<YYYY-MM-DD>.csv`
- `hotelrunner_daily_sales_<YYYY-MM-DD>.csv`

Equivalent `.xlsx` / `.xlsm` extensions are also accepted by scanner+adapter paths.

## Canonical Schemas

Electra `sales_summary` canonical columns:

- required: `date`, `gross_sales`
- optional: `net_sales` (defaults to `0`), `currency` (defaults to `USD`)

Electra `sales_by_agency` canonical columns:

- required: `date`, `agency_id`, `agency_name`, `gross_sales`
- optional: `net_sales` (defaults to `0`), `currency` (defaults to `USD`)

HotelRunner `daily_sales` canonical columns:

- required: `date`, `booking_id` (or alias equivalent), `gross_sales`
- required dimension: either `channel` (or alias equivalent), or both `agency_id` and `agency_name`
- optional: `net_sales` (defaults to `0`), `currency` (defaults to `USD`)

Unknown extra columns are ignored.

## Alias Mapping

Adapters normalize common header variants into canonical names.

Examples for amount columns:

- `gross`, `gross_sales`, `grossRevenue`, `gross_amount` -> `gross_sales`
- `net`, `net_sales`, `netRevenue`, `net_amount` -> `net_sales`

Examples for date columns:

- `date`, `reportDate`, `transaction_date` -> `date`

Examples for Electra agency columns:

- `agentId`, `agencyid`, `partner_id` -> `agency_id`
- `agency`, `agencyName`, `agent_name` -> `agency_name`

Examples for HotelRunner identity/channel columns:

- `booking_id`, `invoice_id`, `reservationId` -> `booking_id`
- `channel`, `agency`, `source` -> `channel`

## Missing Column Behavior

When required columns cannot be resolved from aliases, ingestion fails fast with a clear `header mismatch` error that includes:

- which canonical field is missing
- accepted alias candidates for that field

This behavior is used consistently by:

- inbox validation (`src/ai_deney/inbox/validate.py`)
- parser/normalizer adapters (`src/ai_deney/adapters/`)
