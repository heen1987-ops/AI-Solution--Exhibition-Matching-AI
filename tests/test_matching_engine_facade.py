from __future__ import annotations

import inspect
from decimal import Decimal

import pytest

import meet_ai.engine.facade as facade_module
from meet_ai.engine import (
    CATALOG_SEARCH_POLICY_VERSION,
    MATCHING_ENGINE_COMMAND_V1,
    MATCHING_ENGINE_COMMAND_V1_1,
    MATCHING_ENGINE_RESULT_V1_1,
    REASON_CLAIM_POLICY_VERSION,
    CatalogSearchSignals,
    MatchingCandidateCommand,
    MatchingEngineCommand,
    MatchingEngineValidationError,
    MatchingMode,
    execute_matching,
)
from meet_ai.scoring import EligibilityDecision


def _eligibility(candidate_id: str, passed: bool = True) -> EligibilityDecision:
    return EligibilityDecision(
        passed,
        f"eligibility:{candidate_id}",
        () if passed else ("EXHIBITOR_NOT_APPROVED",),
    )


def test_catalog_search_mode_preserves_frozen_formula_and_provenance() -> None:
    result = execute_matching(
        MatchingEngineCommand(
            mode=MatchingMode.CATALOG_SEARCH,
            taxonomy_version="1.0.0",
            model_version="embedding-model-v1",
            candidates=(
                MatchingCandidateCommand(
                    "candidate-a",
                    "exhibitor-a",
                    _eligibility("candidate-a"),
                    search_signals=CatalogSearchSignals(
                        semantic=0.8,
                        keyword=0.7,
                        category=0.6,
                        data_quality=0.5,
                        booth_availability=0.4,
                    ),
                ),
            ),
        )
    )

    candidate = result.ranked_candidates[0]
    assert result.contract_version == MATCHING_ENGINE_RESULT_V1_1
    assert result.policy_versions == {"catalog_search": CATALOG_SEARCH_POLICY_VERSION}
    assert result.taxonomy_version == "1.0.0"
    assert result.model_version == "embedding-model-v1"
    assert candidate.normalized_score == Decimal("0.705")
    assert candidate.score_100 == Decimal("70.500")
    assert candidate.eligibility_evaluation_id == "eligibility:candidate-a"
    assert len(result.input_fingerprint) == 64
    assert len(result.result_fingerprint) == 64
    assert len(candidate.calculation_fingerprint) == 64


@pytest.mark.parametrize(
    ("mode", "candidate", "expected_policies"),
    [
        (
            MatchingMode.GENERAL_VISITOR,
            MatchingCandidateCommand(
                "visitor",
                "exhibitor-v",
                _eligibility("visitor"),
                components={"goal": 1, "category": Decimal("0.8")},
                confidence=0.9,
            ),
            {"consumer"},
        ),
        (
            MatchingMode.BUYER_TO_EXHIBITOR,
            MatchingCandidateCommand(
                "buyer",
                "exhibitor-b",
                _eligibility("buyer"),
                components={"business_goal": 1, "product": Decimal("0.9")},
                confidence=0.9,
            ),
            {"buyer"},
        ),
        (
            MatchingMode.RECIPROCAL,
            MatchingCandidateCommand(
                "reciprocal",
                "exhibitor-r",
                _eligibility("reciprocal"),
                buyer_components={"business_goal": 1, "product": 0.9},
                exhibitor_components={"buyer_type": 0.9, "channel": 1},
                buyer_confidence=0.9,
                exhibitor_confidence=0.8,
                acceptance_capacity_score=0.75,
            ),
            {"buyer", "exhibitor", "reciprocal"},
        ),
    ],
)
def test_directional_and_reciprocal_modes_select_internal_published_policies(
    mode: MatchingMode,
    candidate: MatchingCandidateCommand,
    expected_policies: set[str],
) -> None:
    result = execute_matching(MatchingEngineCommand(mode, "1.0.0", (candidate,)))

    ranked = result.ranked_candidates[0]
    assert set(result.policy_versions) == expected_policies
    assert set(ranked.score_fingerprints) == expected_policies
    assert Decimal(0) <= ranked.normalized_score <= Decimal(1)
    assert float(ranked.score_100) == pytest.approx(
        float(ranked.normalized_score) * 100
    )
    if mode is MatchingMode.RECIPROCAL:
        assert ranked.buyer_directional_result is not None
        assert ranked.exhibitor_directional_result is not None
        assert ranked.reciprocal_result is not None
    else:
        assert ranked.directional_result is not None


def test_ineligible_and_unrecalled_candidates_are_excluded_before_scoring() -> None:
    result = execute_matching(
        MatchingEngineCommand(
            MatchingMode.GENERAL_VISITOR,
            "1.0.0",
            (
                MatchingCandidateCommand(
                    "blocked",
                    "exhibitor-blocked",
                    _eligibility("blocked", False),
                    components={"not-a-policy-component": "invalid"},
                ),
                MatchingCandidateCommand(
                    "not-recalled",
                    "exhibitor-missed",
                    _eligibility("not-recalled"),
                    recalled=False,
                    components={"also-invalid": "invalid"},
                ),
            ),
        )
    )

    assert result.ranked_candidates == ()
    assert [item.candidate_id for item in result.excluded_candidates] == [
        "blocked",
        "not-recalled",
    ]
    assert result.excluded_candidates[0].reason_codes == ("EXHIBITOR_NOT_APPROVED",)
    assert result.excluded_candidates[1].reason_codes == ("NOT_RECALLED",)


