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
- `report_type`: one of `sales_range`, `sales_month`, `sales_by_channel`, `sales_for_dates`, `occupancy_range`, `reservations_list`, `export_reservations`
- `start_date`: optional `YYYY-MM-DD`
- `end_date`: optional `YYYY-MM-DD`
- `year`: optional integer (`2000..2100`)
- `month`: optional integer (`1..12`)
- `group_by`: optional `day` or `channel`
- `dates`: optional list of `YYYY-MM-DD` for `sales_for_dates`
- `compare`: boolean, optional (`true` enables delta/range comparisons)
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
- Click **Save Run** to call `POST /api/ask/save` and persist an audit trail folder under `outputs/_ask_runs/`.
- Click **Download** to save the returned output as `.md` or `.html`.
- Use **Recent Ask Runs** to open saved `index.md` files or compare a saved run with the current output.

### Debug Trace (Developer Only)

Enable trace output with either:
- URL query: open dashboard with `?debug=1` (for example `http://127.0.0.1:8011/?debug=1`)
- Environment variable: `AI_DENEY_TOY_DEBUG_TRACE=1`

When enabled, `/api/ask` includes a `trace` object for deterministic debugging of:
- intent mode and normalized parse input
- logical query steps and row counts
- warnings surfaced by parsing/execution

`trace` intentionally excludes PII fields such as `guest_name` and other row-level guest-name values.
Timing fields are omitted by default to preserve deterministic trace output across repeated runs.

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

## Ask Runs Audit Trail

Each saved Ask run is persisted to:

`outputs/_ask_runs/<run_id>/`

where:
- `run_id` format: `YYYY-MM-DD_HHMMSS_<shortslug>_<hash8>`
- `<shortslug>` is derived from the question
- `<hash8>` is stable for identical request payloads (`question`, `format`, `redact_pii`, `debug`)

Saved files:
- `request.json` (question/format/redact_pii/debug)
- `response.json` (`ok/spec/meta/content_type` + `trace` only when debug is enabled)
- `output.md` or `output.html` (rendered output)
- `index.md` (human-readable summary + links)

### UI Save + Browse

- Save a run: `POST /api/ask/save`
- List latest runs: `GET /api/ask/runs?limit=20`
- Open run page: `GET /ask-run/{run_id}`
- Open raw run file: `GET /ask-run/{run_id}/index.md` (or `request.json`, `response.json`, `output.md|output.html`)

### Compare Runs

Use:

`GET /api/ask/compare?run_a=<id>&run_b=<id>&format=md|html`

Returns deterministic unified diff text (`diff`) and redacts `guest_name`-like fields when either run has `redact_pii=true`.

### CLI Save Runs

`scripts/ask_alice.py` supports:

```bash
python3 scripts/ask_alice.py "sales by channel for March 2025" \
  --db data/toy_portal/toy.db \
  --out outputs/_ask/march_channel.md \
  --save-run 1
```

This writes normal `--out` output and also persists the same ask-run folder format under `outputs/_ask_runs`.

### Determinism + Redaction Guarantees

- Run hash suffix (`hash8`) is deterministic for the same request payload.
- Compare diffs are deterministic for the same pair/order of runs.
- Trace is only persisted when debug is enabled.
- Trace is sanitized to exclude `guest_name` and row-level raw payload keys.
- All ask-run paths are constrained under repo root.

## E2E UI Lane (Playwright)

Run the full toy Ask Alice E2E rehearsal lane:

```bash
bash scripts/run_toy_e2e.sh
```

What it does:
- Seeds deterministic toy data (`rows=3000`, `seed=42`, fixed date range, fixed hot-range params).
- Runs integration tests (`pytest -q -m integration`) including Ask panel UI automation.
- Writes failure screenshots for Ask E2E into `outputs/_e2e/`.

What it proves:
- UI wiring: Ask input/select/toggle/submit path works end-to-end.
- Deterministic data: seeded totals for `2025-03-01` and `2025-06-03` are stable.
- PII safety: Ask output remains aggregate-only and excludes guest names.
- Multi-span parsing: one Ask request resolves two spans and returns compare output.

Install dependencies (once per environment):

```bash
python3 -m pip install playwright
python3 -m playwright install chromium
```

Notes:
- Integration tests are opt-in (`pytest -q` excludes `@pytest.mark.integration` by default).
- If Playwright package or Chromium runtime is missing, integration tests skip with a clear reason.

New deterministic multi-date sales examples:
- `total sales on March 1 and June 3 2025`
- `compare March 1 vs June 3`
- `sales on 2025-03-01 and 2025-06-03`

If month/day is provided without year (for example `March 1 and June 3`), the parser defaults year to `2025` and returns a warning in `meta.warnings`.

## Call `/api/ask` Directly

Example curl request:

```bash
curl -fsS -X POST 'http://127.0.0.1:8011/api/ask?debug=1' \
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
  "content_type": "text/markdown",
  "trace": {
    "intent_mode": "deterministic",
    "parse": {
      "raw_question": "Sales by channel for March 2025",
      "normalized_question": "sales by channel for march 2025",
      "llm_stub_used": false
    },
    "queries": [
      {
        "name": "sales_grouped_by_channel",
        "params": {
          "end_date": "2025-03-31",
          "group_by": "channel",
          "start_date": "2025-03-01"
        },
        "row_count": 3
      }
    ],
    "timing": {},
    "warnings": []
  }
}
```

## Safety Guarantees

- The LLM/router chooses only the query structure (`QuerySpec`).
- All totals, counts, occupancy, and table rows come only from deterministic SQLite queries.
- LLM output never computes numeric answers.
- Invalid LLM JSON/spec is rejected before any report execution.
