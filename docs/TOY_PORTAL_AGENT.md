# Toy Portal Agent Guide

This guide covers local toy portal usage, deterministic "Ask Alice" reporting, and Playwright integration automation.

## 1) Run Toy Portal

Seed only:

```bash
bash scripts/run_toy_portal.sh --seed-only
```

Run server (auto-seeds if DB missing):

```bash
bash scripts/run_toy_portal.sh
```

Run with custom deterministic seed profile:

```bash
bash scripts/run_toy_portal.sh --seed --rows 1000 --seed 20260301 --date-start 2025-01-01 --date-end 2025-12-31 --hot-range 2025-06-19:2025-06-25 --hot-occupancy 0.75
```

## 2) Ask Alice CLI (Deterministic, no LLM)

Generate a markdown report:

```bash
python3 scripts/ask_alice.py "march 2025 sales data" --out outputs/_ask/toy_sales_march_2025.md
```

Generate HTML report:

```bash
python3 scripts/ask_alice.py "sales by source channel for March 2025" --format html --out outputs/_ask/toy_sales_march_2025.html
```

Optional DB override:

```bash
python3 scripts/ask_alice.py "sales for March 2025" --db data/toy_portal/toy.db --out outputs/_ask/march_sales.md
```

Parser mode details (deterministic vs llm stub):

```bash
cat docs/TOY_AGENT_MODE.md
```

## 3) Run Integration Tests

Integration tests are marked and may skip if optional dependencies are missing:

```bash
pytest -m integration -q
```

Only toy portal Playwright integration:

```bash
pytest -q tests/test_toy_portal_playwright_integration.py
```

## 4) Optional Dependency Install

Base portal deps:

```bash
python3 -m pip install fastapi uvicorn python-multipart
```

Playwright deps for E2E lane:

```bash
python3 -m pip install playwright
python3 -m playwright install chromium
```

If Playwright or browser binaries are missing, integration tests skip instead of failing.
