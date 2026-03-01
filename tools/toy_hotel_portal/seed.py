"""Deterministic seed data for the toy hotel portal SQLite database."""

from __future__ import annotations

import argparse
import random
import sqlite3
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from tools.toy_hotel_portal.db import ROOM_COUNT, clear_db, default_db_path, init_db, insert_reservation


def _repo_root_from_here() -> Path:
    return Path(__file__).resolve().parents[2]


def _count_rows(db_path: Path) -> int:
    init_db(db_path)
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute("SELECT COUNT(*) FROM reservations").fetchone()
        return int(row[0]) if row else 0
    finally:
        conn.close()


def _parse_iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid date: {value!r}, expected YYYY-MM-DD") from exc


def _parse_hot_range(value: str) -> tuple[date, date]:
    start_raw, sep, end_raw = value.partition(":")
    if not sep:
        raise argparse.ArgumentTypeError(f"invalid hot range: {value!r}, expected YYYY-MM-DD:YYYY-MM-DD")
    start_day = _parse_iso_date(start_raw)
    end_day = _parse_iso_date(end_raw)
    if end_day < start_day:
        raise argparse.ArgumentTypeError("hot-range end must be >= start")
    return start_day, end_day


def _iter_days(start: date, end: date) -> list[date]:
    if end < start:
        return []
    days: list[date] = []
    current = start
    while current <= end:
        days.append(current)
        current += timedelta(days=1)
    return days


def _build_hot_targets(
    hot_days: list[date],
    *,
    target_rooms: int,
    room_count: int,
    max_rows: int,
) -> list[int]:
    if not hot_days or target_rooms <= 0:
        return [0 for _ in hot_days]

    # Keep day-to-day movement small while staying near target occupancy.
    pattern = (-2, -1, 0, 1, 2, 1, 0, -1)
    wiggle = max(1, int(round(room_count * 0.04)))
    floor = max(0, target_rooms - wiggle)
    ceiling = min(room_count, max_rows, target_rooms + wiggle)

    targets: list[int] = []
    for idx in range(len(hot_days)):
        goal = target_rooms + pattern[idx % len(pattern)]
        goal = min(ceiling, max(floor, goal))
        targets.append(goal)
    return targets


def _spans_from_targets(hot_days: list[date], targets: list[int]) -> list[tuple[date, date]]:
    """Convert per-day occupancy targets to overlapping reservation spans."""
    if not hot_days:
        return []

    remaining = [max(0, int(value)) for value in targets]
    spans: list[tuple[date, date]] = []
    while True:
        start_idx = next((idx for idx, value in enumerate(remaining) if value > 0), None)
        if start_idx is None:
            break

        end_idx = start_idx
        while end_idx + 1 < len(remaining) and remaining[end_idx + 1] > 0:
            end_idx += 1

        for idx in range(start_idx, end_idx + 1):
            remaining[idx] -= 1

        spans.append((hot_days[start_idx], hot_days[end_idx] + timedelta(days=1)))

    return spans


def _overlaps(check_in: date, check_out: date, span_start: date, span_end: date) -> bool:
    # Reservation overlap test where check_out is exclusive.
    return check_in <= span_end and check_out > span_start


