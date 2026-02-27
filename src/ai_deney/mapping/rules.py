"""Deterministic rule engine for fallback canonical mapping."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

_VALID_RULE_FIELDS = {"agency_id", "agency_name", "channel"}
_VALID_RULE_OPS = {"contains", "regex"}


@dataclass(frozen=True)
class AgencyRule:
    source_system: str
    field: str
    op: str
    value: str
    canon_agency_id: str
    canon_agency_name: str
    reason: str
    compiled_pattern: re.Pattern[str] | None = None


@dataclass(frozen=True)
class AgencyRuleMatch:
    canon_agency_id: str
    canon_agency_name: str
    reason: str


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def default_mapping_rules_path() -> Path:
    return _repo_root() / "config" / "mapping_rules.json"


def _normalize_text(value: str) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _ensure_within_repo(path: Path) -> None:
    try:
        path.resolve().relative_to(_repo_root().resolve())
    except Exception as exc:
        raise ValueError(f"mapping rules path escapes repo root: {path}") from exc


def _load_rule_row(row: dict, idx: int, path: Path) -> AgencyRule:
    source_system = str(row.get("source_system") or "").strip().lower()
    if source_system not in {"electra", "hotelrunner"}:
        raise ValueError(f"invalid rule source_system at {path}:{idx}: {source_system}")

    field = str(row.get("field") or "").strip().lower()
    if field not in _VALID_RULE_FIELDS:
        raise ValueError(f"invalid rule field at {path}:{idx}: {field}")

    op = str(row.get("op") or "").strip().lower()
    if op not in _VALID_RULE_OPS:
        raise ValueError(f"invalid rule op at {path}:{idx}: {op}")

    value = str(row.get("value") or "")
    if not value:
        raise ValueError(f"rule value cannot be empty at {path}:{idx}")

    canon_agency_id = str(row.get("canon_agency_id") or "").strip()
    canon_agency_name = str(row.get("canon_agency_name") or "").strip()
    if not canon_agency_id and not canon_agency_name:
        raise ValueError(f"rule missing canonical target at {path}:{idx}")

    reason = str(row.get("reason") or "").strip()
    if not reason:
        if op == "contains":
            reason = f"rule:contains:{_normalize_text(value)}"
        else:
            reason = f"rule:regex:{value}"

    compiled_pattern: re.Pattern[str] | None = None
    if op == "regex":
        try:
            compiled_pattern = re.compile(value, flags=re.IGNORECASE)
        except re.error as exc:
            raise ValueError(f"invalid regex rule at {path}:{idx}: {value}") from exc

    return AgencyRule(
        source_system=source_system,
        field=field,
        op=op,
        value=value,
        canon_agency_id=canon_agency_id,
        canon_agency_name=canon_agency_name,
        reason=reason,
        compiled_pattern=compiled_pattern,
    )


def load_agency_rules(mapping_rules_path: Path | None = None) -> list[AgencyRule]:
    path = (mapping_rules_path or default_mapping_rules_path()).resolve()
    _ensure_within_repo(path)
    if not path.exists():
        return []

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"mapping rules payload must be an object: {path}")

    raw_rules = payload.get("agency_rules")
    if raw_rules is None:
        return []
    if not isinstance(raw_rules, list):
        raise ValueError(f"agency_rules must be a list: {path}")

    rules: list[AgencyRule] = []
    for idx, row in enumerate(raw_rules, start=1):
        if not isinstance(row, dict):
            raise ValueError(f"rule row must be an object at {path}:{idx}")
        rules.append(_load_rule_row(row, idx=idx, path=path))
    return rules


def apply_agency_rules(
    rules: list[AgencyRule],
    source_system: str,
    source_agency_id: str | None,
    source_agency_name: str | None,
    source_channel: str | None,
) -> AgencyRuleMatch | None:
    system = str(source_system or "").strip().lower()
    values = {
        "agency_id": str(source_agency_id or "").strip(),
        "agency_name": str(source_agency_name or "").strip(),
        "channel": str(source_channel or "").strip(),
    }
    normalized_values = {key: _normalize_text(val) for key, val in values.items()}

    for rule in rules:
        if rule.source_system != system:
            continue
        raw_value = values.get(rule.field, "")
        normalized_value = normalized_values.get(rule.field, "")
        if not raw_value:
            continue

        matched = False
        if rule.op == "contains":
            needle = _normalize_text(rule.value)
            matched = bool(needle) and needle in normalized_value
        elif rule.op == "regex":
            pattern = rule.compiled_pattern
            if pattern is not None:
                matched = bool(pattern.search(raw_value))

        if matched:
            return AgencyRuleMatch(
                canon_agency_id=rule.canon_agency_id,
                canon_agency_name=rule.canon_agency_name,
                reason=rule.reason,
            )
    return None
