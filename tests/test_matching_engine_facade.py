from __future__ import annotations

import inspect
import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

import meet_ai.engine.facade as facade_module
from meet_ai.engine import (
    CATALOG_SEARCH_POLICY_VERSION,
    INTENT_PROPOSAL_SCHEMA_V1,
    MATCHING_ENGINE_COMMAND_V1,
    MATCHING_ENGINE_COMMAND_V1_1,
    MATCHING_ENGINE_RESULT_V1_1,
    PUBLISHED_RANKING_STATE,
    REASON_CLAIM_POLICY_VERSION,
    CandidateSignalDiagnostics,
    CanonicalProfileIntentCommand,
    CatalogScope,
    CatalogSearchSignals,
    HybridRrfShadowCommand,
    HybridShadowValidationError,
    IntentNormalizationValidationError,
    IntentProjectionValidationError,
    MatchingCandidateCommand,
    MatchingEngineCommand,
    MatchingEngineValidationError,
    MatchingMode,
    NaturalLanguageIntentCommand,
    RecallChannelRanking,
    RecallChannelState,
    execute_hybrid_rrf_shadow,
    execute_matching,
    normalize_canonical_profile_intent,
    normalize_natural_language_intent,
    project_intent,
)
from meet_ai.scoring import EligibilityDecision

INTENT_PROJECTION_FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "matching"
    / "intent-projection.v1.json"
)


def _eligibility(candidate_id: str, passed: bool = True) -> EligibilityDecision:
    return EligibilityDecision(
        passed,
        f"eligibility:{candidate_id}",
        () if passed else ("EXHIBITOR_NOT_APPROVED",),
    )


def _semantic_intent(result: object) -> tuple[tuple[str, ...], ...]:
    return (
        tuple(item.concept_code for item in result.must),
        tuple(item.concept_code for item in result.prefer),
        tuple(item.concept_code for item in result.exclude),
        tuple(item.field_code for item in result.unknown),
        tuple(
            f"{item.reason_code}:{','.join(item.candidate_codes)}"
            for item in result.unresolved
        ),
    )


def test_natural_language_and_excel_profile_share_semantic_intent_contract() -> None:
    natural = normalize_natural_language_intent(
        NaturalLanguageIntentCommand("막걸리", context="PRODUCT")
    )
    profile = normalize_canonical_profile_intent(
        CanonicalProfileIntentCommand(prefer_codes=("ALCOHOL.TAKJU",))
    )

    assert _semantic_intent(natural) == _semantic_intent(profile)
    assert natural.contract_version == profile.contract_version
    assert natural.policy_version == profile.policy_version
    assert natural.ontology_version == profile.ontology_version == "1.0.0"


def test_negation_unknown_and_ambiguity_are_not_coerced_to_false_or_zero() -> None:
    excluded = normalize_natural_language_intent(
        NaturalLanguageIntentCommand("막걸리 제외", context="PRODUCT")
    )
    ambiguous = normalize_natural_language_intent(
        NaturalLanguageIntentCommand("OEM", locale="en-US", context="BUYER")
    )
    profile = normalize_canonical_profile_intent(
        CanonicalProfileIntentCommand(
            must_codes=("TRADE.OEM",), unknown_fields=("MOQ",)
        )
    )

    assert [item.concept_code for item in excluded.exclude] == ["ALCOHOL.TAKJU"]
    assert ambiguous.must == ambiguous.prefer == ambiguous.exclude == ()
    assert ambiguous.unresolved[0].reason_code == "AMBIGUOUS_PUBLISHED_TERM"
    assert "TRADE.OEM" in ambiguous.unresolved[0].candidate_codes
    assert profile.unknown[0].knowledge_state == "UNKNOWN"
    assert not hasattr(profile.unknown[0], "value")


