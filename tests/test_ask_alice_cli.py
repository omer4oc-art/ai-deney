from __future__ import annotations

import subprocess
import sys
import shutil
from datetime import datetime, timezone
from pathlib import Path

from tools.toy_hotel_portal.db import init_db, insert_reservation


def _seed_cli_db(db_path: Path) -> None:
    init_db(db_path)
    created_at = datetime(2025, 1, 1, 10, 0, 0, tzinfo=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    insert_reservation(
        db_path,
        {
            "reservation_id": "CLI-1",
            "guest_name": "CLI Guest",
            "check_in": "2025-03-05",
            "check_out": "2025-03-06",
            "room_type": "Standard",
            "adults": 1,
            "children": 0,
            "source_channel": "direct",
            "agency_id": "",
            "agency_name": "",
            "nightly_rate": 200.0,
            "total_paid": 200.0,
            "currency": "USD",
            "created_at": created_at,
        },
    )


def test_ask_alice_cli_writes_markdown_report() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    tmp_root = repo_root / "tests" / "_tmp_tasks" / "ask_alice_cli"
    shutil.rmtree(tmp_root, ignore_errors=True)
    tmp_root.mkdir(parents=True, exist_ok=True)
    db_path = tmp_root / "toy.db"
    out_path = tmp_root / "toy_sales_march_2025.md"
    _seed_cli_db(db_path)

    p = subprocess.run(
        [
            sys.executable,
            "scripts/ask_alice.py",
            "march 2025 sales data",
            "--db",
            str(db_path),
            "--out",
            str(out_path),
        ],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    assert p.returncode == 0, f"stdout={p.stdout}\nstderr={p.stderr}"
    assert out_path.exists()
    text = out_path.read_text(encoding="utf-8")
    assert "# Toy Portal Sales Report (March 2025)" in text
    assert "total_sales: 200.00" in text
    assert "WROTE:" in p.stdout


def test_ask_alice_cli_rejects_output_outside_repo() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    outside_path = Path("/tmp/ask_alice_out.md")
    p = subprocess.run(
        [
            sys.executable,
            "scripts/ask_alice.py",
            "march 2025 sales data",
            "--out",
            str(outside_path),
        ],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    assert p.returncode != 0
    assert "output path escapes repo root" in (p.stderr + p.stdout)
