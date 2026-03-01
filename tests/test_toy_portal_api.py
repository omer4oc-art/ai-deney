from __future__ import annotations

import csv
import io
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from ai_deney.ask_runs import build_request_payload, save_ask_run
from ai_deney.reports.toy_reports import answer_with_metadata
from tools.toy_hotel_portal.app import create_app


def _client_with_tmp_db(tmp_path: Path) -> TestClient:
    app = create_app(repo_root=tmp_path, db_path=tmp_path / "toy.db")
    return TestClient(app)


def test_dashboard_contains_ask_panel_controls(tmp_path: Path) -> None:
    client = _client_with_tmp_db(tmp_path)
    res = client.get("/")
    assert res.status_code == 200
    html = res.text
    for element_id in [
        "ask-panel",
        "ask-input",
        "ask-redact",
        "ask-format",
        "ask-submit",
        "ask-save",
        "ask-download",
        "ask-download-json",
        "ask-save-banner",
        "ask-save-run-id",
        "ask-save-link",
        "ask-trace-toggle",
        "ask-trace",
        "ask-warnings",
        "ask-meta",
        "ask-spans-count",
        "ask-output",
        "ask-html-preview",
        "ask-delta-card",
        "ask-delta-total",
        "ask-delta-pct",
        "ask-max-span",
        "ask-min-span",
        "ask-runs-panel",
        "ask-runs-refresh",
        "ask-runs-empty",
        "ask-runs-list",
    ]:
        assert f'id="{element_id}"' in html


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


def test_ask_endpoint_returns_deterministic_sales_report(tmp_path: Path) -> None:
    client = _client_with_tmp_db(tmp_path)
    payload = {
        "guest_name": "Alice A",
        "check_in": "2025-03-05",
        "check_out": "2025-03-07",
        "room_type": "Deluxe",
        "adults": 2,
        "children": 0,
        "source_channel": "booking",
        "nightly_rate": 120.00,
        "total_paid": 240.00,
        "currency": "USD",
    }
    assert client.post("/api/checkin", json=payload).status_code == 200
    payload["guest_name"] = "Bob B"
    payload["check_in"] = "2025-03-18"
    payload["check_out"] = "2025-03-19"
    payload["source_channel"] = "direct"
    payload["total_paid"] = 150.00
    assert client.post("/api/checkin", json=payload).status_code == 200

    ask_res = client.post(
        "/api/ask",
        json={
            "question": "sales by source channel for March 2025",
            "format": "md",
            "redact_pii": True,
        },
    )
    assert ask_res.status_code == 200
    body = ask_res.json()
    assert set(body.keys()) == {"ok", "spec", "meta", "output", "content_type"}
    assert body["ok"] is True
    assert body["content_type"] == "text/markdown"
    assert isinstance(body["output"], str) and body["output"]
    assert body["spec"]["report_type"] == "sales_by_channel"
    assert body["spec"]["group_by"] == "channel"
    assert body["meta"]["report_type"] == "sales_by_channel"
    assert "| channel | reservations | total_sales |" in body["output"]
    assert "total_sales: 390.00" in body["output"]
    assert "trace" not in body


def test_debug_trace_absent_by_default(tmp_path: Path) -> None:
    client = _client_with_tmp_db(tmp_path)
    ask_res = client.post(
        "/api/ask",
        json={
            "question": "sales by channel for March 2025",
            "format": "md",
            "redact_pii": True,
        },
    )
    assert ask_res.status_code == 200
    body = ask_res.json()
    assert "trace" not in body


def test_debug_trace_present_and_sanitized(tmp_path: Path) -> None:
    client = _client_with_tmp_db(tmp_path)
    payload = {
        "guest_name": "Trace Guest",
        "check_in": "2025-03-05",
        "check_out": "2025-03-07",
        "room_type": "Deluxe",
        "adults": 2,
        "children": 0,
        "source_channel": "booking",
        "nightly_rate": 120.00,
        "total_paid": 240.00,
        "currency": "USD",
    }
    assert client.post("/api/checkin", json=payload).status_code == 200

    ask_res = client.post(
        "/api/ask?debug=1",
        json={
            "question": "sales by source channel for March 2025",
            "format": "md",
            "redact_pii": True,
        },
    )
    assert ask_res.status_code == 200
    body = ask_res.json()
    assert "trace" in body
    trace = body["trace"]
    assert isinstance(trace, (dict, list))
    assert isinstance(trace, dict)
    assert trace["mode"] == "deterministic"
    assert trace["chosen"]["report_type"] == "sales_by_channel"
    assert trace["chosen"]["group_by"] == "channel"
    assert "parsed" in trace
    assert "start_date" in trace["parsed"]
    assert "end_date" in trace["parsed"]
    assert "validation_notes" in trace

    trace_json = json.dumps(trace).lower()
    assert "guest_name" not in trace_json
    assert "\"rows\"" not in trace_json