def _build_rows(
    total_rows: int,
    *,
    seed: int,
    date_start: date,
    date_end: date,
    hot_start: date,
    hot_end: date,
    hot_occupancy: float,
) -> list[dict[str, object]]:
    rng = random.Random(seed)
    if total_rows <= 0:
        return []

    first_names = [
        "Alex",
        "Mina",
        "Jordan",
        "Taylor",
        "Sam",
        "Casey",
        "Drew",
        "Robin",
        "Avery",
        "Riley",
    ]
    last_names = [
        "Stone",
        "Parker",
        "Lee",
        "Kim",
        "Reed",
        "Walker",
        "Shaw",
        "Kaya",
        "Mora",
        "Noor",
    ]

    room_type_weights = [
        ("Standard", 0.62),
        ("Deluxe", 0.28),
        ("Suite", 0.10),
    ]
    channel_weights = [
        ("direct", 0.36),
        ("booking", 0.26),
        ("expedia", 0.20),
        ("airbnb", 0.10),
        ("agency", 0.08),
    ]

    agencies = [
        ("AG001", "Atlas Travel"),
        ("AG002", "Nova Holidays"),
        ("AG003", "Bluebird Tours"),
        ("AG004", "Lumen Agency"),
    ]

    base_rates = {"Standard": 95.0, "Deluxe": 135.0, "Suite": 210.0}
    range_checkout_end = date_end + timedelta(days=1)

    def choose_weighted(weighted: list[tuple[str, float]]) -> str:
        cut = rng.random()
        cumulative = 0.0
        for name, weight in weighted:
            cumulative += weight
            if cut <= cumulative:
                return name
        return weighted[-1][0]

    def build_row(*, row_number: int, check_in: date, check_out: date) -> dict[str, object]:
        room_type = choose_weighted(room_type_weights)
        source_channel = choose_weighted(channel_weights)
        adults = rng.choices([1, 2, 3, 4], weights=[12, 55, 24, 9], k=1)[0]
        children = rng.choices([0, 1, 2], weights=[67, 24, 9], k=1)[0]

        agency_id = ""
        agency_name = ""
        if source_channel == "agency":
            agency_id, agency_name = agencies[rng.randrange(len(agencies))]

        base = base_rates[room_type]
        seasonal = 1.0 + ((check_in.month - 1) / 100.0)
        rate_jitter = rng.uniform(-0.08, 0.12)
        nightly_rate = round(base * seasonal * (1.0 + rate_jitter), 2)
        nights = max(1, (check_out - check_in).days)
        total_paid = round(nightly_rate * nights, 2)

        lead_days = rng.randrange(1, 65)
        booking_day = check_in - timedelta(days=lead_days)
        booking_hour = rng.randrange(0, 24)
        booking_minute = rng.randrange(0, 60)
        created_at = datetime.combine(booking_day, time(booking_hour, booking_minute), tzinfo=timezone.utc)

        first_name = first_names[rng.randrange(len(first_names))]
        last_name = last_names[rng.randrange(len(last_names))]
        guest_name = f"{first_name} {last_name}"

        return {
            "reservation_id": f"SEED-{row_number:05d}",
            "guest_name": guest_name,
            "check_in": check_in.isoformat(),
            "check_out": check_out.isoformat(),
            "room_type": room_type,
            "adults": adults,
            "children": children,
            "source_channel": source_channel,
            "agency_id": agency_id,
            "agency_name": agency_name,
            "nightly_rate": nightly_rate,
            "total_paid": total_paid,
            "currency": "USD",
            "created_at": created_at.isoformat(timespec="seconds").replace("+00:00", "Z"),
        }

    effective_hot_start = max(hot_start, date_start)
    effective_hot_end = min(hot_end, date_end)
    hot_days = _iter_days(effective_hot_start, effective_hot_end) if effective_hot_start <= effective_hot_end else []

    base_target = int(round(hot_occupancy * ROOM_COUNT))
    base_target = min(total_rows, ROOM_COUNT, max(0, base_target))
    hot_targets = _build_hot_targets(
        hot_days,
        target_rooms=base_target,
        room_count=ROOM_COUNT,
        max_rows=total_rows,
    )
    hot_spans = _spans_from_targets(hot_days, hot_targets)

    rows: list[dict[str, object]] = []
    row_number = 1
    for check_in, check_out in hot_spans:
        if row_number > total_rows:
            break
        rows.append(build_row(row_number=row_number, check_in=check_in, check_out=check_out))
        row_number += 1

    non_hot_ranges: list[tuple[date, date]] = []
    if not hot_days:
        non_hot_ranges = [(date_start, date_end)]
    else:
        pre_end = effective_hot_start - timedelta(days=1)
        post_start = effective_hot_end + timedelta(days=1)
        if date_start <= pre_end:
            non_hot_ranges.append((date_start, pre_end))
        if post_start <= date_end:
            non_hot_ranges.append((post_start, date_end))

    while row_number <= total_rows:
        if non_hot_ranges:
            weights = [((seg_end - seg_start).days + 1) for seg_start, seg_end in non_hot_ranges]
            seg_start, seg_end = rng.choices(non_hot_ranges, weights=weights, k=1)[0]
        else:
            seg_start, seg_end = date_start, date_end

        span_days = (seg_end - seg_start).days + 1
        check_in = seg_start + timedelta(days=rng.randrange(max(1, span_days)))
        nights = rng.choices([1, 2, 3, 4, 5, 6, 7], weights=[14, 25, 21, 16, 12, 7, 5], k=1)[0]
        check_out = check_in + timedelta(days=nights)
        if check_out > range_checkout_end:
            check_out = range_checkout_end

        if hot_days and _overlaps(check_in, check_out, effective_hot_start, effective_hot_end):
            if check_in <= effective_hot_start:
                check_out = effective_hot_start
            if check_out <= check_in:
                check_out = min(check_in + timedelta(days=1), range_checkout_end)

        rows.append(build_row(row_number=row_number, check_in=check_in, check_out=check_out))
        row_number += 1
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed the toy portal database deterministically.")
    parser.add_argument("--db", type=Path, default=None, help="Path to SQLite database file")
    parser.add_argument("--rows", type=int, default=200, help="Number of rows to generate")
    parser.add_argument("--seed", type=int, default=20260301, help="Random seed controlling deterministic output")
    parser.add_argument(
        "--date-start",
        type=_parse_iso_date,
        default=date(2025, 1, 1),
        help="First reservation check-in day (inclusive), format YYYY-MM-DD",
    )
    parser.add_argument(
        "--date-end",
        type=_parse_iso_date,
        default=date(2025, 12, 31),
        help="Last reservation check-in day (inclusive), format YYYY-MM-DD",
    )
    parser.add_argument(
        "--hot-range",
        type=_parse_hot_range,
        default=(date(2025, 6, 19), date(2025, 6, 25)),
        metavar="YYYY-MM-DD:YYYY-MM-DD",
        help="Date window where occupancy should be kept higher",
    )
    parser.add_argument(
        "--hot-occupancy",
        type=float,
        default=0.75,
        help="Target occupancy ratio for hot-range days (0..1)",
    )
    parser.add_argument("--reset", action="store_true", help="Delete existing rows before seeding")
    args = parser.parse_args()

    if args.rows < 0:
        parser.error("--rows must be >= 0")
    if args.date_end < args.date_start:
        parser.error("--date-end must be >= --date-start")
    if not (0.0 <= float(args.hot_occupancy) <= 1.0):
        parser.error("--hot-occupancy must be between 0 and 1")

    hot_start, hot_end = args.hot_range

    repo_root = _repo_root_from_here()
    db_path = (args.db or default_db_path(repo_root)).resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    existing_rows = _count_rows(db_path)
    if existing_rows > 0 and not args.reset:
        print(f"seed_skip=1 rows_existing={existing_rows} db={db_path}")
        return 0

    if args.reset:
        clear_db(db_path)
    else:
        init_db(db_path)

    rows = _build_rows(
        args.rows,
        seed=args.seed,
        date_start=args.date_start,
        date_end=args.date_end,
        hot_start=hot_start,
        hot_end=hot_end,
        hot_occupancy=float(args.hot_occupancy),
    )
    for row in rows:
        insert_reservation(db_path, row)

    print(
        " ".join(
            [
                "seed_ok=1",
                f"rows_inserted={len(rows)}",
                f"db={db_path}",
                f"seed={args.seed}",
                f"date_start={args.date_start.isoformat()}",
                f"date_end={args.date_end.isoformat()}",
                f"hot_range={hot_start.isoformat()}:{hot_end.isoformat()}",
                f"hot_occupancy={float(args.hot_occupancy):.2f}",
            ]
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
