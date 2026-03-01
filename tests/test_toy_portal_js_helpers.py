from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest


def test_ask_js_helpers_slug_and_hash_are_pure_and_stable() -> None:
    if shutil.which("node") is None:
        pytest.skip("node is required for JS helper unit tests")

    repo_root = Path(__file__).resolve().parents[1]
    app_js = repo_root / "tools" / "toy_hotel_portal" / "static" / "app.js"
    script = f"""
const helpers = require({str(app_js)!r});
const slug = helpers.slugifyText("Sales by channel for March 2025!!!");
const short = helpers.buildAskRunShortSlug("Sales by channel for March 2025!!!");
const hashA = helpers.buildAskRunHash8({{question:"Sales by channel for March 2025", format:"md", redact_pii:true, debug:false}});
const hashB = helpers.buildAskRunHash8({{question:"Sales by channel for March 2025", format:"md", redact_pii:true, debug:false}});
const hashC = helpers.buildAskRunHash8({{question:"Sales by channel for March 2025", format:"md", redact_pii:true, debug:true}});
console.log(JSON.stringify({{slug, short, hashA, hashB, hashC}}));
"""
    run = subprocess.run(["node", "-e", script], cwd=str(repo_root), capture_output=True, text=True, check=False)
    assert run.returncode == 0, run.stderr or run.stdout
    payload = json.loads(run.stdout.strip())
    assert payload["slug"] == "sales-by-channel-for-march-2025"
    assert payload["short"] == "sales-by-channel-for-march-2025"
    assert payload["hashA"] == payload["hashB"]
    assert payload["hashA"] != payload["hashC"]
    assert re.fullmatch(r"[0-9a-f]{8}", payload["hashA"]) is not None
