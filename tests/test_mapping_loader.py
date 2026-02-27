import shutil
import json
from pathlib import Path

import pytest

from ai_deney.mapping.loader import load_mapping_bundle, match_agency, match_agency_with_reason, normalize_name


def _repo_tmp_dir(name: str) -> Path:
    repo_root = Path(__file__).resolve().parents[1]
    p = repo_root / "tests" / "_tmp_tasks" / "mapping_loader" / name
    shutil.rmtree(p, ignore_errors=True)
    p.mkdir(parents=True, exist_ok=True)
    return p


def test_mapping_loader_rejects_duplicate_agency_id_mapping() -> None:
    tmp = _repo_tmp_dir("duplicate_id")
    mapping_path = tmp / "mapping_agencies.csv"
    mapping_path.write_text(
        "\n".join(
            [
                "source_system,source_agency_id,source_agency_name,canon_agency_id,canon_agency_name,notes",
                "electra,AG001,Atlas Partners,AG001,Atlas Partners,first",
                "electra,AG001,Atlas Partners,AG001,Atlas Partners,duplicate",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate agency id mapping"):
        load_mapping_bundle(mapping_agencies_path=mapping_path, mapping_channels_path=tmp / "missing.csv")


def test_mapping_loader_rejects_ambiguous_agency_name_mapping() -> None:
    tmp = _repo_tmp_dir("ambiguous_name")
    mapping_path = tmp / "mapping_agencies.csv"
    mapping_path.write_text(
        "\n".join(
            [
                "source_system,source_agency_id,source_agency_name,canon_agency_id,canon_agency_name,notes",
                "hotelrunner,,Atlas Partners,AG001,Atlas Partners,first",
                "hotelrunner,,Atlas-Partners,AG999,Wrong Canon,conflict after normalization",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="ambiguous agency name mapping"):
        load_mapping_bundle(mapping_agencies_path=mapping_path, mapping_channels_path=tmp / "missing.csv")


def test_name_normalization_matching_by_name_when_id_missing() -> None:
    tmp = _repo_tmp_dir("name_matching")
    mapping_path = tmp / "mapping_agencies.csv"
    mapping_path.write_text(
        "\n".join(
            [
                "source_system,source_agency_id,source_agency_name,canon_agency_id,canon_agency_name,notes",
                "hotelrunner,,Atlas-Partners!!,AG001,Atlas Partners,name only",
                "electra,AG001,Atlas Partners,AG001,Atlas Partners,id mapping",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    bundle = load_mapping_bundle(mapping_agencies_path=mapping_path, mapping_channels_path=tmp / "missing.csv")

    assert normalize_name("  Atlas-Partners!! ") == "atlas partners"
    assert match_agency(bundle, "hotelrunner", "", "Atlas   Partners") == ("AG001", "Atlas Partners")
    assert match_agency(bundle, "hotelrunner", "UNKNOWN", "Atlas Partners") is None


def test_mapping_rules_are_applied_after_csv_matches() -> None:
    tmp = _repo_tmp_dir("csv_beats_rules")
    mapping_path = tmp / "mapping_agencies.csv"
    rules_path = tmp / "mapping_rules.json"
    mapping_path.write_text(
        "\n".join(
            [
                "source_system,source_agency_id,source_agency_name,canon_agency_id,canon_agency_name,notes",
                "hotelrunner,,Direct Channel,AG999,Custom Direct,csv should win",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    rules_path.write_text(
        json.dumps(
            {
                "agency_rules": [
                    {
                        "source_system": "hotelrunner",
                        "field": "agency_name",
                        "op": "contains",
                        "value": "direct",
                        "canon_agency_id": "DIRECT",
                        "canon_agency_name": "Direct Channel",
                        "reason": "rule:contains:direct",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    bundle = load_mapping_bundle(
        mapping_agencies_path=mapping_path,
        mapping_channels_path=tmp / "missing.csv",
        mapping_rules_path=rules_path,
    )
    decision = match_agency_with_reason(
        bundle,
        source_system="hotelrunner",
        source_agency_id="",
        source_agency_name="Direct Channel",
        source_channel="Direct",
    )

    assert decision == ("AG999", "Custom Direct", "csv_match:name")
