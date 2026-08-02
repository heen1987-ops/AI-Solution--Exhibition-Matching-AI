"""Public command/result contract for the common matching engine."""

from .facade import (
    CATALOG_SEARCH_POLICY_VERSION,
    MATCHING_ENGINE_COMMAND_V1,
    MATCHING_ENGINE_RESULT_V1,
    MATCHING_ENGINE_VERSION,
    CatalogSearchScoreResult,
    CatalogSearchSignals,
    ExcludedCandidateResult,
    MatchingCandidateCommand,
    MatchingEngineCommand,
    MatchingEngineResult,
    MatchingEngineValidationError,
    MatchingMode,
    RankedCandidateResult,
    execute_matching,
    score_catalog_search,
)

__all__ = [
    "CATALOG_SEARCH_POLICY_VERSION",
    "MATCHING_ENGINE_COMMAND_V1",
    "MATCHING_ENGINE_RESULT_V1",
    "MATCHING_ENGINE_VERSION",
    "CatalogSearchScoreResult",
    "CatalogSearchSignals",
    "ExcludedCandidateResult",
    "MatchingCandidateCommand",
    "MatchingEngineCommand",
    "MatchingEngineResult",
    "MatchingEngineValidationError",
    "MatchingMode",
    "RankedCandidateResult",
    "execute_matching",
    "score_catalog_search",
]
