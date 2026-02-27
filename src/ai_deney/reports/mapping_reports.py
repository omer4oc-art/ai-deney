"""Mapping health report executors and deterministic markdown/html rendering."""

from __future__ import annotations

import csv
from html import escape
from pathlib import Path

from ai_deney.intent.query_spec import QuerySpec
from ai_deney.mapping.health import (
    drift_report,
    find_collisions,
    find_unmapped,
    sample_mapped_rows,
    suggest_unmapped_candidates,
)
from ai_deney.mapping.loader import MappingBundle, enrich_rows, load_mapping_bundle
from ai_deney.mapping.metrics import unknown_rate_improvement_by_year
from ai_deney.reports.reconcile_reports import ensure_normalized_data
from ai_deney.reports.registry import ReportRegistry

_DETERMINISTIC_SOURCE_FOOTER = (
    "Source: Electra + HotelRunner mock fixtures + mapping config; Generated: deterministic run."
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _default_normalized_root() -> Path:
    return _repo_root() / "data" / "normalized"


def _read_electra_rows(years: list[int], normalized_root: Path) -> list[dict]:
    rows: list[dict] = []
    for year in sorted(set(int(y) for y in years)):
        path = normalized_root / f"electra_sales_{year}.csv"
        with path.open("r", encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                rows.append(
                    {
                        "date": str(row.get("date") or "").strip(),
                        "year": int(row.get("year") or year),
                        "agency_id": str(row.get("agency_id") or "").strip(),
                        "agency_name": str(row.get("agency_name") or "").strip(),
                        "gross_sales": float(row.get("gross_sales") or 0.0),
                    }
                )
    return rows


def _read_hotelrunner_rows(years: list[int], normalized_root: Path) -> list[dict]:
    rows: list[dict] = []
    for year in sorted(set(int(y) for y in years)):
        path = normalized_root / f"hotelrunner_sales_{year}.csv"
        with path.open("r", encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                rows.append(
                    {
                        "date": str(row.get("date") or "").strip(),
                        "year": int(row.get("year") or year),
                        "agency_id": str(row.get("agency_id") or "").strip(),
                        "agency_name": str(row.get("agency_name") or "").strip(),
                        "channel": str(row.get("channel") or row.get("agency") or "").strip(),
                        "gross_sales": float(row.get("gross_sales") or 0.0),
                    }
                )
    return rows


def _enriched_rows(
    years: list[int],
    normalized_root: Path,
    mapping_agencies_path: Path | None = None,
    mapping_channels_path: Path | None = None,
    mapping_rules_path: Path | None = None,
) -> tuple[list[dict], list[dict], list[dict], MappingBundle]:
    mapping = load_mapping_bundle(
        mapping_agencies_path=mapping_agencies_path,
        mapping_channels_path=mapping_channels_path,
        mapping_rules_path=mapping_rules_path,
    )
    electra_rows = enrich_rows(_read_electra_rows(years, normalized_root), source_system="electra", mapping=mapping)
    hr_rows = enrich_rows(_read_hotelrunner_rows(years, normalized_root), source_system="hotelrunner", mapping=mapping)
    for row in electra_rows:
        row["system"] = "electra"
    for row in hr_rows:
        row["system"] = "hotelrunner"
    collisions = find_collisions(mapping)
    return electra_rows, hr_rows, collisions, mapping


def run_mapping_health_agency(
    years: list[int],
    normalized_root: Path | None = None,
    mapping_agencies_path: Path | None = None,
    mapping_channels_path: Path | None = None,
    mapping_rules_path: Path | None = None,
) -> dict:
    normalized = (normalized_root or _default_normalized_root()).resolve()
    electra_rows, hr_rows, collisions, mapping = _enriched_rows(
        years,
        normalized_root=normalized,
        mapping_agencies_path=mapping_agencies_path,
        mapping_channels_path=mapping_channels_path,
        mapping_rules_path=mapping_rules_path,
    )

    unmapped = [
        r
        for r in (find_unmapped(electra_rows, "electra") + find_unmapped(hr_rows, "hotelrunner"))
        if str(r.get("item_type")) == "agency"
    ]
    unmapped.sort(
        key=lambda r: (
            str(r.get("system", "")),
            str(r.get("source_agency_id", "")),
            str(r.get("source_agency_name", "")),
        )
    )

    agency_collisions = [r for r in collisions if str(r.get("mapping_type")) == "agency"]
    drift = drift_report(electra_rows, hr_rows)
    mapped_sample = sample_mapped_rows(electra_rows + hr_rows, limit=20)
    unmapped_suggestions = suggest_unmapped_candidates(unmapped, mapping=mapping, max_candidates=3)
    return {
        "sample_mapped": mapped_sample,
        "unmapped_suggestions": unmapped_suggestions,
        "unmapped": unmapped,
        "collisions": agency_collisions,
        "drift": drift,
    }


def run_mapping_health_channel(
    years: list[int],
    normalized_root: Path | None = None,
    mapping_agencies_path: Path | None = None,
    mapping_channels_path: Path | None = None,
    mapping_rules_path: Path | None = None,
) -> dict:
    normalized = (normalized_root or _default_normalized_root()).resolve()
    electra_rows, hr_rows, collisions, _ = _enriched_rows(
        years,
        normalized_root=normalized,
        mapping_agencies_path=mapping_agencies_path,
        mapping_channels_path=mapping_channels_path,
        mapping_rules_path=mapping_rules_path,
    )
    unmapped = [
        r
        for r in (find_unmapped(electra_rows, "electra") + find_unmapped(hr_rows, "hotelrunner"))
        if str(r.get("item_type")) == "channel"
    ]
    unmapped.sort(
        key=lambda r: (
            str(r.get("system", "")),
            str(r.get("source_channel", "")),
        )
    )
    channel_collisions = [r for r in collisions if str(r.get("mapping_type")) == "channel"]
    return {
        "sample_mapped": [],
        "unmapped_suggestions": [],
        "unmapped": unmapped,
        "collisions": channel_collisions,
        "drift": [],
    }


def run_mapping_explain_agency(
    years: list[int],
    normalized_root: Path | None = None,
    mapping_agencies_path: Path | None = None,
    mapping_channels_path: Path | None = None,
    mapping_rules_path: Path | None = None,
) -> dict:
    normalized = (normalized_root or _default_normalized_root()).resolve()
    electra_rows, hr_rows, _collisions, mapping = _enriched_rows(
        years,
        normalized_root=normalized,
        mapping_agencies_path=mapping_agencies_path,
        mapping_channels_path=mapping_channels_path,
        mapping_rules_path=mapping_rules_path,
    )
    unmapped = [
        r
        for r in (find_unmapped(electra_rows, "electra") + find_unmapped(hr_rows, "hotelrunner"))
        if str(r.get("item_type")) == "agency"
    ]
    mapped_sample = sample_mapped_rows(electra_rows + hr_rows, limit=25)
    unmapped_suggestions = suggest_unmapped_candidates(unmapped, mapping=mapping, max_candidates=3)
    return {
        "sample_mapped": mapped_sample,
        "unmapped_suggestions": unmapped_suggestions,
    }


def run_unknown_rate_improvement(
    years: list[int],
    normalized_root: Path | None = None,
    mapping_agencies_path: Path | None = None,
    mapping_channels_path: Path | None = None,
    mapping_rules_path: Path | None = None,
) -> dict:
    normalized = (normalized_root or _default_normalized_root()).resolve()
    rows = unknown_rate_improvement_by_year(
        years=years,
        normalized_root=normalized,
        granularity="monthly",
        mapping_agencies_path=mapping_agencies_path,
        mapping_channels_path=mapping_channels_path,
        mapping_rules_path=mapping_rules_path,
    )
    return {"improvement": rows}


def _format_value(value) -> str:
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def _render_table_markdown(rows: list[dict]) -> list[str]:
    if not rows:
        return ["_No rows_"]
    cols = list(rows[0].keys())
    out = ["| " + " | ".join(cols) + " |", "| " + " | ".join(["---"] * len(cols)) + " |"]
    for row in rows:
        out.append("| " + " | ".join(_format_value(row.get(c, "")) for c in cols) + " |")
    return out


def _render_table_html(rows: list[dict]) -> list[str]:
    if not rows:
        return ["<p><em>No rows</em></p>"]
    cols = list(rows[0].keys())
    out = [
        "<table>",
        "<thead><tr>" + "".join(f"<th>{escape(str(c))}</th>" for c in cols) + "</tr></thead>",
        "<tbody>",
    ]
    for row in rows:
        out.append("<tr>" + "".join(f"<td>{escape(_format_value(row.get(c, '')))}</td>" for c in cols) + "</tr>")
    out.extend(["</tbody>", "</table>"])
    return out


def render_markdown(report: dict, title: str, notes: str, sections: list[str]) -> str:
    lines = [f"# {title}", "", notes, ""]
    section_titles = {
        "sample_mapped": "Mapped Decisions Sample",
        "unmapped_suggestions": "Unmapped Suggestions",
        "unmapped": "Unmapped",
        "collisions": "Collisions",
        "drift": "Drift",
        "improvement": "Unknown Rate Improvement",
    }
    for key in sections:
        lines.append(f"## {section_titles[key]}")
        lines.extend(_render_table_markdown(list(report.get(key) or [])))
        lines.append("")
    lines.append(f"Data freshness / source: {_DETERMINISTIC_SOURCE_FOOTER}")
    lines.append("")
    return "\n".join(lines)


def render_html(report: dict, title: str, notes: str, sections: list[str]) -> str:
    lines = [
        "<!doctype html>",
        "<html>",
        "<head>",
        "<meta charset=\"utf-8\">",
        f"<title>{escape(title)}</title>",
        "<style>",
        "body { font-family: sans-serif; margin: 24px; }",
        "table { border-collapse: collapse; width: 100%; }",
        "th, td { border: 1px solid #ddd; padding: 6px 8px; text-align: left; }",
        "th { background: #f5f5f5; }",
        "</style>",
        "</head>",
        "<body>",
        f"<h1>{escape(title)}</h1>",
        f"<p>{escape(notes)}</p>",
    ]
    section_titles = {
        "sample_mapped": "Mapped Decisions Sample",
        "unmapped_suggestions": "Unmapped Suggestions",
        "unmapped": "Unmapped",
        "collisions": "Collisions",
        "drift": "Drift",
        "improvement": "Unknown Rate Improvement",
    }
    for key in sections:
        lines.append(f"<h2>{escape(section_titles[key])}</h2>")
        lines.extend(_render_table_html(list(report.get(key) or [])))
    lines.extend(
        [
            f"<p>Data freshness / source: {escape(_DETERMINISTIC_SOURCE_FOOTER)}</p>",
            "</body>",
            "</html>",
            "",
        ]
    )
    return "\n".join(lines)


def _build_registry(
    normalized_root: Path | None = None,
    mapping_agencies_path: Path | None = None,
    mapping_channels_path: Path | None = None,
    mapping_rules_path: Path | None = None,
) -> ReportRegistry:
    registry = ReportRegistry()
    registry.register(
        "mapping.health_agency",
        lambda years: run_mapping_health_agency(
            years,
            normalized_root=normalized_root,
            mapping_agencies_path=mapping_agencies_path,
            mapping_channels_path=mapping_channels_path,
            mapping_rules_path=mapping_rules_path,
        ),
    )
    registry.register(
        "mapping.health_channel",
        lambda years: run_mapping_health_channel(
            years,
            normalized_root=normalized_root,
            mapping_agencies_path=mapping_agencies_path,
            mapping_channels_path=mapping_channels_path,
            mapping_rules_path=mapping_rules_path,
        ),
    )
    registry.register(
        "mapping.explain_agency",
        lambda years: run_mapping_explain_agency(
            years,
            normalized_root=normalized_root,
            mapping_agencies_path=mapping_agencies_path,
            mapping_channels_path=mapping_channels_path,
            mapping_rules_path=mapping_rules_path,
        ),
    )
    registry.register(
        "mapping.unknown_rate_improvement",
        lambda years: run_unknown_rate_improvement(
            years,
            normalized_root=normalized_root,
            mapping_agencies_path=mapping_agencies_path,
            mapping_channels_path=mapping_channels_path,
            mapping_rules_path=mapping_rules_path,
        ),
    )
    return registry


def answer_from_spec(spec: QuerySpec, normalized_root: Path | None = None, output_format: str = "markdown") -> str:
    if spec.source != "mapping":
        raise ValueError("spec is not a mapping-health query")

    ensure_normalized_data(spec.years, normalized_root=normalized_root)
    registry = _build_registry(normalized_root=normalized_root)
    report = registry.get(spec.registry_key)(spec.years)
    years_label = ", ".join(str(y) for y in spec.years)

    if spec.analysis == "mapping_health_channel":
        title = f"Mapping Health by Channel ({years_label})"
        notes = f"Canonical channel mapping health for years: {years_label}."
        sections = ["unmapped", "collisions"]
    elif spec.analysis == "mapping_explain_agency":
        title = f"Mapping Explainability by Agency ({years_label})"
        notes = (
            f"Deterministic mapping decisions and unmapped candidate suggestions for years: {years_label}. "
            "Rules are applied only after explicit CSV matches."
        )
        sections = ["sample_mapped", "unmapped_suggestions"]
    elif spec.analysis == "mapping_unknown_rate_improvement":
        title = f"Unknown Rate Improvement by Mapping ({years_label})"
        notes = (
            f"UNKNOWN share comparison for monthly reconcile-by-agency in years: {years_label}. "
            "Baseline uses raw source-native dim values; mapped uses canonical mapping v2."
        )
        sections = ["improvement"]
    elif spec.analysis == "mapping_unmapped_agency":
        title = f"Unmapped Agencies ({years_label})"
        notes = f"Agencies missing canonical mappings for years: {years_label}."
        sections = ["unmapped", "unmapped_suggestions"]
    elif spec.analysis == "mapping_drift_agency":
        title = f"Agency Drift Electra vs HotelRunner ({years_label})"
        notes = f"Canonical agency drift for years: {years_label}."
        sections = ["drift"]
    else:
        title = f"Mapping Health by Agency ({years_label})"
        notes = f"Canonical agency mapping health for years: {years_label}. Includes mapping explainability samples."
        sections = ["sample_mapped", "unmapped_suggestions", "unmapped", "collisions", "drift"]

    if output_format == "markdown":
        return render_markdown(report=report, title=title, notes=notes, sections=sections)
    if output_format == "html":
        return render_html(report=report, title=title, notes=notes, sections=sections)
    raise ValueError(f"unsupported output_format: {output_format}")