def test_intent_fingerprints_are_reproducible_order_independent_and_pii_redacted() -> None:
    first = normalize_canonical_profile_intent(
        CanonicalProfileIntentCommand(
            prefer_codes=("USE.GIFT", "ALCOHOL.TAKJU"),
            unknown_fields=("MOQ", "CERTIFICATION"),
        )
    )
    second = normalize_canonical_profile_intent(
        CanonicalProfileIntentCommand(
            prefer_codes=("ALCOHOL.TAKJU", "USE.GIFT"),
            unknown_fields=("CERTIFICATION", "MOQ"),
        )
    )
    with_first_email = normalize_natural_language_intent(
        NaturalLanguageIntentCommand("막걸리 buyer.one@example.com", context="PRODUCT")
    )
    with_second_email = normalize_natural_language_intent(
        NaturalLanguageIntentCommand("막걸리 buyer.two@example.com", context="PRODUCT")
    )

    assert first.input_fingerprint == second.input_fingerprint
    assert first.result_fingerprint == second.result_fingerprint
    assert with_first_email.input_fingerprint == with_second_email.input_fingerprint
    assert with_first_email.redacted_input_kinds == ("EMAIL",)
    assert "buyer.one" not in repr(with_first_email)
    assert "buyer.one" not in str(with_first_email.to_dict())


def test_optional_provider_output_is_schema_validated_and_never_promoted() -> None:
    class ProposalAdapter:
        redacted_query = ""

        def propose(self, **kwargs: object) -> dict[str, object]:
            self.redacted_query = str(kwargs["redacted_query"])
            return {
                "schema_version": INTENT_PROPOSAL_SCHEMA_V1,
                "items": [
                    {"concept_code": "USE.GIFT", "requirement": "PREFER"}
                ],
            }

    adapter = ProposalAdapter()
    result = normalize_natural_language_intent(
        NaturalLanguageIntentCommand("새로운 것 test@example.com"),
        proposal_adapter=adapter,
    )

    assert adapter.redacted_query == "새로운 것 [redacted-email]"
    assert result.prefer == ()
    assert result.proposals[0].concept_code == "USE.GIFT"
    assert result.proposals[0].proposal_state == "VALIDATED_PROPOSAL_ONLY"
    assert result.unresolved[0].reason_code == "NO_PUBLISHED_MAPPING"


def test_unpublished_or_malformed_intent_inputs_fail_closed() -> None:
    with pytest.raises(IntentNormalizationValidationError, match="published ontology"):
        normalize_canonical_profile_intent(
            CanonicalProfileIntentCommand(prefer_codes=("MADE.UP",))
        )
    with pytest.raises(IntentNormalizationValidationError, match="privacy-safe"):
        CanonicalProfileIntentCommand(unknown_fields=("person@example.com",))

    class InvalidProposalAdapter:
        def propose(self, **_: object) -> dict[str, object]:
            return {
                "schema_version": INTENT_PROPOSAL_SCHEMA_V1,
                "items": [
                    {
                        "concept_code": "USE.GIFT",
                        "requirement": "PREFER",
                        "claim": "unsupported",
                    }
                ],
            }

    with pytest.raises(IntentNormalizationValidationError, match="strict schema"):
        normalize_natural_language_intent(
            NaturalLanguageIntentCommand("선물"),
            proposal_adapter=InvalidProposalAdapter(),
        )


def _projection_intent(source: str, command: dict[str, object]) -> object:
    if source == "NATURAL_LANGUAGE":
        return normalize_natural_language_intent(
            NaturalLanguageIntentCommand(
                query=str(command["query"]),
                locale=str(command.get("locale", "ko-KR")),
                context=str(command.get("context", "ANY")),
            )
        )
    return normalize_canonical_profile_intent(
        CanonicalProfileIntentCommand(
            must_codes=tuple(command.get("must_codes", ())),
            prefer_codes=tuple(command.get("prefer_codes", ())),
            exclude_codes=tuple(command.get("exclude_codes", ())),
            unknown_fields=tuple(command.get("unknown_fields", ())),
        )
    )


def _projection_summary(plan: object) -> dict[str, object]:
    return {
        "retrieval_codes": [item.concept_code for item in plan.retrieval_features],
        "constraints": [
            {
                "concept_code": item.concept_code,
                "operator": item.operator.value,
                "candidate_field": item.candidate_field,
                "verification_mode": item.verification_mode.value,
            }
            for item in plan.hard_filter_constraints
        ],
        "information_required": [
            {
                "concept_code": item.concept_code,
                "reason_code": item.reason_code,
            }
            for item in plan.information_required
        ],
        "deferred_reasons": [item.reason_code for item in plan.deferred],
    }


