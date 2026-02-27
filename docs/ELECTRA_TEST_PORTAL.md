# Electra Test Portal + Playwright Connector

This repo includes a tiny local portal and optional Playwright connector to exercise real download automation patterns without external network dependency.

## Portal scope

Implemented endpoints:

- `GET /health`
- `GET /login`
- `POST /login`
- `GET /reports` (session required)
- `POST /reports/download` (session required)

Portal supports only:

- `sales_summary`
- `sales_by_agency`

## Run portal

```bash
bash scripts/run_electra_test_portal.sh
```

Default URL: `http://127.0.0.1:8008`

## Connector mode switch

Default connector mode remains mock fixtures.

- `AI_DENEY_ELECTRA_CONNECTOR=mock` (default)
- `AI_DENEY_ELECTRA_CONNECTOR=portal_playwright` (opt-in)

Optional environment variables for portal mode:

- `AI_DENEY_ELECTRA_PORTAL_URL` (default `http://127.0.0.1:8008`)
- `AI_DENEY_ELECTRA_PORTAL_USERNAME` (default `demo`)
- `AI_DENEY_ELECTRA_PORTAL_PASSWORD` (default `demo123`)
- `AI_DENEY_ELECTRA_PORTAL_TIMEOUT_MS` (default `15000`)
- `AI_DENEY_ELECTRA_PORTAL_MAX_RETRIES` (default `2`)
- `AI_DENEY_ELECTRA_EXPORT_VARIANT` (`canonical` or `messy`, default `canonical`)

## Output paths

Downloaded portal exports are saved under:

- `data/raw/electra_portal/<run_id>/<report_type>/<year>/...`

Failure screenshots are saved under:

- `outputs/_watcher_logs/`

## Dependency notes

Portal and connector are optional and skip-safe in test runs.

Required for full portal automation flow:

- `fastapi`
- `uvicorn`
- `playwright`
- Chromium browser for Playwright (`playwright install chromium`)
