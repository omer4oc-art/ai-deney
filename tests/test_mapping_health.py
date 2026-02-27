import shutil
from pathlib import Path

from ai_deney.mapping.health import drift_report, find_collisions, find_unmapped
from ai_deney.mapping.loader import load_mapping_bundle


def _repo_tmp_dir(name: str) -> Path:
    repo_root = Path(__file__).resolve().parents[1]
    p = repo_root / "tests" / "_tmp_tasks" / "mapping_health" / name
    shutil.rmtree(p, ignore_errors=True)
    p.mkdir(parents=True, exist_ok=True)
    return p


def test_find_unmapped_returns_unique_agencies_and_channels() -> None:
    rows = [
        {
            "year": 2026,
            "agency_id": "AG001",
            "agency_name": "Atlas Partners",
            "channel": "Booking.com",
            "canon_agency_id": "AG001",
            "canon_agency_name": "Atlas Partners",
            "canon_channel": "OTA",
        },
        {
            "year": 2026,
            "agency_id": "AGNEW",
            "agency_name": "Nova Ventures",
            "channel": "Nova Channel",
            "canon_agency_id": "",
            "canon_agency_name": "",
            "canon_channel": "",
        },
        {
            "year": 2026,
            "agency_id": "AGNEW",
            "agency_name": "Nova Ventures",
            "channel": "Nova Channel",
            "canon_agency_id": "",
            "canon_agency_name": "",
            "canon_channel": "",
        },
        {
            "year": 2026,
            "agency_id": "TOTAL",
            "agency_name": "Overall Total",
            "canon_agency_id": "",
            "canon_agency_name": "",
            "canon_channel": "",
        },
    ]

    unmapped = find_unmapped(rows, "hotelrunner")
    assert len(unmapped) == 2
    assert any(r["item_type"] == "agency" and r["source_agency_id"] == "AGNEW" for r in unmapped)
    assert any(r["item_type"] == "channel" and r["source_channel"] == "Nova Channel" for r in unmapped)


def test_find_collisions_detects_many_sources_to_one_canon() -> None:
    tmp = _repo_tmp_dir("collision")
    mapping_path = tmp / "mapping_agencies.csv"
    mapping_path.write_text(
        "\n".join(
            [
                "source_system,source_agency_id,source_agency_name,canon_agency_id,canon_agency_name,notes",
                "electra,AG001,Atlas Partners,AG001,Atlas Partners,base",
                "electra,AGX01,Atlas Affiliate,AG001,Atlas Partners,intentional collision",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    bundle = load_mapping_bundle(mapping_agencies_path=mapping_path, mapping_channels_path=tmp / "missing.csv")
    collisions = find_collisions(bundle)

    assert any(
        r["mapping_type"] == "agency"
        and r["collision_type"] == "many_sources_to_one_canon"
        and r["canon_value"] == "AG001"
        for r in collisions
    )


def test_drift_report_flags_system_specific_canonical_agencies() -> None:
    electra_rows = [
        {"year": 2025, "canon_agency_id": "AG001", "canon_agency_name": "Atlas Partners"},
        {"year": 2025, "canon_agency_id": "AG002", "canon_agency_name": "Beacon Agency"},
    ]
    hr_rows = [
        {"year": 2025, "canon_agency_id": "AG001", "canon_agency_name": "Atlas Partners"},
        {"year": 2025, "canon_agency_id": "AG003", "canon_agency_name": "Cedar Travel"},
    ]
    drift = drift_report(electra_rows, hr_rows)
    assert drift == [
        {
            "presence": "electra_only",
            "canon_agency_id": "AG002",
            "canon_agency_name": "Beacon Agency",
            "years": "2025",
        },
        {
            "presence": "hotelrunner_only",
            "canon_agency_id": "AG003",
            "canon_agency_name": "Cedar Travel",
            "years": "2025",
        },
    ]
