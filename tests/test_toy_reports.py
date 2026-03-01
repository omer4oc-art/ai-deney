from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from ai_deney.reports.toy_reports import answer_question, answer_with_metadata
from tools.toy_hotel_portal.db import init_db, insert_reservation


def _insert_sale(
    db_path: Path,
    *,
    reservation_id: str,
    check_in: str,
    total_paid: float,
    source_channel: str = "direct",
    agency_id: str = "",
    agency_name: str = "",
) -> None:
    check_in_day = date.fromisoformat(check_in)
    check_out_day = check_in_day + timedelta(days=1)
    created_at = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    insert_reservation(
        db_path,
        {
            "reservation_id": reservation_id,
            "guest_name": "Unit Test",
            "check_in": check_in_day.isoformat(),
            "check_out": check_out_day.isoformat(),
            "room_type": "Standard",
            "adults": 1,
            "children": 0,
            "source_channel": source_channel,
            "agency_id": agency_id,
            "agency_name": agency_name,
            "nightly_rate": float(total_paid),
            "total_paid": float(total_paid),
            "currency": "USD",
            "created_at": created_at,
        },
    )


def test_answer_question_sales_month_markdown_uses_checkin_sum(tmp_path: Path) -> None:
    db_path = tmp_path / "toy.db"
    init_db(db_path)
    _insert_sale(db_path, reservation_id="T1", check_in="2025-03-05", total_paid=100.0, source_channel="direct")
    _insert_sale(db_path, reservation_id="T2", check_in="2025-03-10", total_paid=250.0, source_channel="booking")
    _insert_sale(db_path, reservation_id="T3", check_in="2025-04-01", total_paid=999.0, source_channel="direct")

    text = answer_question("march 2025 sales data", db_path=db_path, output_format="markdown")
    assert "# Toy Portal Sales Report (March 2025)" in text
    assert "Sales definition: SUM(total_paid) for reservations whose check_in date falls within the selected date range." in text
    assert "total_sales: 350.00" in text
    assert "| day | reservations | total_sales |" in text
    assert "| 2025-03-05 | 1 | 100.00 |" in text


def test_answer_with_metadata_supports_group_by_source_channel(tmp_path: Path) -> None:
    db_path = tmp_path / "toy.db"
    init_db(db_path)
    _insert_sale(db_path, reservation_id="S1", check_in="2025-03-01", total_paid=120.0, source_channel="direct")
    _insert_sale(db_path, reservation_id="S2", check_in="2025-03-02", total_paid=80.0, source_channel="direct")
    _insert_sale(db_path, reservation_id="S3", check_in="2025-03-02", total_paid=220.0, source_channel="booking")

    result = answer_with_metadata("sales by source channel for March 2025", db_path=db_path, output_format="markdown")
    assert result["metadata"]["group_by"] == "source_channel"
    assert result["metadata"]["total_sales"] == 420.0
    rendered = str(result["report"])
    assert "| source_channel | reservations | total_sales |" in rendered
    assert "| direct | 2 | 200.00 |" in rendered
    assert "| booking | 1 | 220.00 |" in rendered


def test_answer_question_supports_html_output(tmp_path: Path) -> None:
    db_path = tmp_path / "toy.db"
    init_db(db_path)
    _insert_sale(db_path, reservation_id="A1", check_in="2025-03-11", total_paid=300.0, source_channel="agency", agency_id="AG1", agency_name="Atlas")
    _insert_sale(db_path, reservation_id="A2", check_in="2025-03-12", total_paid=150.0, source_channel="agency", agency_id="AG1", agency_name="Atlas")

    html = answer_question("sales by agency for March 2025", db_path=db_path, output_format="html")
    assert "<!doctype html>" in html.lower()
    assert "<table>" in html
    assert "total_sales: 450.00" in html
