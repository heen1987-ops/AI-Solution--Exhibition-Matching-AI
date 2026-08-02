"""Backend-to-engine boundary for deterministic matching execution.

This adapter supplies the published ontology version and translates one backend
candidate at a time into the provider/DB-independent engine contract.  It owns no
weights and implements no score formula.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from app.services.matching.ontology_support import get_catalog
from meet_ai.engine import (
    CatalogSearchSignals,
    MatchingCandidateCommand,
    MatchingEngineCommand,
    MatchingMode,
    RankedCandidateResult,
    execute_matching,
)
from meet_ai.scoring import EligibilityDecision, ScoreCap

Number = float | int | str


def _execute_one(
    mode: MatchingMode,
    candidate: MatchingCandidateCommand,
    *,
    model_version: str | None = None,
) -> RankedCandidateResult:
    result = execute_matching(
        MatchingEngineCommand(
            mode=mode,
            taxonomy_version=get_catalog().version,
            model_version=model_version,
            candidates=(candidate,),
        )
    )
    if len(result.ranked_candidates) != 1:
        raise RuntimeError("eligible backend candidate was not scored by the engine")
    return result.ranked_candidates[0]


def execute_catalog_search_score(
    signals: CatalogSearchSignals,
    *,
    reason_evidence: Mapping[str, Sequence[str]] | None = None,
    model_version: str | None = None,
) -> RankedCandidateResult:
    return _execute_one(
        MatchingMode.CATALOG_SEARCH,
        MatchingCandidateCommand(
            candidate_id="catalog-search-candidate",
            exhibitor_id="catalog-search-exhibitor",
            eligibility=EligibilityDecision(True, "catalog-search-eligibility-v1"),
            search_signals=signals,
            reason_evidence=reason_evidence or {},
        ),
        model_version=model_version,
    )


def execute_directional_score(
    *,
    candidate_id: str,
    exhibitor_id: str,
    mode: MatchingMode,
    components: Mapping[str, Number | None],
    eligibility: EligibilityDecision,
    confidence: Number | None,
    caps: Sequence[ScoreCap] = (),
    reason_evidence: Mapping[str, Sequence[str]] | None = None,
    model_version: str | None = None,
) -> RankedCandidateResult:
    if mode not in (MatchingMode.GENERAL_VISITOR, MatchingMode.BUYER_TO_EXHIBITOR):
        raise ValueError(f"directional adapter does not support {mode.value}")
    return _execute_one(
        mode,
        MatchingCandidateCommand(
            candidate_id=candidate_id,
            exhibitor_id=exhibitor_id,
            eligibility=eligibility,
            components=components,
            confidence=confidence,
            score_caps=tuple(caps),
            reason_evidence=reason_evidence or {},
        ),
        model_version=model_version,
    )


def execute_reciprocal_score(
    *,
    candidate_id: str,
    exhibitor_id: str,
    eligibility: EligibilityDecision,
    buyer_components: Mapping[str, Number | None],
    exhibitor_components: Mapping[str, Number | None],
    buyer_confidence: Number,
    exhibitor_confidence: Number,
    acceptance_capacity_score: Number,
    buyer_caps: Sequence[ScoreCap] = (),
    exhibitor_caps: Sequence[ScoreCap] = (),
    score_caps: Sequence[ScoreCap] = (),
    policy_adjustment: Number = 0,
    reason_evidence: Mapping[str, Sequence[str]] | None = None,
    model_version: str | None = None,
) -> RankedCandidateResult:
    return _execute_one(
        MatchingMode.RECIPROCAL,
        MatchingCandidateCommand(
            candidate_id=candidate_id,
            exhibitor_id=exhibitor_id,
            eligibility=eligibility,
            buyer_components=buyer_components,
            exhibitor_components=exhibitor_components,
            buyer_confidence=buyer_confidence,
            exhibitor_confidence=exhibitor_confidence,
            acceptance_capacity_score=acceptance_capacity_score,
            policy_adjustment=policy_adjustment,
            buyer_caps=tuple(buyer_caps),
            exhibitor_caps=tuple(exhibitor_caps),
            score_caps=tuple(score_caps),
            reason_evidence=reason_evidence or {},
        ),
        model_version=model_version,
    )
