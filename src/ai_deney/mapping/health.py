"""Deterministic diagnostics for canonical mapping health."""

from __future__ import annotations

from collections import defaultdict

from ai_deney.mapping.loader import MappingBundle, normalize_name


def _sorted_years(years: set[int]) -> str:
    return ",".join(str(y) for y in sorted(years))


def find_unmapped(rows: list[dict], system: str) -> list[dict]:
    """Return unique unmapped agencies/channels for a source system."""
    source_system = str(system or "").strip().lower()
    unmapped: dict[tuple[str, str, str], dict] = {}

    for row in rows:
        year = int(row.get("year", 0) or 0)
        source_agency_id = str(row.get("agency_id") or "").strip()
        source_agency_name = str(row.get("agency_name") or row.get("agency") or "").strip()
        source_channel = str(row.get("channel") or "").strip()
        canon_agency_id = str(row.get("canon_agency_id") or "").strip()
        canon_agency_name = str(row.get("canon_agency_name") or "").strip()
        canon_channel = str(row.get("canon_channel") or "").strip()

        if source_agency_id == "TOTAL":
            continue

        if (source_agency_id or source_agency_name) and (not canon_agency_id and not canon_agency_name):
            agency_key = ("agency", source_agency_id, normalize_name(source_agency_name))
            item = unmapped.setdefault(
                agency_key,
                {
                    "system": source_system,
                    "item_type": "agency",
                    "source_agency_id": source_agency_id,
                    "source_agency_name": source_agency_name,
                    "source_channel": "",
                    "occurrences": 0,
                    "years": set(),
                },
            )
            item["occurrences"] += 1
            item["years"].add(year)

        if source_channel and not canon_channel:
            channel_key = ("channel", "", normalize_name(source_channel))
            item = unmapped.setdefault(
                channel_key,
                {
                    "system": source_system,
                    "item_type": "channel",
                    "source_agency_id": "",
                    "source_agency_name": "",
                    "source_channel": source_channel,
                    "occurrences": 0,
                    "years": set(),
                },
            )
            item["occurrences"] += 1
            item["years"].add(year)

    out: list[dict] = []
    for item in unmapped.values():
        out.append(
            {
                "system": item["system"],
                "item_type": item["item_type"],
                "source_agency_id": item["source_agency_id"],
                "source_agency_name": item["source_agency_name"],
                "source_channel": item["source_channel"],
                "occurrences": int(item["occurrences"]),
                "years": _sorted_years(set(item["years"])),
            }
        )

    out.sort(
        key=lambda r: (
            str(r["system"]),
            str(r["item_type"]),
            str(r["source_agency_id"]),
            str(r["source_agency_name"]),
            str(r["source_channel"]),
        )
    )
    return out


def _find_agency_collisions(mapping: MappingBundle) -> list[dict]:
    collisions: list[dict] = []

    by_source: dict[tuple[str, str, str], set[tuple[str, str]]] = defaultdict(set)
    for entry in mapping.agency_entries:
        canon = (entry.canon_agency_id, entry.canon_agency_name)
        if entry.source_agency_id:
            by_source[("agency", entry.source_system, f"id:{entry.source_agency_id}")].add(canon)
        if entry.source_agency_name_norm:
            by_source[("agency", entry.source_system, f"name:{entry.source_agency_name_norm}")].add(canon)

    for key in sorted(by_source.keys()):
        canon_targets = by_source[key]
        if len(canon_targets) > 1:
            kind, source_system, source_value = key
            canon_text = "; ".join(sorted(f"{cid}/{cname}" for cid, cname in canon_targets))
            collisions.append(
                {
                    "mapping_type": kind,
                    "collision_type": "source_to_multiple_canon",
                    "source_system": source_system,
                    "source_value": source_value,
                    "canon_value": canon_text,
                }
            )

    by_canon: dict[tuple[str, str], set[str]] = defaultdict(set)
    for entry in mapping.agency_entries:
        canon_key = (entry.source_system, entry.canon_agency_id or entry.canon_agency_name)
        source_value = entry.source_agency_id or entry.source_agency_name_norm
        by_canon[canon_key].add(source_value)

    for (source_system, canon_value), source_values in sorted(by_canon.items()):
        if len(source_values) > 1:
            collisions.append(
                {
                    "mapping_type": "agency",
                    "collision_type": "many_sources_to_one_canon",
                    "source_system": source_system,
                    "source_value": "; ".join(sorted(source_values)),
                    "canon_value": canon_value,
                }
            )

    return collisions


def _find_channel_collisions(mapping: MappingBundle) -> list[dict]:
    collisions: list[dict] = []

    by_canon: dict[tuple[str, str], set[str]] = defaultdict(set)
    for entry in mapping.channel_entries:
        by_canon[(entry.source_system, entry.canon_channel)].add(entry.source_channel_norm)

    for (source_system, canon_channel), source_values in sorted(by_canon.items()):
        if len(source_values) > 1:
            collisions.append(
                {
                    "mapping_type": "channel",
                    "collision_type": "many_sources_to_one_canon",
                    "source_system": source_system,
                    "source_value": "; ".join(sorted(source_values)),
                    "canon_value": canon_channel,
                }
            )

    return collisions


def find_collisions(mapping: MappingBundle) -> list[dict]:
    """Return deterministic collision candidates from mapping tables."""
    rows = _find_agency_collisions(mapping) + _find_channel_collisions(mapping)
    rows.sort(
        key=lambda r: (
            str(r["mapping_type"]),
            str(r["collision_type"]),
            str(r["source_system"]),
            str(r["canon_value"]),
            str(r["source_value"]),
        )
    )
    return rows


