#!/usr/bin/env python3
"""Generate deterministic Electra CSV fixtures with multi-date realism."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Agency:
    agency_id: str
    agency_name: str
    base_gross_cents: int


AGENCIES = [
    Agency("AG001", "Atlas Partners", 12000),
    Agency("AG002", "Beacon Agency", 11100),
    Agency("AG003", "Cedar Travel", 9800),
    Agency("AG004", "Drift Voyages", 8700),
    Agency("AG005", "Elm Holidays", 7600),
    Agency("DIRECT", "Direct Channel", 10300),
]

DAY_SLOTS = [1, 7, 13, 19, 25]  # 5 dates per month * 6 months => 30 days/year
MONTHS = [1, 2, 3, 4, 5, 6]
YEARS = [2025, 2026]

# At least two cancellation/refund-like events per year.
REFUND_EVENTS = {
    2025: [
        ("2025-02-19", "AG002", -2500, "refund_adjustment"),
        ("2025-05-07", "DIRECT", -4100, "cancellation_adjustment"),
    ],
    2026: [
        ("2026-02-19", "AG003", -2800, "refund_adjustment"),
        ("2026-05-07", "DIRECT", -4600, "cancellation_adjustment"),
    ],
}


def _fmt(cents: int) -> str:
    return f"{cents / 100.0:.2f}"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _default_out_root() -> Path:
    return _repo_root() / "fixtures" / "electra"


def _day_rows_for_year(year: int) -> tuple[list[dict], list[dict]]:
    by_agency_rows: list[dict] = []
    summary_rows: list[dict] = []
    refunds = {(d, aid): cents for d, aid, cents, _ in REFUND_EVENTS.get(year, [])}
    refund_notes = {(d, aid): note for d, aid, _, note in REFUND_EVENTS.get(year, [])}

    for month in MONTHS:
        for day_index, day in enumerate(DAY_SLOTS):
            date = f"{year}-{month:02d}-{day:02d}"
            day_gross_cents = 0
            day_net_cents = 0
            for agency_index, agency in enumerate(AGENCIES):
                gross_cents = (
                    agency.base_gross_cents
                    + (year - 2025) * 1250
                    + month * 95
                    + day_index * 37
                    + agency_index * 29
                )
                net_cents = gross_cents - round(gross_cents * 0.09)
                day_gross_cents += gross_cents
                day_net_cents += net_cents
                by_agency_rows.append(
                    {
                        "date": date,
                        "agency_id": agency.agency_id,
                        "agency_name": agency.agency_name,
                        "gross_sales": _fmt(gross_cents),
                        "net_sales": _fmt(net_cents),
                        "currency": "USD",
                        "note": "",
                    }
                )
                refund_key = (date, agency.agency_id)
                if refund_key in refunds:
                    refund_cents = refunds[refund_key]
                    day_net_cents += refund_cents
                    by_agency_rows.append(
                        {
                            "date": date,
                            "agency_id": agency.agency_id,
                            "agency_name": agency.agency_name,
                            "gross_sales": _fmt(0),
                            "net_sales": _fmt(refund_cents),
                            "currency": "USD",
                            "note": refund_notes[refund_key],
                        }
                    )

            summary_rows.append(
                {
                    "date": date,
                    "gross_sales": _fmt(day_gross_cents),
                    "net_sales": _fmt(day_net_cents),
                    "currency": "USD",
                    "note": "includes_adjustments" if any(k[0] == date for k in refunds) else "",
                }
            )
    return summary_rows, by_agency_rows


def generate(out_root: Path) -> list[Path]:
    out_root.mkdir(parents=True, exist_ok=True)
    out_paths: list[Path] = []
    for year in YEARS:
        summary_rows, by_agency_rows = _day_rows_for_year(year)
        summary_path = out_root / f"sales_summary_{year}.csv"
        agency_path = out_root / f"sales_by_agency_{year}.csv"

        with summary_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["date", "gross_sales", "net_sales", "currency", "note"])
            writer.writeheader()
            writer.writerows(summary_rows)
        with agency_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["date", "agency_id", "agency_name", "gross_sales", "net_sales", "currency", "note"],
            )
            writer.writeheader()
            writer.writerows(by_agency_rows)

        out_paths.extend([summary_path, agency_path])
    return out_paths


def main() -> int:
    out_root = _default_out_root()
    paths = generate(out_root)
    for path in paths:
        print(f"WROTE: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
