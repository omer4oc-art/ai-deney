# Toy Agent Mode

Stage B introduces an intent parser with two modes for toy portal questions.

## Deterministic vs LLM Parser

`AI_DENEY_TOY_INTENT_MODE=deterministic` (default)
- Uses local regex/rule parsing.
- Converts question text into strict `QuerySpec` JSON.
- No LLM/router call is made.

`AI_DENEY_TOY_INTENT_MODE=llm`
- Calls a local router stub that returns raw JSON `QuerySpec`.
- Raw JSON is always validated by the same deterministic validator.
- Any schema/type/date mismatch is rejected with `ValueError`.

## QuerySpec Schema

`QuerySpec` fields:
- `report_type`: one of `sales_range`, `sales_month`, `sales_by_channel`, `occupancy_range`, `reservations_list`, `export_reservations`
- `start_date`: optional `YYYY-MM-DD`
- `end_date`: optional `YYYY-MM-DD`
- `year`: optional integer (`2000..2100`)
- `month`: optional integer (`1..12`)
- `group_by`: optional `day` or `channel`
- `redact_pii`: boolean, default `true`
- `format`: `md` or `html`, default `md`

Validation guarantees:
- Invalid dates are rejected.
- `start_date <= end_date` is required when both are provided.
- Ranges are filled deterministically from `year/month` when needed.
- `March 2025` resolves to `2025-03-01..2025-03-31`.
- Ambiguous range requests raise a clear error.

## Enabling LLM Mode

The toy LLM mode is stub-only and local. Configure one of:

```bash
export AI_DENEY_TOY_INTENT_MODE=llm
export AI_DENEY_TOY_LLM_STUB_JSON='{"report_type":"sales_by_channel","year":2025,"month":3,"group_by":"channel","redact_pii":true,"format":"md"}'
```

or:

```bash
export AI_DENEY_TOY_INTENT_MODE=llm
export AI_DENEY_TOY_LLM_STUB_FILE=outputs/_ask/stub_query_spec.json
```

## UI Ask Panel

The dashboard has an **Ask Alice** panel above the reservations table.

Usage:
- Open the portal dashboard (`/`).
- Enter a question (for example: `Sales by channel for March 2025`).
- Choose `md` or `html`.
- Keep **Redact** on by default unless you need raw names.
- Click **Ask** to call `POST /api/ask`.
- Click **Download** to save the returned output as `.md` or `.html`.

API payload from the panel:

```json
{
  "question": "Sales by channel for March 2025",
  "format": "md",
  "redact_pii": true
}
```

The API returns deterministic report output with:
- `spec` (validated QuerySpec)
- `meta` (execution metadata)
- `output` (rendered markdown/html string)
- `content_type` (`text/markdown` or `text/html`)

## Call `/api/ask` Directly

Example curl request:

```bash
curl -fsS -X POST http://127.0.0.1:8011/api/ask \
  -H 'content-type: application/json' \
  -d '{"question":"Sales by channel for March 2025","format":"md","redact_pii":true}'
```

Example response shape:

```json
{
  "ok": true,
  "spec": {},
  "meta": {},
  "output": "...",
  "content_type": "text/markdown"
}
```

## Safety Guarantees

- The LLM/router chooses only the query structure (`QuerySpec`).
- All totals, counts, occupancy, and table rows come only from deterministic SQLite queries.
- LLM output never computes numeric answers.
- Invalid LLM JSON/spec is rejected before any report execution.