def _canon_key(row: dict) -> tuple[str, str] | None:
    canon_id = str(row.get("canon_agency_id") or "").strip()
    canon_name = str(row.get("canon_agency_name") or "").strip()
    if not canon_id and not canon_name:
        return None
    return canon_id, canon_name


def drift_report(electra_rows: list[dict], hr_rows: list[dict]) -> list[dict]:
    """Return canonical agencies present in only one system."""

    electra_map: dict[tuple[str, str], set[int]] = defaultdict(set)
    hr_map: dict[tuple[str, str], set[int]] = defaultdict(set)

    for row in electra_rows:
        key = _canon_key(row)
        if not key:
            continue
        electra_map[key].add(int(row.get("year", 0) or 0))

    for row in hr_rows:
        key = _canon_key(row)
        if not key:
            continue
        hr_map[key].add(int(row.get("year", 0) or 0))

    out: list[dict] = []
    electra_keys = set(electra_map.keys())
    hr_keys = set(hr_map.keys())

    for key in sorted(electra_keys - hr_keys):
        out.append(
            {
                "presence": "electra_only",
                "canon_agency_id": key[0],
                "canon_agency_name": key[1],
                "years": _sorted_years(electra_map[key]),
            }
        )

    for key in sorted(hr_keys - electra_keys):
        out.append(
            {
                "presence": "hotelrunner_only",
                "canon_agency_id": key[0],
                "canon_agency_name": key[1],
                "years": _sorted_years(hr_map[key]),
            }
        )

    return out


def _token_set(value: str) -> set[str]:
    normalized = normalize_name(value)
    if not normalized:
        return set()
    return {token for token in normalized.split(" ") if token}


def _token_overlap_score(left: str, right: str) -> float:
    left_tokens = _token_set(left)
    right_tokens = _token_set(right)
    if not left_tokens or not right_tokens:
        return 0.0
    union = left_tokens | right_tokens
    if not union:
        return 0.0
    intersection = left_tokens & right_tokens
    return float(len(intersection)) / float(len(union))


def sample_mapped_rows(rows: list[dict], limit: int = 20) -> list[dict]:
    """Return a deterministic sample of rows with canonical mapping decisions."""
    mapped = [
        {
            "system": str(row.get("system") or "").strip(),
            "year": int(row.get("year", 0) or 0),
            "date": str(row.get("date") or "").strip(),
            "source_agency_id": str(row.get("agency_id") or "").strip(),
            "source_agency_name": str(row.get("agency_name") or row.get("agency") or "").strip(),
            "source_channel": str(row.get("channel") or "").strip(),
            "canon_agency_id": str(row.get("canon_agency_id") or "").strip(),
            "canon_agency_name": str(row.get("canon_agency_name") or "").strip(),
            "mapped_by": str(row.get("mapped_by") or "").strip(),
        }
        for row in rows
        if (str(row.get("canon_agency_id") or "").strip() or str(row.get("canon_agency_name") or "").strip())
    ]
    mapped.sort(
        key=lambda r: (
            str(r["system"]),
            int(r["year"]),
            str(r["date"]),
            str(r["source_agency_id"]),
            str(r["source_agency_name"]),
            str(r["source_channel"]),
            str(r["canon_agency_id"]),
            str(r["mapped_by"]),
        )
    )
    return mapped[: max(0, int(limit))]


def suggest_unmapped_candidates(
    unmapped_rows: list[dict],
    mapping: MappingBundle,
    max_candidates: int = 3,
) -> list[dict]:
    """
    Suggest deterministic canonical candidates for unmapped agency rows.

    Similarity is token-overlap between source agency text and canonical agency name.
    """
    max_n = max(1, int(max_candidates))
    by_system: dict[str, list[tuple[str, str]]] = defaultdict(list)
    seen_per_system: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for entry in mapping.agency_entries:
        key = (entry.canon_agency_id, entry.canon_agency_name)
        if key in seen_per_system[entry.source_system]:
            continue
        seen_per_system[entry.source_system].add(key)
        by_system[entry.source_system].append(key)

    for system in by_system:
        by_system[system].sort(key=lambda x: (str(x[0]), str(x[1])))

    out: list[dict] = []
    for row in unmapped_rows:
        if str(row.get("item_type")) != "agency":
            continue
        system = str(row.get("system") or "").strip().lower()
        source_name = str(row.get("source_agency_name") or row.get("source_agency_id") or "").strip()
        candidates = by_system.get(system, [])
        scored = []
        for canon_id, canon_name in candidates:
            score = _token_overlap_score(source_name, canon_name)
            scored.append((score, canon_id, canon_name))
        scored.sort(key=lambda x: (-float(x[0]), str(x[1]), str(x[2])))

        suggested_items: list[str] = []
        for score, canon_id, canon_name in scored[:max_n]:
            suggested_items.append(f"{canon_id}/{canon_name} ({score:.2f})")

        out.append(
            {
                "system": system,
                "source_agency_id": str(row.get("source_agency_id") or "").strip(),
                "source_agency_name": str(row.get("source_agency_name") or "").strip(),
                "occurrences": int(row.get("occurrences", 0) or 0),
                "years": str(row.get("years") or "").strip(),
                "suggested_candidates": "; ".join(suggested_items),
            }
        )

    out.sort(
        key=lambda r: (
            str(r["system"]),
            str(r["source_agency_id"]),
            str(r["source_agency_name"]),
        )
    )
    return out
