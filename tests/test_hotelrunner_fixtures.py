import csv
from pathlib import Path


def _read_csv(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def test_hotelrunner_fixtures_have_required_shape() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    fixture_root = repo_root / "fixtures" / "hotelrunner"
    for year in (2025, 2026):
        rows = _read_csv(fixture_root / f"daily_sales_{year}.csv")
        assert len(rows) >= 30
        assert {
            "date",
            "booking_id",
            "agency_id",
            "agency_name",
            "channel",
            "gross_sales",
            "net_sales",
            "currency",
        } <= set(rows[0].keys())
        assert all(float(r["gross_sales"]) >= 0 for r in rows)


def test_hotelrunner_fixtures_include_discrepancies_vs_electra() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    electra_root = repo_root / "fixtures" / "electra"
    hr_root = repo_root / "fixtures" / "hotelrunner"
    for year in (2025, 2026):
        e_rows = _read_csv(electra_root / f"sales_summary_{year}.csv")
        h_rows = _read_csv(hr_root / f"daily_sales_{year}.csv")
        e = {r["date"]: round(float(r["gross_sales"]), 2) for r in e_rows}
        h: dict[str, float] = {}
        for row in h_rows:
            h[row["date"]] = round(h.get(row["date"], 0.0) + float(row["gross_sales"]), 2)
        deltas = [round(e[d] - h[d], 2) for d in sorted(set(e) & set(h))]
        assert any(0 < abs(d) <= 1 for d in deltas)
        assert any(abs(d) >= 50 for d in deltas)


def test_hotelrunner_fixtures_include_new_agency_event() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    hr_root = repo_root / "fixtures" / "hotelrunner"
    rows_2026 = _read_csv(hr_root / "daily_sales_2026.csv")
    assert any(r["agency_id"] == "AGNEW" for r in rows_2026)
