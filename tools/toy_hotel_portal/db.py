"""SQLite helpers for the toy hotel portal."""

from __future__ import annotations

import csv
import hashlib
import io
import sqlite3
from datetime import date, timedelta
from pathlib import Path

ROOM_COUNT = 50

EXPORT_HEADERS = [
    "reservation_id",
    "guest_name",
    "check_in",
    "check_out",
    "room_type",
    "adults",
    "children",
    "source_channel",
    "agency_id",
    "agency_name",
    "nightly_rate",
    "total_paid",
    "currency",
    "created_at",
]

TABLE_HEADERS = [
    "reservation_id",
    "guest_name",
    "check_in",
    "check_out",
    "room_type",
    "source_channel",
]


def default_db_path(repo_root: Path) -> Path:
    return repo_root / "data" / "toy_portal" / "toy.db"


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with _connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS reservations (
                reservation_id TEXT PRIMARY KEY,
                guest_name TEXT NOT NULL,
                check_in TEXT NOT NULL,
                check_out TEXT NOT NULL,
                room_type TEXT NOT NULL,
                adults INTEGER NOT NULL,
                children INTEGER NOT NULL,
                source_channel TEXT NOT NULL,
                agency_id TEXT NOT NULL,
                agency_name TEXT NOT NULL,
                nightly_rate REAL NOT NULL,
                total_paid REAL NOT NULL,
                currency TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_res_check_in ON reservations(check_in)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_res_check_out ON reservations(check_out)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_res_created_at ON reservations(created_at DESC)")
        conn.commit()


def clear_db(db_path: Path) -> None:
    init_db(db_path)
    with _connect(db_path) as conn:
        conn.execute("DELETE FROM reservations")
        conn.commit()


def next_reservation_id(db_path: Path) -> str:
    init_db(db_path)
    with _connect(db_path) as conn:
        row = conn.execute("SELECT COUNT(*) AS n FROM reservations").fetchone()
    count = int(row["n"]) if row is not None else 0
    return f"RES-{count + 1:06d}"


def insert_reservation(db_path: Path, record: dict[str, object]) -> None:
    init_db(db_path)
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO reservations (
                reservation_id,
                guest_name,
                check_in,
                check_out,
                room_type,
                adults,
                children,
                source_channel,
                agency_id,
                agency_name,
                nightly_rate,
                total_paid,
                currency,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["reservation_id"],
                record["guest_name"],
                record["check_in"],
                record["check_out"],
                record["room_type"],
                int(record["adults"]),
                int(record["children"]),
                record["source_channel"],
                record["agency_id"],
                record["agency_name"],
                float(record["nightly_rate"]),
                float(record["total_paid"]),
                record["currency"],
                record["created_at"],
            ),
        )
        conn.commit()


def reservations_in_window(db_path: Path, start: date, end: date, limit: int) -> list[dict[str, object]]:
    init_db(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT reservation_id, guest_name, check_in, check_out, room_type, source_channel
            FROM reservations
            WHERE check_in <= ? AND check_out >= ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (end.isoformat(), start.isoformat(), int(limit)),
        ).fetchall()
    return [dict(row) for row in rows]


def export_rows_in_window(db_path: Path, start: date, end: date) -> list[dict[str, object]]:
    init_db(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT reservation_id, guest_name, check_in, check_out, room_type,
                   adults, children, source_channel, agency_id, agency_name,
                   nightly_rate, total_paid, currency, created_at
            FROM reservations
            WHERE check_in <= ? AND check_out >= ?
            ORDER BY created_at DESC
            """,
            (end.isoformat(), start.isoformat()),
        ).fetchall()
    return [dict(row) for row in rows]


def occupancy_days(db_path: Path, start: date, end: date) -> list[dict[str, object]]:
    init_db(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT check_in, check_out
            FROM reservations
            WHERE check_in <= ? AND check_out > ?
            """,
            (end.isoformat(), start.isoformat()),
        ).fetchall()

    spans: list[tuple[date, date]] = []
    for row in rows:
        spans.append((date.fromisoformat(str(row["check_in"])), date.fromisoformat(str(row["check_out"]))))

    days: list[dict[str, object]] = []
    current = start
    while current <= end:
        occupied = 0
        for check_in, check_out in spans:
            if check_in <= current < check_out:
                occupied += 1
        days.append({"date": current.isoformat(), "occupied_rooms": occupied})
        current += timedelta(days=1)
    return days


def occupancy_pct(days: list[dict[str, object]], room_count: int = ROOM_COUNT) -> float:
    if not days or room_count <= 0:
        return 0.0
    avg = sum(int(day["occupied_rooms"]) / float(room_count) for day in days) / float(len(days))
    return round(avg * 100.0, 2)


def get_sales_totals_for_dates(db_path: Path, dates: list[str]) -> list[dict[str, object]]:
    init_db(db_path)
    normalized = sorted(set(str(d) for d in dates if str(d).strip()))
    if not normalized:
        return []

    placeholders = ",".join(["?"] * len(normalized))
    with _connect(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT
                check_in AS date,
                COUNT(*) AS reservations,
                ROUND(COALESCE(SUM(total_paid), 0.0), 2) AS total_sales
            FROM reservations
            WHERE check_in IN ({placeholders})
            GROUP BY check_in
            ORDER BY check_in ASC
            """,
            tuple(normalized),
        ).fetchall()

    by_date = {str(row["date"]): row for row in rows}
    out: list[dict[str, object]] = []
    for d in normalized:
        row = by_date.get(d)
        if row is None:
            out.append({"date": d, "reservations": 0, "total_sales": 0.0})
        else:
            out.append(
                {
                    "date": d,
                    "reservations": int(row["reservations"] or 0),
                    "total_sales": float(row["total_sales"] or 0.0),
                }
            )
    return out


def to_csv(rows: list[dict[str, object]], *, redact_pii: bool) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=EXPORT_HEADERS, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        out = dict(row)
        if redact_pii:
            name = str(out.get("guest_name", ""))
            digest = hashlib.sha256(name.encode("utf-8")).hexdigest()[:12]
            out["guest_name"] = f"REDACTED_{digest}"
        writer.writerow(out)
    return buf.getvalue()
