import csv
from pathlib import Path


def _read_csv(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def test_electra_fixtures_have_realistic_size_and_channels() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    fixture_root = repo_root / "fixtures" / "electra"
    for year in (2025, 2026):
        summary_rows = _read_csv(fixture_root / f"sales_summary_{year}.csv")
        agency_rows = _read_csv(fixture_root / f"sales_by_agency_{year}.csv")

        unique_dates = {r["date"] for r in summary_rows}
        assert len(unique_dates) >= 30
        assert len(summary_rows) >= 30
        assert len(agency_rows) >= 180
        assert {r["agency_id"] for r in agency_rows} >= {"AG001", "AG002", "AG003", "AG004", "AG005", "DIRECT"}


def test_electra_fixtures_include_refund_like_net_events() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    fixture_root = repo_root / "fixtures" / "electra"
    all_rows = []
    for year in (2025, 2026):
        all_rows.extend(_read_csv(fixture_root / f"sales_by_agency_{year}.csv"))
    negative_net_rows = [r for r in all_rows if float(r["net_sales"]) < 0]
    assert len(negative_net_rows) >= 4


def test_summary_totals_match_agency_totals_per_year() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    fixture_root = repo_root / "fixtures" / "electra"
    for year in (2025, 2026):
        summary_rows = _read_csv(fixture_root / f"sales_summary_{year}.csv")
        agency_rows = _read_csv(fixture_root / f"sales_by_agency_{year}.csv")
        summary_gross = round(sum(float(r["gross_sales"]) for r in summary_rows), 2)
        agency_gross = round(sum(float(r["gross_sales"]) for r in agency_rows), 2)
        assert summary_gross == agency_gross
