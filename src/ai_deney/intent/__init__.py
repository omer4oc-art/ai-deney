"""Deterministic intent parsing for Electra questions."""

from .electra_intent import parse_electra_query
from .query_spec import QuerySpec

__all__ = ["QuerySpec", "parse_electra_query"]

