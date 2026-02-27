"""Mapping helpers for canonical agency/channel normalization."""

from ai_deney.mapping.health import drift_report, find_collisions, find_unmapped
from ai_deney.mapping.loader import (
    MappingBundle,
    default_mapping_agencies_path,
    default_mapping_channels_path,
    default_mapping_rules_path,
    enrich_row,
    enrich_rows,
    load_mapping_bundle,
    match_agency,
    match_agency_with_reason,
    match_channel,
    normalize_name,
)
from ai_deney.mapping.rules import apply_agency_rules, load_agency_rules

__all__ = [
    "MappingBundle",
    "default_mapping_agencies_path",
    "default_mapping_channels_path",
    "default_mapping_rules_path",
    "drift_report",
    "enrich_row",
    "enrich_rows",
    "find_collisions",
    "find_unmapped",
    "load_mapping_bundle",
    "load_agency_rules",
    "match_agency",
    "match_agency_with_reason",
    "match_channel",
    "normalize_name",
    "apply_agency_rules",
]
