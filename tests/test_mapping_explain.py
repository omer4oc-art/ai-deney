import csv
import json
import shutil
from pathlib import Path

from ai_deney.reports.mapping_reports import run_mapping_explain_agency


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _repo_tmp_dir(name: str) -> Path:
    repo_root = Path(__file__).resolve().parents[1]
    p = repo_root / "tests" / "_tmp_tasks" / "mapping_explain" / name
    shutil.rmtree(p, ignore_errors=True)
    p.mkdir(parents=True, exist_ok=True)
    return p


def test_mapping_explain_report_populates_mapped_by_reasons() -> None:
    tmp = _repo_tmp_dir("mapped_by")
    normalized_root = tmp / "normalized"
    _write_csv(
        normalized_root / "electra_sales_2070.csv",
        ["date", "year", "agency_id", "agency_name", "gross_sales", "net_sales", "currency"],
        [
            {
                "date": "2070-01-01",
                "year": 2070,
                "agency_id": "AG001",
                "agency_name": "Atlas Partners",
                "gross_sales": "100.00",
                "net_sales": "91.00",
                "currency": "USD",
            }
        ],
    )
    _write_csv(
        normalized_root / "hotelrunner_sales_2070.csv",
        ["date", "year", "booking_id", "agency_id", "agency_name", "channel", "gross_sales", "net_sales", "currency"],
        [
            {
                "date": "2070-01-01",
                "year": 2070,
                "booking_id": "HR20700001",
                "agency_id": "",
                "agency_name": "Direct Channel",
                "channel": "Direct",
                "gross_sales": "100.00",
                "net_sales": "91.00",
                "currency": "USD",
            }
        ],
    )

    mapping_path = tmp / "mapping_agencies.csv"
    mapping_path.write_text(
        "\n".join(
            [
                "source_system,source_agency_id,source_agency_name,canon_agency_id,canon_agency_name,notes",
                "electra,AG001,Atlas Partners,AG001,Atlas Partners,electra mapping",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    rules_path = tmp / "mapping_rules.json"
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

    report = run_mapping_explain_agency(
        years=[2070],
        normalized_root=normalized_root,
        mapping_agencies_path=mapping_path,
        mapping_channels_path=tmp / "missing_channels.csv",
        mapping_rules_path=rules_path,
    )

    sample = list(report["sample_mapped"])
    assert sample
    assert all(str(row.get("mapped_by") or "").strip() for row in sample)
    assert any(str(row.get("mapped_by", "")).startswith("rule:") for row in sample)
