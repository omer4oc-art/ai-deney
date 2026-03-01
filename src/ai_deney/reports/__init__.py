"""Report registry + executors for deterministic answers."""

from .toy_reports import answer_question as answer_toy_question
from .toy_reports import answer_with_metadata as answer_toy_with_metadata

__all__ = ["answer_toy_question", "answer_toy_with_metadata"]
