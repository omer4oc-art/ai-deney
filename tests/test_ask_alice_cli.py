from __future__ import annotations

import json
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


def test_ask_alice_cli_records_parse_transcript(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    db_path = tmp_path / "toy.db"
    out_path = repo_root / "tests" / "_tmp_tasks" / "ask_alice_cli" / "recorded_report.md"
    transcript_path = repo_root / "tests" / "_tmp_tasks" / "ask_alice_cli" / "parse_transcript.json"
    _seed_cli_db(db_path)

    p = subprocess.run(
        [
            sys.executable,
            "scripts/ask_alice.py",
            "sales by channel for March 2025",
            "--db",
            str(db_path),
            "--out",
            str(out_path),
            "--record-transcript",
            str(transcript_path),
        ],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    assert p.returncode == 0, f"stdout={p.stdout}\nstderr={p.stderr}"
    assert transcript_path.exists()
    parsed = json.loads(transcript_path.read_text(encoding="utf-8"))
    assert parsed["question"] == "sales by channel for March 2025"
    assert parsed["raw_llm_json"] is None
    assert parsed["validated_query_spec"]["report_type"] == "sales_by_channel"


def test_ask_alice_cli_replays_parse_transcript(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    db_path = tmp_path / "toy.db"
    out_path = repo_root / "tests" / "_tmp_tasks" / "ask_alice_cli" / "replayed_report.md"
    transcript_path = repo_root / "tests" / "_tmp_tasks" / "ask_alice_cli" / "parse_replay.json"
    _seed_cli_db(db_path)

    transcript_path.parent.mkdir(parents=True, exist_ok=True)
    transcript_path.write_text(
        json.dumps(
            {
                "question": "sales by channel for March 2025",
                "raw_llm_json": {"report_type": "sales_by_channel"},
                "validated_query_spec": {
                    "report_type": "sales_by_channel",
                    "year": 2025,
                    "month": 3,
                    "start_date": "2025-03-01",
                    "end_date": "2025-03-31",
                    "group_by": "channel",
                    "redact_pii": True,
                    "format": "md",
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    p = subprocess.run(
        [
            sys.executable,
            "scripts/ask_alice.py",
            "sales by channel for March 2025",
            "--db",
            str(db_path),
            "--out",
            str(out_path),
            "--replay-transcript",
            str(transcript_path),
        ],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    assert p.returncode == 0, f"stdout={p.stdout}\nstderr={p.stderr}"
    assert "INTENT_MODE: replay" in p.stdout
    text = out_path.read_text(encoding="utf-8")
    assert "total_sales: 200.00" in text


def test_ask_alice_cli_save_run_writes_artifacts(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    db_path = tmp_path / "toy.db"
    out_path = repo_root / "tests" / "_tmp_tasks" / "ask_alice_cli" / "saved_run_report.md"
    _seed_cli_db(db_path)

    p = subprocess.run(
        [
            sys.executable,
            "scripts/ask_alice.py",
            "sales by channel for March 2025",
            "--db",
            str(db_path),
            "--out",
            str(out_path),
            "--save-run",
            "1",
        ],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    assert p.returncode == 0, f"stdout={p.stdout}\nstderr={p.stderr}"
    assert "RUN_ID:" in p.stdout
    run_id = ""
    for line in p.stdout.splitlines():
        if line.startswith("RUN_ID: "):
            run_id = line.split("RUN_ID: ", 1)[1].strip()
            break
    assert run_id

    run_dir = repo_root / "outputs" / "_ask_runs" / run_id
    assert run_dir.exists()
    assert (run_dir / "request.json").exists()
    assert (run_dir / "response.json").exists()
    assert (run_dir / "output.md").exists()
    assert (run_dir / "index.md").exists()

    req = json.loads((run_dir / "request.json").read_text(encoding="utf-8"))
    resp = json.loads((run_dir / "response.json").read_text(encoding="utf-8"))
    assert req["question"] == "sales by channel for March 2025"
    assert req["format"] == "md"
    assert req["debug"] is False
    assert "trace" not in resp