def test_projection_fixture_preserves_excel_natural_parity_and_filter_boundaries() -> None:
    payload = json.loads(INTENT_PROJECTION_FIXTURE.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "intent-projection-fixture-v1.0"
    groups: dict[str, list[str]] = {}

    for scenario in payload["scenarios"]:
        intent = _projection_intent(scenario["source"], scenario["command"])
        plan = project_intent(intent, catalog_scope=scenario["catalog_scope"])
        assert _projection_summary(plan) == scenario["expected"], scenario["scenario_id"]
        assert plan.ranking_state == PUBLISHED_RANKING_STATE
        assert len(plan.semantic_input_fingerprint) == 64
        assert len(plan.plan_fingerprint) == 64
        assert len(plan.result_fingerprint) == 64
        if scenario.get("parity_group"):
            groups.setdefault(scenario["parity_group"], []).append(
                plan.plan_fingerprint
            )

    assert groups
    assert all(len(values) == 2 and len(set(values)) == 1 for values in groups.values())


def test_unknown_unresolved_and_model_proposals_remain_outside_projection() -> None:
    class ProposalAdapter:
        def propose(self, **_: object) -> dict[str, object]:
            return {
                "schema_version": INTENT_PROPOSAL_SCHEMA_V1,
                "items": [
                    {"concept_code": "USE.GIFT", "requirement": "PREFER"}
                ],
            }

    natural = normalize_natural_language_intent(
        NaturalLanguageIntentCommand("unmapped person@example.com", locale="en-US"),
        proposal_adapter=ProposalAdapter(),
    )
    profile = normalize_canonical_profile_intent(
        CanonicalProfileIntentCommand(unknown_fields=("MOQ",))
    )
    natural_plan = project_intent(
        natural, catalog_scope=CatalogScope.PUBLIC_CATALOG
    )
    profile_plan = project_intent(
        profile, catalog_scope=CatalogScope.VERIFIED_BUYER_CATALOG
    )

    assert natural_plan.retrieval_features == ()
    assert natural_plan.hard_filter_constraints == ()
    assert {item.kind for item in natural_plan.deferred} == {
        "PROPOSAL_ONLY",
        "UNRESOLVED",
    }
    assert {item.reason_code for item in natural_plan.deferred} == {
        "MODEL_PROPOSAL_NOT_CONFIRMED",
        "NO_PUBLISHED_MAPPING",
    }
    assert "person@example.com" not in str(natural_plan.to_dict())
    assert profile_plan.retrieval_features == ()
    assert profile_plan.hard_filter_constraints == ()
    assert profile_plan.deferred[0].kind == "UNKNOWN"
    assert profile_plan.deferred[0].reason_code == "SUBJECT_VALUE_UNKNOWN"


def test_public_scope_never_projects_buyer_only_preferences() -> None:
    intent = normalize_canonical_profile_intent(
        CanonicalProfileIntentCommand(prefer_codes=("CHANNEL.EXPORT",))
    )
    public_plan = project_intent(intent, catalog_scope=CatalogScope.PUBLIC_CATALOG)
    buyer_plan = project_intent(
        intent, catalog_scope=CatalogScope.VERIFIED_BUYER_CATALOG
    )

    assert public_plan.retrieval_features == ()
    assert public_plan.deferred[0].reason_code == "CATALOG_SCOPE_RESTRICTED"
    assert [item.concept_code for item in buyer_plan.retrieval_features] == [
        "CHANNEL.EXPORT"
    ]


def test_projection_rejects_tampered_intent_and_never_calls_ranking() -> None:
    intent = normalize_canonical_profile_intent(
        CanonicalProfileIntentCommand(prefer_codes=("ALCOHOL.TAKJU",))
    )
    with pytest.raises(IntentProjectionValidationError, match="fingerprint"):
        project_intent(
            replace(intent, result_fingerprint="invalid"),
            catalog_scope=CatalogScope.PUBLIC_CATALOG,
        )

    source = inspect.getsource(project_intent)
    assert "execute_matching" not in source
    assert "score_catalog_search" not in source


def test_hard_constraint_declares_unknown_and_missing_as_information_required() -> None:
    intent = normalize_canonical_profile_intent(
        CanonicalProfileIntentCommand(must_codes=("BIZ_GOAL.OEM",))
    )
    plan = project_intent(
        intent, catalog_scope=CatalogScope.VERIFIED_BUYER_CATALOG
    )

    constraint = plan.hard_filter_constraints[0]
    assert constraint.unknown_outcome == "INFORMATION_REQUIRED"
    assert constraint.missing_outcome == "INFORMATION_REQUIRED"


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


def _hybrid_shadow_command(
    vector_state: RecallChannelState = RecallChannelState.AVAILABLE,
) -> HybridRrfShadowCommand:
    return HybridRrfShadowCommand(
        candidate_ids=("candidate-c", "candidate-a", "candidate-b"),
        published_ranking=("candidate-b", "candidate-c", "candidate-a"),
        channels=(
            RecallChannelRanking(
                "VECTOR",
                vector_state,
                ("candidate-a", "candidate-b", "candidate-c")
                if vector_state is RecallChannelState.AVAILABLE
                else (),
            ),
            RecallChannelRanking(
                "KEYWORD", "AVAILABLE", ("candidate-b", "candidate-c")
            ),
            RecallChannelRanking(
                "STRUCTURED", "AVAILABLE", ("candidate-b", "candidate-a")
            ),
        ),
        candidate_signals=(
            CandidateSignalDiagnostics(
                "candidate-a",
                unknown_signals=("minimum_order_quantity",),
            ),
            CandidateSignalDiagnostics(
                "candidate-c",
                missing_signals=("export_market",),
            ),
        ),
    )


def test_hybrid_rrf_is_shadow_only_and_preserves_unknown_boundaries() -> None:
    result = execute_hybrid_rrf_shadow(_hybrid_shadow_command())

    assert result.shadow_only is True
    assert result.promotion_allowed is False
    assert result.published_ranking == (
        "candidate-b",
        "candidate-c",
        "candidate-a",
    )
    assert [item.candidate_id for item in result.shadow_ranking] == [
        "candidate-b",
        "candidate-a",
        "candidate-c",
    ]
    assert all(item.rrf_score is not None for item in result.shadow_ranking)
    candidate_a = next(
        item for item in result.shadow_ranking if item.candidate_id == "candidate-a"
    )
    candidate_c = next(
        item for item in result.shadow_ranking if item.candidate_id == "candidate-c"
    )
    assert candidate_a.unknown_signals == ("minimum_order_quantity",)
    assert candidate_a.channel_ranks["KEYWORD"] is None
    assert candidate_c.missing_signals == ("export_market",)
    assert candidate_c.channel_ranks["STRUCTURED"] is None
    assert result.unknown_signal_count == 1
    assert result.missing_signal_count == 1
    assert len(result.input_fingerprint) == 64
    assert len(result.result_fingerprint) == 64


@pytest.mark.parametrize(
    "vector_state",
    [RecallChannelState.UNAVAILABLE, RecallChannelState.NOT_INVOKED],
)
def test_vector_failure_preserves_published_weighted_order_without_zero_scores(
    vector_state: RecallChannelState,
) -> None:
    result = execute_hybrid_rrf_shadow(_hybrid_shadow_command(vector_state))

    assert result.fallback_applied is True
    assert result.fallback_reason == vector_state.value
    assert tuple(item.candidate_id for item in result.shadow_ranking) == (
        "candidate-b",
        "candidate-c",
        "candidate-a",
    )
    assert all(item.rrf_score is None for item in result.shadow_ranking)


def test_hybrid_shadow_fingerprint_ignores_set_like_input_order() -> None:
    command = _hybrid_shadow_command()
    reordered = HybridRrfShadowCommand(
        candidate_ids=tuple(reversed(command.candidate_ids)),
        published_ranking=command.published_ranking,
        channels=tuple(reversed(command.channels)),
        candidate_signals=tuple(reversed(command.candidate_signals)),
    )

    first = execute_hybrid_rrf_shadow(command)
    second = execute_hybrid_rrf_shadow(reordered)

    assert first.input_fingerprint == second.input_fingerprint
    assert first.result_fingerprint == second.result_fingerprint
    assert first.to_dict() == second.to_dict()


def test_hybrid_shadow_rejects_ambiguous_unknown_and_unavailable_inputs() -> None:
    with pytest.raises(HybridShadowValidationError, match="both UNKNOWN and MISSING"):
        CandidateSignalDiagnostics(
            "candidate-a",
            unknown_signals=("moq",),
            missing_signals=("moq",),
        )

    with pytest.raises(HybridShadowValidationError, match="cannot contain a ranking"):
        RecallChannelRanking("VECTOR", "UNAVAILABLE", ("candidate-a",))
