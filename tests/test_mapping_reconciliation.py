import csv
import shutil
from pathlib import Path

from ai_deney.reconcile.electra_vs_hotelrunner import reconcile_by_dim_daily


def _repo_tmp_dir(name: str) -> Path:
    repo_root = Path(__file__).resolve().parents[1]
    p = repo_root / "tests" / "_tmp_tasks" / "mapping_reconcile" / name
    shutil.rmtree(p, ignore_errors=True)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_minimal_normalized_fixture(normalized_root: Path) -> None:
    _write_csv(
        normalized_root / "electra_sales_2060.csv",
        ["date", "year", "agency_id", "agency_name", "gross_sales", "net_sales", "currency"],
        [
            {
                "date": "2060-01-01",
                "year": 2060,
                "agency_id": "AG001",
                "agency_name": "Atlas Partners",
                "gross_sales": "100.00",
                "net_sales": "91.00",
                "currency": "USD",
            }
        ],
    )
    _write_csv(
        normalized_root / "hotelrunner_sales_2060.csv",
        [
            "date",
            "year",
            "booking_id",
            "agency_id",
            "agency_name",
            "channel",
            "gross_sales",
            "net_sales",
            "currency",
        ],
        [
            {
                "date": "2060-01-01",
                "year": 2060,
                "booking_id": "HR20600001",
                "agency_id": "",
                "agency_name": "Atlas Partners",
                "channel": "Booking.com",
                "gross_sales": "100.00",
                "net_sales": "91.00",
                "currency": "USD",
            }
        ],
    )


def test_reconcile_by_agency_uses_canonical_mapping_and_reduces_unknown(tmp_path: Path) -> None:
    normalized_root = tmp_path / "normalized"
    _write_minimal_normalized_fixture(normalized_root)

    mapping_root = _repo_tmp_dir("canonical_reduction")
    baseline_mapping = mapping_root / "baseline_mapping_agencies.csv"
    mapped_mapping = mapping_root / "mapped_mapping_agencies.csv"

    baseline_mapping.write_text(
        "\n".join(
            [
                "source_system,source_agency_id,source_agency_name,canon_agency_id,canon_agency_name,notes",
                "electra,AG001,Atlas Partners,AG001,Atlas Partners,baseline electra mapping",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    mapped_mapping.write_text(
        "\n".join(
            [
                "source_system,source_agency_id,source_agency_name,canon_agency_id,canon_agency_name,notes",
                "electra,AG001,Atlas Partners,AG001,Atlas Partners,electra mapping",
                "hotelrunner,,Atlas Partners,AG001,Atlas Partners,name-based hr mapping",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    baseline_rows = reconcile_by_dim_daily(
        [2060],
        dim="agency",
        normalized_root_electra=normalized_root,
        normalized_root_hr=normalized_root,
        mapping_agencies_path=baseline_mapping,
        mapping_channels_path=mapping_root / "missing_channels.csv",
    ).to_dict("records")
    mapped_rows = reconcile_by_dim_daily(
        [2060],
        dim="agency",
        normalized_root_electra=normalized_root,
        normalized_root_hr=normalized_root,
        mapping_agencies_path=mapped_mapping,
        mapping_channels_path=mapping_root / "missing_channels.csv",
    ).to_dict("records")

    baseline_unknown = sum(1 for row in baseline_rows if row["reason_code"] == "UNKNOWN")
    mapped_unknown = sum(1 for row in mapped_rows if row["reason_code"] == "UNKNOWN")

    assert baseline_unknown > mapped_unknown
    assert mapped_unknown == 0
    assert any(row["dim_value"] == "AG001" and row["status"] == "MATCH" for row in mapped_rows)
