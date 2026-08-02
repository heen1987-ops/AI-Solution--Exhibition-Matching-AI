"""Offline quality gates for the common matching engine."""

from .engine import (
    EVALUATOR_VERSION,
    GOLDEN_SET_SCHEMA_VERSION,
    EvaluationReport,
    GoldenSet,
    GoldenSetValidationError,
    evaluate_golden_set,
    evaluate_scenario,
    load_golden_set,
    load_golden_set_payload,
)

__all__ = [
    "EVALUATOR_VERSION",
    "GOLDEN_SET_SCHEMA_VERSION",
    "EvaluationReport",
    "GoldenSet",
    "GoldenSetValidationError",
    "evaluate_golden_set",
    "evaluate_scenario",
    "load_golden_set",
    "load_golden_set_payload",
]
