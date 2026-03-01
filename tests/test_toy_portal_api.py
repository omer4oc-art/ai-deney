from __future__ import annotations

import csv
import io
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from tools.toy_hotel_portal.app import create_app


def _client_with_tmp_db(tmp_path: Path) -> TestClient:
    app = create_app(repo_root=tmp_path, db_path=tmp_path / "toy.db")
    return TestClient(app)


def test_checkin_insert_and_reservations_list(tmp_path: Path) -> None:
    client = _client_with_tmp_db(tmp_path)

    payload = {
        "guest_name": "Ada Lovelace",
        "check_in": "2025-05-01",
        "check_out": "2025-05-04",
        "room_type": "Deluxe",
        "adults": 2,
        "children": 1,
        "source_channel": "booking",
        "agency_id": "",
        "agency_name": "",
        "nightly_rate": 120.50,
        "total_paid": 361.50,
        "currency": "USD",
    }
    checkin_json = client.post("/api/checkin", json=payload)
    assert checkin_json.status_code == 200
    data_json = checkin_json.json()
    assert data_json["ok"] is True
    assert data_json["reservation_id"].startswith("RES-")

    checkin_form = client.post(
        "/api/checkin",
        data={
            "guest_name": "Grace Hopper",
            "check_in": "2025-05-02",
            "check_out": "2025-05-03",
            "room_type": "Standard",
            "adults": "1",
            "children": "0",
            "source_channel": "direct",
            "nightly_rate": "99.99",
            "total_paid": "99.99",
            "currency": "USD",
        },
    )
    assert checkin_form.status_code == 200
    assert checkin_form.json()["ok"] is True

    res = client.get("/api/reservations", params={"start": "2025-05-01", "end": "2025-05-10", "limit": 10})
    assert res.status_code == 200
    rows = res.json()
    assert isinstance(rows, list)
    assert len(rows) == 2
    assert set(rows[0].keys()) == {
        "reservation_id",
        "guest_name",
        "check_in",
        "check_out",
        "room_type",
        "source_channel",
    }


def test_occupancy_logic(tmp_path: Path) -> None:
    client = _client_with_tmp_db(tmp_path)
    res = client.post(
        "/api/checkin",
        json={
            "reservation_id": "OCC-1",
            "guest_name": "Test Guest",
            "check_in": "2025-01-10",
            "check_out": "2025-01-12",
            "room_type": "Standard",
            "adults": 1,
            "children": 0,
            "source_channel": "direct",
            "nightly_rate": 100,
            "total_paid": 200,
            "currency": "USD",
        },
    )
    assert res.status_code == 200

    occ = client.get("/api/occupancy", params={"start": "2025-01-10", "end": "2025-01-12"})
    assert occ.status_code == 200
    body = occ.json()
    assert body["room_count"] == 50
    days = {d["date"]: d["occupied_rooms"] for d in body["days"]}
    assert days["2025-01-10"] == 1
    assert days["2025-01-11"] == 1
    assert days["2025-01-12"] == 0
    assert body["occupancy_pct"] == 1.33


def test_export_csv_headers_and_redaction(tmp_path: Path) -> None:
    client = _client_with_tmp_db(tmp_path)
    res = client.post(
        "/api/checkin",
        json={
            "reservation_id": "EXP-1",
            "guest_name": "Jane Doe",
            "check_in": "2025-06-01",
            "check_out": "2025-06-02",
            "room_type": "Suite",
            "adults": 2,
            "children": 0,
            "source_channel": "agency",
            "agency_id": "AG001",
            "agency_name": "Atlas Travel",
            "nightly_rate": 250,
            "total_paid": 250,
            "currency": "USD",
        },
    )
    assert res.status_code == 200

    export_res = client.get("/api/export", params={"start": "2025-06-01", "end": "2025-06-10", "redact_pii": 1})
    assert export_res.status_code == 200
    assert export_res.headers["content-type"].startswith("text/csv")
    assert export_res.headers["content-disposition"].startswith("attachment;")
    assert "toy_portal_2025-06-01_2025-06-10.csv" in export_res.headers["content-disposition"]
    assert export_res.text.strip()
    first_line = export_res.text.splitlines()[0]
    assert (
        first_line
        == "reservation_id,guest_name,check_in,check_out,room_type,adults,children,source_channel,agency_id,agency_name,nightly_rate,total_paid,currency,created_at"
    )

    rows = list(csv.DictReader(io.StringIO(export_res.text)))
    assert len(rows) == 1
    assert rows[0]["reservation_id"] == "EXP-1"
    assert rows[0]["guest_name"].startswith("REDACTED_")


def test_seeded_occupancy_covers_default_dashboard_window(tmp_path: Path) -> None:
    db_path = tmp_path / "toy.db"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.toy_hotel_portal.seed",
            "--db",
            str(db_path),
            "--rows",
            "200",
            "--reset",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout

    client = _client_with_tmp_db(tmp_path)
    occ = client.get("/api/occupancy", params={"start": "2025-06-19", "end": "2025-06-25"})
    assert occ.status_code == 200
    days = occ.json()["days"]
    assert any(int(day["occupied_rooms"]) > 0 for day in days)


def test_seeded_hot_range_occupancy_pct_above_50(tmp_path: Path) -> None:
    db_path = tmp_path / "toy.db"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.toy_hotel_portal.seed",
            "--db",
            str(db_path),
            "--rows",
            "1000",
            "--seed",
            "20260301",
            "--date-start",
            "2025-01-01",
            "--date-end",
            "2025-12-31",
            "--hot-range",
            "2025-06-19:2025-06-25",
            "--hot-occupancy",
            "0.75",
            "--reset",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout

    client = _client_with_tmp_db(tmp_path)
    occ = client.get("/api/occupancy", params={"start": "2025-06-19", "end": "2025-06-25"})
    assert occ.status_code == 200
    body = occ.json()
    assert float(body["occupancy_pct"]) > 50.0
