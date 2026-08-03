"""Deterministic scoring primitives for exhibition matching."""

from .engine import (
    BUYER_SCORE_V1,
    CONSUMER_SCORE_V1,
    EXHIBITOR_SCORE_V1,
    GUEST_WEB_SEARCH_SCORE_V1,
    RECIPROCAL_SCORE_V1,
    DirectionalScoreResult,
    EligibilityDecision,
    IneligibleCandidateError,
    ReciprocalScoreResult,
    ScoreCap,
    ScoreValidationError,
    ScoringPolicy,
    calculate_directional_score,
    calculate_reciprocal_score,
)

__all__ = [
    "BUYER_SCORE_V1",
    "CONSUMER_SCORE_V1",
    "EXHIBITOR_SCORE_V1",
    "GUEST_WEB_SEARCH_SCORE_V1",
    "RECIPROCAL_SCORE_V1",
    "DirectionalScoreResult",
    "EligibilityDecision",
    "IneligibleCandidateError",
    "ReciprocalScoreResult",
    "ScoreCap",
    "ScoreValidationError",
    "ScoringPolicy",
    "calculate_directional_score",
    "calculate_reciprocal_score",
]