def test_command_order_and_set_like_order_do_not_change_fingerprints_or_rank() -> None:
    first_candidate = MatchingCandidateCommand(
        "b",
        "exhibitor-b",
        _eligibility("b"),
        recall_channels=("VECTOR", "STRUCTURED"),
        components={"goal": 0.8, "category": 0.8},
    )
    second_candidate = MatchingCandidateCommand(
        "a",
        "exhibitor-a",
        _eligibility("a"),
        recall_channels=("STRUCTURED",),
        components={"category": 0.8, "goal": 0.8},
    )

    first = execute_matching(
        MatchingEngineCommand(
            MatchingMode.GENERAL_VISITOR,
            "1.0.0",
            (first_candidate, second_candidate),
        )
    )
    second = execute_matching(
        MatchingEngineCommand(
            MatchingMode.GENERAL_VISITOR,
            "1.0.0",
            (second_candidate, first_candidate),
        )
    )

    assert first.input_fingerprint == second.input_fingerprint
    assert first.result_fingerprint == second.result_fingerprint
    assert [item.candidate_id for item in first.ranked_candidates] == ["a", "b"]


def test_contract_fails_closed_and_facade_has_no_runtime_service_dependencies() -> None:
    with pytest.raises(MatchingEngineValidationError, match="unsupported command"):
        MatchingEngineCommand(
            MatchingMode.GENERAL_VISITOR,
            "1.0.0",
            (),
            contract_version="matching-engine-command-v2",
        )
    with pytest.raises(MatchingEngineValidationError, match="taxonomy_version"):
        MatchingEngineCommand(MatchingMode.GENERAL_VISITOR, " ", ())

    source = inspect.getsource(facade_module)
    assert MATCHING_ENGINE_COMMAND_V1 in source
    for forbidden in ("fastapi", "sqlalchemy", "httpx", "openai", "app.services"):
        assert forbidden not in source.lower()


def test_reason_claims_require_both_actual_contribution_and_adapter_evidence() -> None:
    candidate = MatchingCandidateCommand(
        "buyer-reason",
        "exhibitor-reason",
        _eligibility("buyer-reason"),
        recall_channels=("STRUCTURED", "VECTOR"),
        components={"product": 0.9, "channel": 0.8, "moq": 0.7},
        confidence=0.9,
        reason_evidence={
            "PRODUCT_MATCH": ("buyer:product", "candidate:product"),
            "CHANNEL_MATCH": ("buyer:channel", "candidate:channel"),
            "UNSUPPORTED_FACT": ("candidate:unsupported",),
        },
    )

    ranked = execute_matching(
        MatchingEngineCommand(
            MatchingMode.BUYER_TO_EXHIBITOR,
            "1.0.0",
            (candidate,),
        )
    ).ranked_candidates[0]

    assert [claim.code for claim in ranked.reason_claims] == [
        "PRODUCT_MATCH",
        "CHANNEL_MATCH",
    ]
    assert all(claim.evidence_refs for claim in ranked.reason_claims)
    assert all(claim.source_components for claim in ranked.reason_claims)
    assert all(
        claim.policy_version == REASON_CLAIM_POLICY_VERSION
        and len(claim.claim_fingerprint) == 64
        for claim in ranked.reason_claims
    )
    assert ranked.reason_fingerprint is not None
    assert len(ranked.reason_fingerprint) == 64


def test_legacy_contract_rejects_reason_evidence_instead_of_mutating_v1() -> None:
    candidate = MatchingCandidateCommand(
        "legacy",
        "legacy-exhibitor",
        _eligibility("legacy"),
        components={"goal": 1},
        reason_evidence={"GOAL_MATCH": ("profile:goal", "candidate:goal")},
    )

    with pytest.raises(MatchingEngineValidationError, match="does not support"):
        MatchingEngineCommand(
            MatchingMode.GENERAL_VISITOR,
            "1.0.0",
            (candidate,),
            contract_version=MATCHING_ENGINE_COMMAND_V1,
        )

    assert MatchingEngineCommand(
        MatchingMode.GENERAL_VISITOR,
        "1.0.0",
        (),
    ).contract_version == MATCHING_ENGINE_COMMAND_V1_1


def test_hard_filter_reason_claim_is_emitted_only_with_filter_evidence() -> None:
    result = execute_matching(
        MatchingEngineCommand(
            MatchingMode.BUYER_TO_EXHIBITOR,
            "1.0.0",
            (
                MatchingCandidateCommand(
                    "blocked-with-evidence",
                    "blocked-exhibitor",
                    _eligibility("blocked-with-evidence", False),
                    reason_evidence={
                        "EXHIBITOR_NOT_APPROVED": (
                            "participation:blocked:approval_status",
                        )
                    },
                ),
                MatchingCandidateCommand(
                    "blocked-without-evidence",
                    "blocked-exhibitor-2",
                    _eligibility("blocked-without-evidence", False),
                ),
            ),
        )
    )

    with_evidence, without_evidence = result.excluded_candidates
    assert [claim.code for claim in with_evidence.reason_claims] == [
        "EXHIBITOR_NOT_APPROVED"
    ]
    assert with_evidence.reason_claims[0].source_components == (
        "eligibility:EXHIBITOR_NOT_APPROVED",
    )
    assert without_evidence.reason_claims == ()
