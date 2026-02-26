#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

echo "[1/3] py_compile core entrypoints"
python -m py_compile batch_agent.py agent.py agent_json.py memory_agent.py memory.py file_tools.py run_logger.py ollama_client.py

echo "[2/3] py_compile library code"
python -m py_compile src/ai_deney/*.py

echo "[3/3] pytest"
pytest -q

echo "OK: gates passed"
