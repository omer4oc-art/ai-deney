"""Deterministic loaders for canonical agency/channel mapping tables."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path

_VALID_SYSTEMS = {"electra", "hotelrunner"}
_VALID_CANON_CHANNELS = {"DIRECT", "WEB", "WALKIN", "OTA", "AGENCY"}


@dataclass(frozen=True)
class AgencyMappingEntry:
    source_system: str
    source_agency_id: str
    source_agency_name: str
    source_agency_name_norm: str
    canon_agency_id: str
    canon_agency_name: str
    notes: str


@dataclass(frozen=True)
class ChannelMappingEntry:
    source_system: str
    source_channel: str
    source_channel_norm: str
    canon_channel: str


@dataclass(frozen=True)
class MappingBundle:
    agency_entries: list[AgencyMappingEntry]
    channel_entries: list[ChannelMappingEntry]
    agency_by_id: dict[tuple[str, str], AgencyMappingEntry]
    agency_by_name: dict[tuple[str, str], AgencyMappingEntry]
    channel_by_value: dict[tuple[str, str], ChannelMappingEntry]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def default_mapping_agencies_path() -> Path:
    return _repo_root() / "config" / "mapping_agencies.csv"


def default_mapping_channels_path() -> Path:
    return _repo_root() / "config" / "mapping_channels.csv"


def normalize_name(value: str) -> str:
    """Normalize names for deterministic matching (case, spaces, punctuation)."""
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _normalize_source_id(value: str) -> str:
    return str(value or "").strip().upper()


def _normalize_system(value: str) -> str:
    return str(value or "").strip().lower()


def _read_rows(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return [dict(r) for r in csv.DictReader(f)]


def _validate_columns(path: Path, expected: list[str]) -> None:
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = [str(c).strip() for c in (reader.fieldnames or [])]
    missing = [c for c in expected if c not in fieldnames]
    if missing:
        raise ValueError(f"mapping file missing columns {missing}: {path}")


def _ensure_within_repo(path: Path) -> None:
    try:
        path.resolve().relative_to(_repo_root().resolve())
    except Exception as exc:
        raise ValueError(f"mapping path escapes repo root: {path}") from exc


def _load_agency_entries(path: Path) -> MappingBundle:
    _validate_columns(
        path,
        expected=[
            "source_system",
            "source_agency_id",
            "source_agency_name",
            "canon_agency_id",
            "canon_agency_name",
            "notes",
        ],
    )
    rows = _read_rows(path)

    agency_entries: list[AgencyMappingEntry] = []
    agency_by_id: dict[tuple[str, str], AgencyMappingEntry] = {}
    agency_by_name: dict[tuple[str, str], AgencyMappingEntry] = {}

    for idx, row in enumerate(rows, start=2):
        source_system = _normalize_system(row.get("source_system", ""))
        if source_system not in _VALID_SYSTEMS:
            raise ValueError(f"invalid source_system at {path}:{idx}: {source_system}")

        source_agency_id = _normalize_source_id(row.get("source_agency_id", ""))
        source_agency_name = str(row.get("source_agency_name", "") or "").strip()
        source_agency_name_norm = normalize_name(source_agency_name)
        canon_agency_id = str(row.get("canon_agency_id", "") or "").strip()
        canon_agency_name = str(row.get("canon_agency_name", "") or "").strip()
        notes = str(row.get("notes", "") or "").strip()

        if not source_agency_id and not source_agency_name_norm:
            raise ValueError(f"mapping row missing source id and source name at {path}:{idx}")
        if not canon_agency_id and not canon_agency_name:
            raise ValueError(f"mapping row missing canonical id and canonical name at {path}:{idx}")

        entry = AgencyMappingEntry(
            source_system=source_system,
            source_agency_id=source_agency_id,
            source_agency_name=source_agency_name,
            source_agency_name_norm=source_agency_name_norm,
            canon_agency_id=canon_agency_id,
            canon_agency_name=canon_agency_name,
            notes=notes,
        )

        if source_agency_id:
            key_id = (source_system, source_agency_id)
            if key_id in agency_by_id:
                prev = agency_by_id[key_id]
                if (prev.canon_agency_id, prev.canon_agency_name) == (canon_agency_id, canon_agency_name):
                    raise ValueError(f"duplicate agency id mapping at {path}:{idx}: {key_id}")
                raise ValueError(
                    f"ambiguous agency id mapping at {path}:{idx}: {key_id} -> "
                    f"{prev.canon_agency_id}/{prev.canon_agency_name} and {canon_agency_id}/{canon_agency_name}"
                )
            agency_by_id[key_id] = entry

        if source_agency_name_norm:
            key_name = (source_system, source_agency_name_norm)
            if key_name in agency_by_name:
                prev = agency_by_name[key_name]
                if (prev.canon_agency_id, prev.canon_agency_name) == (canon_agency_id, canon_agency_name):
                    raise ValueError(f"duplicate agency name mapping at {path}:{idx}: {key_name}")
                raise ValueError(
                    f"ambiguous agency name mapping at {path}:{idx}: {key_name} -> "
                    f"{prev.canon_agency_id}/{prev.canon_agency_name} and {canon_agency_id}/{canon_agency_name}"
                )
            agency_by_name[key_name] = entry

        agency_entries.append(entry)

    agency_entries.sort(
        key=lambda e: (
            e.source_system,
            e.source_agency_id,
            e.source_agency_name_norm,
            e.canon_agency_id,
            e.canon_agency_name,
        )
    )

    return MappingBundle(
        agency_entries=agency_entries,
        channel_entries=[],
        agency_by_id=agency_by_id,
        agency_by_name=agency_by_name,
        channel_by_value={},
    )


def _load_channel_entries(path: Path) -> tuple[list[ChannelMappingEntry], dict[tuple[str, str], ChannelMappingEntry]]:
    _validate_columns(path, expected=["source_system", "source_channel", "canon_channel"])
    rows = _read_rows(path)

    channel_entries: list[ChannelMappingEntry] = []
    channel_by_value: dict[tuple[str, str], ChannelMappingEntry] = {}

    for idx, row in enumerate(rows, start=2):
        source_system = _normalize_system(row.get("source_system", ""))
        if source_system not in _VALID_SYSTEMS:
            raise ValueError(f"invalid source_system at {path}:{idx}: {source_system}")

        source_channel = str(row.get("source_channel", "") or "").strip()
        source_channel_norm = normalize_name(source_channel)
        if not source_channel_norm:
            raise ValueError(f"channel mapping missing source_channel at {path}:{idx}")

        canon_channel = str(row.get("canon_channel", "") or "").strip().upper()
        if canon_channel not in _VALID_CANON_CHANNELS:
            raise ValueError(
                f"invalid canon_channel at {path}:{idx}: {canon_channel}; "
                f"expected one of {sorted(_VALID_CANON_CHANNELS)}"
            )

        entry = ChannelMappingEntry(
            source_system=source_system,
            source_channel=source_channel,
            source_channel_norm=source_channel_norm,
            canon_channel=canon_channel,
        )
        key = (source_system, source_channel_norm)
        if key in channel_by_value:
            prev = channel_by_value[key]
            if prev.canon_channel == canon_channel:
                raise ValueError(f"duplicate channel mapping at {path}:{idx}: {key}")
            raise ValueError(
                f"ambiguous channel mapping at {path}:{idx}: {key} -> "
                f"{prev.canon_channel} and {canon_channel}"
            )
        channel_by_value[key] = entry
        channel_entries.append(entry)

    channel_entries.sort(key=lambda e: (e.source_system, e.source_channel_norm, e.canon_channel))
    return channel_entries, channel_by_value


def load_mapping_bundle(
    mapping_agencies_path: Path | None = None,
    mapping_channels_path: Path | None = None,
) -> MappingBundle:
    """Load canonical mapping files with strict deterministic validation."""
    agencies_path = (mapping_agencies_path or default_mapping_agencies_path()).resolve()
    channels_path = (mapping_channels_path or default_mapping_channels_path()).resolve()
    _ensure_within_repo(agencies_path)
    if not agencies_path.exists():
        raise ValueError(f"agency mapping file not found: {agencies_path}")

    bundle = _load_agency_entries(agencies_path)

    channel_entries: list[ChannelMappingEntry] = []
    channel_by_value: dict[tuple[str, str], ChannelMappingEntry] = {}
    if channels_path.exists():
        _ensure_within_repo(channels_path)
        channel_entries, channel_by_value = _load_channel_entries(channels_path)

    return MappingBundle(
        agency_entries=bundle.agency_entries,
        channel_entries=channel_entries,
        agency_by_id=bundle.agency_by_id,
        agency_by_name=bundle.agency_by_name,
        channel_by_value=channel_by_value,
    )


def match_agency(
    mapping: MappingBundle,
    source_system: str,
    source_agency_id: str | None,
    source_agency_name: str | None,
) -> tuple[str, str] | None:
    """Match an agency by id; fallback to normalized name only when id is missing."""
    system = _normalize_system(source_system)
    source_id = _normalize_source_id(source_agency_id or "")
    source_name_norm = normalize_name(source_agency_name or "")

    if source_id:
        entry = mapping.agency_by_id.get((system, source_id))
        if not entry:
            return None
        return entry.canon_agency_id, entry.canon_agency_name

    if source_name_norm:
        entry = mapping.agency_by_name.get((system, source_name_norm))
        if not entry:
            return None
        return entry.canon_agency_id, entry.canon_agency_name

    return None


def match_channel(
    mapping: MappingBundle,
    source_system: str,
    source_channel: str | None,
    source_agency_name: str | None,
) -> str | None:
    """Match canonical channel by channel value, or agency name when channel is absent."""
    system = _normalize_system(source_system)
    channel_norm = normalize_name(source_channel or "")
    if channel_norm:
        entry = mapping.channel_by_value.get((system, channel_norm))
        if entry:
            return entry.canon_channel
        return None

    agency_name_norm = normalize_name(source_agency_name or "")
    if agency_name_norm:
        entry = mapping.channel_by_value.get((system, agency_name_norm))
        if entry:
            return entry.canon_channel
    return None


def enrich_row(row: dict, source_system: str, mapping: MappingBundle) -> dict:
    """Attach canonical agency/channel fields to a normalized row (view-layer enrichment)."""
    out = dict(row)
    source_id = str(row.get("agency_id") or "").strip()
    source_name = str(row.get("agency_name") or row.get("agency") or "").strip()
    agency_match = match_agency(
        mapping=mapping,
        source_system=source_system,
        source_agency_id=source_id,
        source_agency_name=source_name,
    )
    if agency_match:
        out["canon_agency_id"] = agency_match[0]
        out["canon_agency_name"] = agency_match[1]
    else:
        out["canon_agency_id"] = ""
        out["canon_agency_name"] = ""

    source_channel = str(row.get("channel") or "").strip()
    canon_channel = match_channel(
        mapping=mapping,
        source_system=source_system,
        source_channel=source_channel,
        source_agency_name=source_name,
    )
    out["canon_channel"] = canon_channel or ""
    return out


def enrich_rows(rows: list[dict], source_system: str, mapping: MappingBundle) -> list[dict]:
    return [enrich_row(row, source_system=source_system, mapping=mapping) for row in rows]