def test_ask_endpoint_debug_trace_enabled_by_env_var(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AI_DENEY_TOY_DEBUG_TRACE", "1")
    client = _client_with_tmp_db(tmp_path)
    ask_res = client.post(
        "/api/ask",
        json={
            "question": "sales by channel for March 2025",
            "format": "md",
            "redact_pii": True,
        },
    )
    assert ask_res.status_code == 200
    body = ask_res.json()
    assert "trace" in body


def test_ask_endpoint_rejects_integer_redact_pii(tmp_path: Path) -> None:
    client = _client_with_tmp_db(tmp_path)
    ask_res = client.post(
        "/api/ask",
        json={
            "question": "sales by channel for March 2025",
            "format": "md",
            "redact_pii": 1,
        },
    )
    assert ask_res.status_code == 422


def test_ask_endpoint_matches_shared_answer_pipeline(tmp_path: Path) -> None:
    client = _client_with_tmp_db(tmp_path)
    payload = {
        "guest_name": "Alice A",
        "check_in": "2025-03-05",
        "check_out": "2025-03-07",
        "room_type": "Deluxe",
        "adults": 2,
        "children": 0,
        "source_channel": "booking",
        "nightly_rate": 120.00,
        "total_paid": 240.00,
        "currency": "USD",
    }
    assert client.post("/api/checkin", json=payload).status_code == 200
    payload["guest_name"] = "Bob B"
    payload["check_in"] = "2025-03-18"
    payload["check_out"] = "2025-03-19"
    payload["source_channel"] = "direct"
    payload["total_paid"] = 150.00
    assert client.post("/api/checkin", json=payload).status_code == 200

    question = "Sales by channel for March 2025"
    ask_res = client.post("/api/ask", json={"question": question, "format": "md", "redact_pii": True})
    assert ask_res.status_code == 200
    body = ask_res.json()

    expected = answer_with_metadata(
        question,
        db_path=client.app.state.db_path,
        output_format="markdown",
        redact_pii=True,
    )

    api_report = str(body["output"])
    expected_report = str(expected["report"])
    assert api_report.splitlines()[0] == expected_report.splitlines()[0]
    assert "| channel | reservations | total_sales |" in api_report
    assert "| channel | reservations | total_sales |" in expected_report
    assert "total_sales: 390.00" in api_report
    assert "total_sales: 390.00" in expected_report
    assert body["spec"]["report_type"] == expected["spec"]["report_type"]


def test_ask_endpoint_html_returns_html_content_type(tmp_path: Path) -> None:
    client = _client_with_tmp_db(tmp_path)
    payload = {
        "guest_name": "Html Guest",
        "check_in": "2025-03-05",
        "check_out": "2025-03-06",
        "room_type": "Deluxe",
        "adults": 2,
        "children": 0,
        "source_channel": "direct",
        "nightly_rate": 100.00,
        "total_paid": 100.00,
        "currency": "USD",
    }
    assert client.post("/api/checkin", json=payload).status_code == 200

    ask_res = client.post(
        "/api/ask",
        json={"question": "sales for March 2025", "format": "html", "redact_pii": True},
    )
    assert ask_res.status_code == 200
    body = ask_res.json()
    assert body["content_type"] == "text/html"
    assert "<!doctype html>" in body["output"].lower()


def test_ask_endpoint_html_escapes_question_script_input(tmp_path: Path) -> None:
    client = _client_with_tmp_db(tmp_path)
    payload = {
        "guest_name": "Safe Guest",
        "check_in": "2025-03-05",
        "check_out": "2025-03-06",
        "room_type": "Deluxe",
        "adults": 2,
        "children": 0,
        "source_channel": "direct",
        "nightly_rate": 110.00,
        "total_paid": 110.00,
        "currency": "USD",
    }
    assert client.post("/api/checkin", json=payload).status_code == 200

    question = "Sales by channel for March 2025 <script>alert(1)</script>"
    ask_res = client.post(
        "/api/ask",
        json={"question": question, "format": "html", "redact_pii": True},
    )
    assert ask_res.status_code == 200
    body = ask_res.json()
    assert "<script>alert(1)</script>" not in body["output"]
    assert "&lt;script&gt;" not in body["output"]


def test_ask_endpoint_same_question_same_output(tmp_path: Path) -> None:
    client = _client_with_tmp_db(tmp_path)
    payload = {
        "guest_name": "Alice A",
        "check_in": "2025-03-05",
        "check_out": "2025-03-07",
        "room_type": "Deluxe",
        "adults": 2,
        "children": 0,
        "source_channel": "booking",
        "nightly_rate": 120.00,
        "total_paid": 240.00,
        "currency": "USD",
    }
    assert client.post("/api/checkin", json=payload).status_code == 200

    req = {"question": "Sales by channel for March 2025", "format": "md", "redact_pii": True}
    first = client.post("/api/ask", json=req)
    second = client.post("/api/ask", json=req)
    assert first.status_code == 200
    assert second.status_code == 200
    first_body = first.json()
    second_body = second.json()
    assert first_body["output"] == second_body["output"]
    assert first_body["spec"] == second_body["spec"]
    assert first_body["meta"] == second_body["meta"]


def test_ask_sales_multi_span_iso_query_includes_spans_count_totals_and_deltas(tmp_path: Path) -> None:
    client = _client_with_tmp_db(tmp_path)
    for guest_name, check_in, total_paid in [
        ("Date Guest 1", "2025-03-01", 120.0),
        ("Date Guest 2", "2025-03-01", 80.0),
        ("Date Guest 3", "2025-06-03", 150.0),
    ]:
        assert (
            client.post(
                "/api/checkin",
                json={
                    "guest_name": guest_name,
                    "check_in": check_in,
                    "check_out": "2025-06-04" if check_in == "2025-06-03" else "2025-03-02",
                    "room_type": "Standard",
                    "adults": 1,
                    "children": 0,
                    "source_channel": "direct",
                    "nightly_rate": total_paid,
                    "total_paid": total_paid,
                    "currency": "USD",
                },
            ).status_code
            == 200
        )

    ask_res = client.post(
        "/api/ask",
        json={
            "question": "total sales on 2025-03-01 and 2025-06-03",
            "format": "md",
            "redact_pii": True,
        },
    )
    assert ask_res.status_code == 200
    body = ask_res.json()
    assert "spec" in body
    assert "plan" not in body
    assert body["spec"]["report_type"] == "sales_day"
    assert [span["start_date"] for span in body["spec"]["spans"]] == ["2025-03-01", "2025-06-03"]
    assert body["spec"]["compare"] is True
    assert body["meta"]["spans_count"] == 2
    assert body["meta"]["compare"] is True
    assert [row["total_sales"] for row in body["meta"]["totals"]] == [200.0, 150.0]
    assert set(body["meta"]["deltas"].keys()) >= {
        "delta_total_sales",
        "pct_change_total_sales",
        "max_span_label",
        "max_span_total_sales",
        "min_span_label",
        "min_span_total_sales",
    }
    assert body["meta"]["deltas"]["delta_total_sales"] == -50.0
    assert body["meta"]["deltas"]["pct_change_total_sales"] == -25.0
    assert "2025-03-01" in body["output"]
    assert "2025-06-03" in body["output"]
    assert "| label | start | end | reservations | total_sales |" in body["output"]


def test_ask_multi_span_smoke_default_and_debug_trace(tmp_path: Path) -> None:
    client = _client_with_tmp_db(tmp_path)
    for guest_name, check_in, total_paid in [
        ("Smoke Guest 1", "2025-03-01", 100.0),
        ("Smoke Guest 2", "2025-06-03", 300.0),
    ]:
        assert (
            client.post(
                "/api/checkin",
                json={
                    "guest_name": guest_name,
                    "check_in": check_in,
                    "check_out": "2025-06-04" if check_in == "2025-06-03" else "2025-03-02",
                    "room_type": "Standard",
                    "adults": 1,
                    "children": 0,
                    "source_channel": "direct",
                    "nightly_rate": total_paid,
                    "total_paid": total_paid,
                    "currency": "USD",
                },
            ).status_code
            == 200
        )

    request_json = {
        "question": "Total sales on March 1st 2025 and June 3rd 2025",
        "format": "md",
        "redact_pii": True,
    }
    normal = client.post("/api/ask", json=request_json)
    assert normal.status_code == 200
    normal_body = normal.json()
    assert normal_body["ok"] is True
    assert normal_body["meta"]["spans_count"] == 2
    assert len(normal_body["meta"]["totals"]) == 2
    assert normal_body["spec"]["compare"] is True
    assert normal_body["meta"]["compare"] is True
    assert "trace" not in normal_body

    debug = client.post("/api/ask?debug=1", json=request_json)
    assert debug.status_code == 200
    debug_body = debug.json()
    assert debug_body["ok"] is True
    assert "trace" in debug_body
    serialized_trace = json.dumps(debug_body["trace"], sort_keys=True).lower()
    assert "guest_name" not in serialized_trace


def test_ask_multi_span_spec_compare_equals_meta_compare(tmp_path: Path) -> None:
    client = _client_with_tmp_db(tmp_path)
    for guest_name, check_in, total_paid in [
        ("Parity Guest 1", "2025-03-01", 140.0),
        ("Parity Guest 2", "2025-06-03", 260.0),
    ]:
        assert (
            client.post(
                "/api/checkin",
                json={
                    "guest_name": guest_name,
                    "check_in": check_in,
                    "check_out": "2025-06-04" if check_in == "2025-06-03" else "2025-03-02",
                    "room_type": "Standard",
                    "adults": 1,
                    "children": 0,
                    "source_channel": "direct",
                    "nightly_rate": total_paid,
                    "total_paid": total_paid,
                    "currency": "USD",
                },
            ).status_code
            == 200
        )

    body = client.post(
        "/api/ask",
        json={
            "question": "Total sales on March 1st 2025 and June 3rd 2025",
            "format": "md",
            "redact_pii": True,
        },
    ).json()
    assert body["spec"]["compare"] == body["meta"]["compare"]
    assert body["spec"]["compare"] is True
    assert body["meta"]["spans_count"] == 2

    debug_body = client.post(
        "/api/ask?debug=1",
        json={
            "question": "Total sales on March 1st 2025 and June 3rd 2025",
            "format": "md",
            "redact_pii": True,
        },
    ).json()
    assert debug_body["spec"]["compare"] == debug_body["meta"]["compare"] == True


def test_ask_sales_for_dates_compare_includes_delta_line(tmp_path: Path) -> None:
    client = _client_with_tmp_db(tmp_path)
    for guest_name, check_in, total_paid in [
        ("Cmp Guest 1", "2025-03-01", 200.0),
        ("Cmp Guest 2", "2025-06-03", 500.0),
    ]:
        assert (
            client.post(
                "/api/checkin",
                json={
                    "guest_name": guest_name,
                    "check_in": check_in,
                    "check_out": "2025-06-04" if check_in == "2025-06-03" else "2025-03-02",
                    "room_type": "Standard",
                    "adults": 1,
                    "children": 0,
                    "source_channel": "direct",
                    "nightly_rate": total_paid,
                    "total_paid": total_paid,
                    "currency": "USD",
                },
            ).status_code
            == 200
        )

    ask_res = client.post(
        "/api/ask",
        json={"question": "compare March 1 vs June 3 2025", "format": "md", "redact_pii": True},
    )
    assert ask_res.status_code == 200
    body = ask_res.json()
    assert "spec" in body
    assert "plan" not in body
    assert len(body["spec"]["spans"]) == 2
    assert body["meta"]["spans_count"] == 2
    assert body["meta"]["compare"] is True
    assert body["meta"]["deltas"]["delta_total_sales"] == 300.0
    assert body["meta"]["deltas"]["pct_change_total_sales"] == 150.0
    assert "delta_total_sales(first_to_last): 2025-06-03 - 2025-03-01 = 300.00" in body["output"]
    assert "pct_change_total_sales(first_to_last): 150.00%" in body["output"]


def test_ask_sales_for_dates_missing_year_adds_warning(tmp_path: Path) -> None:
    client = _client_with_tmp_db(tmp_path)
    for guest_name, check_in, total_paid in [
        ("Warn Guest 1", "2025-03-01", 180.0),
        ("Warn Guest 2", "2025-06-03", 210.0),
    ]:
        assert (
            client.post(
                "/api/checkin",
                json={
                    "guest_name": guest_name,
                    "check_in": check_in,
                    "check_out": "2025-06-04" if check_in == "2025-06-03" else "2025-03-02",
                    "room_type": "Standard",
                    "adults": 1,
                    "children": 0,
                    "source_channel": "direct",
                    "nightly_rate": total_paid,
                    "total_paid": total_paid,
                    "currency": "USD",
                },
            ).status_code
            == 200
        )

    ask_res = client.post(
        "/api/ask",
        json={"question": "compare March 1 vs June 3", "format": "md", "redact_pii": True},
    )
    assert ask_res.status_code == 200
    body = ask_res.json()
    assert "spec" in body
    assert "plan" not in body
    assert body["meta"]["warnings"]
    assert any("defaulted to 2025" in str(w) for w in body["meta"]["warnings"])


def test_ask_sales_single_span_query_compare_false_and_no_delta_payload(tmp_path: Path) -> None:
    client = _client_with_tmp_db(tmp_path)
    assert (
        client.post(
            "/api/checkin",
            json={
                "guest_name": "Single Span Guest",
                "check_in": "2025-03-01",
                "check_out": "2025-03-02",
                "room_type": "Standard",
                "adults": 1,
                "children": 0,
                "source_channel": "direct",
                "nightly_rate": 100.0,
                "total_paid": 100.0,
                "currency": "USD",
            },
        ).status_code
        == 200
    )

    ask_res = client.post(
        "/api/ask",
        json={"question": "Total sales on March 1st 2025", "format": "md", "redact_pii": True},
    )
    assert ask_res.status_code == 200
    body = ask_res.json()
    assert len(body["spec"]["spans"]) == 0
    assert body["spec"]["compare"] is False
    assert body["meta"]["compare"] is False
    assert body["meta"]["spans_count"] in (None, 1)
    assert not body["meta"].get("deltas")


def test_ask_sales_for_dates_same_request_same_output_hash(tmp_path: Path) -> None:
    client = _client_with_tmp_db(tmp_path)
    for guest_name, check_in, total_paid in [
        ("Det Guest 1", "2025-03-01", 100.0),
        ("Det Guest 2", "2025-06-03", 300.0),
    ]:
        assert (
            client.post(
                "/api/checkin",
                json={
                    "guest_name": guest_name,
                    "check_in": check_in,
                    "check_out": "2025-06-04" if check_in == "2025-06-03" else "2025-03-02",
                    "room_type": "Standard",
                    "adults": 1,
                    "children": 0,
                    "source_channel": "direct",
                    "nightly_rate": total_paid,
                    "total_paid": total_paid,
                    "currency": "USD",
                },
            ).status_code
            == 200
        )

    request_json = {
        "question": "compare 2025-03-01 vs 2025-06-03",
        "format": "md",
        "redact_pii": True,
    }
    first = client.post("/api/ask", json=request_json)
    second = client.post("/api/ask", json=request_json)
    assert first.status_code == 200
    assert second.status_code == 200
    first_hash = hashlib.sha256(first.json()["output"].encode("utf-8")).hexdigest()
    second_hash = hashlib.sha256(second.json()["output"].encode("utf-8")).hexdigest()
    assert first_hash == second_hash


def test_ask_save_creates_expected_artifacts_without_trace_by_default(tmp_path: Path) -> None:
    client = _client_with_tmp_db(tmp_path)
    res = client.post(
        "/api/ask/save",
        json={"question": "Sales by channel for March 2025", "format": "md", "redact_pii": True},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert "run_id" in body and body["run_id"]
    run_dir = tmp_path / body["run_dir"]
    assert run_dir.exists()
    assert (run_dir / "request.json").exists()
    assert (run_dir / "response.json").exists()
    assert (run_dir / "output.md").exists()
    assert (run_dir / "index.md").exists()

    request_payload = json.loads((run_dir / "request.json").read_text(encoding="utf-8"))
    response_payload = json.loads((run_dir / "response.json").read_text(encoding="utf-8"))
    output_text = (run_dir / "output.md").read_text(encoding="utf-8")
    assert request_payload == {
        "question": "Sales by channel for March 2025",
        "format": "md",
        "redact_pii": True,
        "debug": False,
    }
    assert "trace" not in response_payload
    assert "trace" not in json.dumps(response_payload).lower()
    assert output_text == str(body["response"]["output"])
    assert "guest_name" not in output_text.lower()


def test_ask_save_identical_payloads_keep_same_hash8_suffix_and_output(tmp_path: Path) -> None:
    client = _client_with_tmp_db(tmp_path)
    req = {"question": "Sales by channel for March 2025", "format": "md", "redact_pii": True}
    first = client.post("/api/ask/save", json=req)
    second = client.post("/api/ask/save", json=req)
    assert first.status_code == 200
    assert second.status_code == 200
    first_body = first.json()
    second_body = second.json()
    assert first_body["run_id"].split("_")[-1] == second_body["run_id"].split("_")[-1]
    assert first_body["response"]["output"] == second_body["response"]["output"]

    first_run_dir = tmp_path / first_body["run_dir"]
    second_run_dir = tmp_path / second_body["run_dir"]
    first_output = (first_run_dir / "output.md").read_text(encoding="utf-8")
    second_output = (second_run_dir / "output.md").read_text(encoding="utf-8")
    assert first_output == second_output


def test_ask_save_debug_writes_trace_without_guest_name(tmp_path: Path) -> None:
    client = _client_with_tmp_db(tmp_path)
    res = client.post(
        "/api/ask/save?debug=1",
        json={"question": "Sales by channel for March 2025", "format": "md", "redact_pii": True},
    )
    assert res.status_code == 200
    body = res.json()
    run_dir = tmp_path / body["run_dir"]
    response_payload = json.loads((run_dir / "response.json").read_text(encoding="utf-8"))
    assert "trace" in response_payload
    trace_json = json.dumps(response_payload["trace"], sort_keys=True).lower()
    assert "guest_name" not in trace_json


def test_ask_runs_lists_latest_saved_runs(tmp_path: Path) -> None:
    client = _client_with_tmp_db(tmp_path)
    for question in ["Sales by channel for March 2025", "Sales for March 2025"]:
        res = client.post("/api/ask/save", json={"question": question, "format": "md", "redact_pii": True})
        assert res.status_code == 200

    listed = client.get("/api/ask/runs", params={"limit": 20})
    assert listed.status_code == 200
    body = listed.json()
    assert body["ok"] is True
    assert len(body["runs"]) >= 2
    first = body["runs"][0]
    assert "run_id" in first
    assert "question_snippet" in first
    assert "created_at" in first
    assert "index_url" in first


def test_ask_compare_is_stable_and_redacts_guest_name_when_either_run_is_redacted(tmp_path: Path) -> None:
    client = _client_with_tmp_db(tmp_path)
    repo_root = tmp_path.resolve()
    run_a = save_ask_run(
        repo_root=repo_root,
        request_payload=build_request_payload(
            question="manual run a",
            ask_format="md",
            redact_pii=False,
            debug=False,
        ),
        response_payload={"ok": True, "spec": {}, "meta": {"report_type": "manual"}, "content_type": "text/markdown"},
        output_text="guest_name: Alice A\nvalue: 1\n",
    )
    run_b = save_ask_run(
        repo_root=repo_root,
        request_payload=build_request_payload(
            question="manual run b",
            ask_format="md",
            redact_pii=True,
            debug=False,
        ),
        response_payload={"ok": True, "spec": {}, "meta": {"report_type": "manual"}, "content_type": "text/markdown"},
        output_text="guest_name: Bob B\nvalue: 2\n",
    )
    first = client.get(
        "/api/ask/compare",
        params={"run_a": run_a["run_id"], "run_b": run_b["run_id"], "format": "md"},
    )
    second = client.get(
        "/api/ask/compare",
        params={"run_a": run_a["run_id"], "run_b": run_b["run_id"], "format": "md"},
    )
    assert first.status_code == 200
    assert second.status_code == 200
    first_body = first.json()
    second_body = second.json()
    assert first_body["diff"] == second_body["diff"]
    assert first_body["diff"].startswith("--- ")
    assert "Alice A" not in first_body["diff"]
    assert "Bob B" not in first_body["diff"]
    assert "guest_name: REDACTED" in first_body["diff"]
