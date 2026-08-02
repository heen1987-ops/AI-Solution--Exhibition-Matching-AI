from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from app.services.matching.constraint_shadow import (
    HARD_FILTER_SHADOW_ENFORCEMENT,
    build_runtime_constraint_shadow_gate_command,
    evaluate_runtime_constraint_shadow,
    evaluate_runtime_constraint_shadow_gate,
    map_candidate_observations,
    project_runtime_profile,
)
from app.services.matching.engine_adapter import (
    execute_catalog_search_score,
    execute_directional_score,
)
from app.services.matching.explanation_generator import generate_explanations
from app.services.matching.hard_filter import evaluate_hard_filters
from app.services.matching.types import (
    FilterOutcome,
    GoalItem,
    MatchCandidate,
    ResolvedContext,
    ResolvedProfile,
    ShadowParityState,
    SubjectContext,
    TaxonomyItem,
)

from meet_ai.engine import CatalogSearchSignals, MatchingMode
from meet_ai.evaluation import (
    MINIMUM_RUNTIME_COMPARABLE_SAMPLE,
    ConstraintShadowGateCommand,
    ConstraintShadowGateValidationError,
    ConstraintShadowReasonCount,
    ConstraintShadowState,
    ConstraintShadowStateCount,
    evaluate_constraint_shadow_gate,
)
from meet_ai.scoring import EligibilityDecision


def _fixture(name: str) -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "tests" / "fixtures" / "matching" / name
        if candidate.is_file():
            return candidate
    raise RuntimeError(f"matching fixture not found: {name}")


RUNTIME_SHADOW_FIXTURE = _fixture("runtime-constraint-shadow.v1.json")
RUNTIME_SHADOW_PAYLOAD = json.loads(
    RUNTIME_SHADOW_FIXTURE.read_text(encoding="utf-8")
)
RUNTIME_SHADOW_SCENARIOS = RUNTIME_SHADOW_PAYLOAD["scenarios"]
SHADOW_GATE_FIXTURE = _fixture("constraint-shadow-gate.v1.json")
SHADOW_GATE_PAYLOAD = json.loads(SHADOW_GATE_FIXTURE.read_text(encoding="utf-8"))
SHADOW_GATE_SCENARIOS = SHADOW_GATE_PAYLOAD["scenarios"]


def test_backend_catalog_adapter_uses_common_facade_policy() -> None:
    result = execute_catalog_search_score(
        CatalogSearchSignals(0.8, 0.7, 0.6, 0.5, 0.4),
        reason_evidence={
            "SEMANTIC_MATCH": ("query:structured", "candidate:approved_summary"),
            "KEYWORD_MATCH": ("query:tokens", "candidate:approved_document"),
        },
        model_version="embedding-v1",
    )

    assert float(result.normalized_score) == 0.705
    assert result.policy_versions == {"catalog_search": "catalog-search-score-v1.0"}
    assert result.catalog_search_result is not None
    assert [claim.code for claim in result.reason_claims] == [
        "SEMANTIC_MATCH",
        "KEYWORD_MATCH",
    ]


def test_backend_recommendation_adapter_preserves_eligibility_provenance() -> None:
    result = execute_directional_score(
        candidate_id="candidate-a",
        exhibitor_id="exhibitor-a",
        mode=MatchingMode.GENERAL_VISITOR,
        components={"goal": 1.0, "category": 0.8},
        eligibility=EligibilityDecision(True, "filter-evaluation-a"),
        confidence=0.9,
        reason_evidence={
            "GOAL_MATCH": ("profile:goal", "candidate:usage"),
            "CATEGORY_MATCH": ("profile:category", "candidate:category"),
        },
    )

    assert result.eligibility_evaluation_id == "filter-evaluation-a"
    assert result.policy_versions == {"consumer": "consumer-score-v1.0"}
    assert result.directional_result is not None
    assert result.calculation_fingerprint
    assert {claim.code for claim in result.reason_claims} == {
        "GOAL_MATCH",
        "CATEGORY_MATCH",
    }


def test_runtime_explanation_projects_facade_claims_not_raw_feature_rank() -> None:
    profile = ResolvedProfile(
        profile_id=uuid.uuid4(),
        profile_version=1,
        profile_version_id=uuid.uuid4(),
        user_type="GENERAL_VISITOR",
        completeness=80,
        goals=[],
        categories=[],
        channels=[],
        regions=[],
        taste=[],
        aroma=[],
        extra={},
        numeric_conditions={},
        raw_context={},
    )
    candidate = MatchCandidate(
        object_type="PRODUCT",
        object_id=uuid.uuid4(),
        recommendable_id=uuid.uuid4(),
        exhibitor_id=uuid.uuid4(),
        participation_id=uuid.uuid4(),
        public_object_id="product-runtime-reason",
        features={"taste_match": 1.0, "category_match": 0.8},
        directional_policy_version="consumer-score-v1.0",
        directional_contributions={"category": 0.2},
    )

    generate_explanations([candidate], profile=profile)

    assert [reason.code for reason in candidate.reasons] == ["CATEGORY_MATCH"]
    assert set(candidate.reasons[0].evidence_refs) == {
        f"profile:{profile.profile_id}:v1",
        f"product:{candidate.object_id}:category_match",
    }


def _subject() -> SubjectContext:
    profile_id = uuid.uuid4()
    return SubjectContext(
        tenant_id=uuid.uuid4(),
        event_id=uuid.uuid4(),
        profile_id=profile_id,
        visit_session_id=None,
        user_id=uuid.uuid4(),
        guest_session_id=None,
        request_id="req-constraint-shadow",
        idempotency_key=None,
        server_time=datetime(2026, 8, 3, tzinfo=UTC),
    )


def _context(subject: SubjectContext) -> ResolvedContext:
    return ResolvedContext(
        current_zone=None,
        current_zone_id=None,
        remaining_minutes=None,
        visited_booth_ids=set(),
        upcoming_meetings=[],
        upcoming_meeting_booth_ids=set(),
        operational_snapshot_version=1,
        exclude_visited=False,
        include_meetings=False,
        avoid_congestion=False,
        server_time=subject.server_time,
    )


def _buyer_profile(subject: SubjectContext) -> ResolvedProfile:
    return ResolvedProfile(
        profile_id=subject.profile_id,
        profile_version=1,
        profile_version_id=uuid.uuid4(),
        user_type="BUYER",
        completeness=90,
        goals=[GoalItem("BIZ_GOAL.OEM", 1, "REQUIRED", 1.0, "USER_INPUT")],
        categories=[],
        channels=[],
        regions=[],
        taste=[],
        aroma=[],
        extra={},
        numeric_conditions={},
        raw_context={},
    )


def _general_profile(
    subject: SubjectContext, *, category_level: str | None = None
) -> ResolvedProfile:
    return ResolvedProfile(
        profile_id=subject.profile_id,
        profile_version=1,
        profile_version_id=uuid.uuid4(),
        user_type="GENERAL_VISITOR",
        completeness=90,
        goals=[],
        categories=(
            [TaxonomyItem("ALCOHOL.TAKJU", category_level, 1.0)]
            if category_level
            else []
        ),
        channels=[],
        regions=[],
        taste=[],
        aroma=[],
        extra={},
        numeric_conditions={},
        raw_context={},
    )


def _exhibitor_candidate(
    status: str | None,
    *,
    state: str | None = None,
    object_id: uuid.UUID | None = None,
) -> MatchCandidate:
    trade_profile: dict[str, object] = {
        "channels": [],
        "regions": [],
    }
    if status is not None:
        trade_profile["oem_status"] = status
    candidate_id = object_id or uuid.uuid4()
    payload: dict[str, object] = {
        "master_approval_status": "APPROVED",
        "participation_status": "ACTIVE",
        "consultation_enabled": True,
        "supply_profile": {
            "approval_status": "APPROVED",
            "business_types": [],
            "trade_profile": trade_profile,
        },
    }
    if state is not None:
        payload["observation_states"] = {
            "supply_profile.trade_profile.oem_status": state
        }
    return MatchCandidate(
        object_type="EXHIBITOR",
        object_id=candidate_id,
        recommendable_id=uuid.uuid4(),
        exhibitor_id=candidate_id,
        participation_id=uuid.uuid4(),
        public_object_id=str(candidate_id),
        payload=payload,
    )


def _product_candidate(
    category_code: str,
    *,
    approved: bool = True,
    object_id: uuid.UUID | None = None,
) -> MatchCandidate:
    candidate_id = object_id or uuid.uuid4()
    return MatchCandidate(
        object_type="PRODUCT",
        object_id=candidate_id,
        recommendable_id=uuid.uuid4(),
        exhibitor_id=uuid.uuid4(),
        participation_id=uuid.uuid4(),
        public_object_id=str(candidate_id),
        payload={
            "category_code": category_code,
            "approval_status": "APPROVED",
            "master_approval_status": "APPROVED" if approved else "PENDING",
            "participation_status": "ACTIVE",
        },
    )


def _evaluate_shadow(
    candidate: MatchCandidate,
    profile: ResolvedProfile,
    subject: SubjectContext,
):
    return evaluate_hard_filters(
        candidates=[candidate],
        subject=subject,
        profile=profile,
        context=_context(subject),
        excluded_recommendable_ids=set(),
    )


@pytest.mark.parametrize(
    "scenario",
    RUNTIME_SHADOW_SCENARIOS,
    ids=[item["scenario_id"] for item in RUNTIME_SHADOW_SCENARIOS],
)
def test_runtime_constraint_shadow_preserves_trade_information_states(
    scenario: dict[str, object],
) -> None:
    assert (
        RUNTIME_SHADOW_PAYLOAD["schema_version"]
        == "runtime-constraint-shadow-fixture-v1.0"
    )
    subject = _subject()
    evaluation = _evaluate_shadow(
        _exhibitor_candidate(
            scenario["status"] if isinstance(scenario["status"], str) else None,
            state=scenario["state"] if isinstance(scenario["state"], str) else None,
        ),
        _buyer_profile(subject),
        subject,
    )

    shadow = evaluation.constraint_shadow[0]
    assert evaluation.outcomes[0].passed is scenario["legacy_passed"]
    assert shadow.projected_outcome == scenario["projected_outcome"]
    assert shadow.parity_state.value == scenario["parity_state"]
    assert scenario["reason_code"] in shadow.reason_codes
    assert shadow.enforcement_enabled is HARD_FILTER_SHADOW_ENFORCEMENT is False
    assert len(shadow.shadow_fingerprint) == 64


def test_approved_public_and_verified_buyer_fields_map_to_one_engine_contract() -> None:
    subject = _subject()
    profile = _buyer_profile(subject)
    profile.categories = [TaxonomyItem("ALCOHOL.TAKJU", "REQUIRED", 1.0)]
    profile.channels = [TaxonomyItem("CHANNEL.OFFLINE_RETAIL", "REQUIRED", 1.0)]
    profile.regions = [TaxonomyItem("REGION.KR.SEOUL", "REQUIRED", 1.0)]
    profile.taste = [TaxonomyItem("TASTE.DRY", "REQUIRED", 1.0)]
    profile.aroma = [TaxonomyItem("AROMA.FRUIT", "REQUIRED", 1.0)]
    profile.extra = {
        "use_case": [TaxonomyItem("USE.GIFT", "REQUIRED", 1.0)],
        "product_feature": [
            TaxonomyItem("FEATURE.PREMIUM", "REQUIRED", 1.0)
        ],
        "booth_service": [
            TaxonomyItem("SERVICE.TASTING", "REQUIRED", 1.0)
        ],
        "alcohol_level": [
            TaxonomyItem("ALCOHOL_LEVEL.LOW", "REQUIRED", 1.0)
        ],
        "trade_type": [
            TaxonomyItem("TRADE.REGULAR_SUPPLY", "REQUIRED", 1.0)
        ],
    }
    candidate = _product_candidate("ALCOHOL.TAKJU")
    candidate.payload.update(
        {
            "taste_json": {"TASTE.DRY": 5},
            "aroma_json": {"AROMA.FRUIT": 4},
            "usage_json": ["USE.GIFT"],
            "feature_json": ["FEATURE.PREMIUM"],
            "tasting_status": "AVAILABLE",
            "alcohol_percentage": 7.0,
            "supply_profile": {
                "approval_status": "APPROVED",
                "business_types": ["TRADE.REGULAR_SUPPLY"],
                "trade_profile": {
                    "channels": ["CHANNEL.OFFLINE_RETAIL"],
                    "regions": ["REGION.KR.SEOUL"],
                    "oem_status": "YES",
                },
            },
        }
    )

    plan = project_runtime_profile(profile)
    observations, reasons = map_candidate_observations(candidate, plan)

    assert reasons == ()
    assert {item.candidate_field for item in observations} == {
        "candidate.category_codes",
        "candidate.taste_codes",
        "candidate.aroma_codes",
        "candidate.usage_codes",
        "candidate.feature_codes",
        "candidate.service_codes",
        "candidate.alcohol_percentage",
        "supply_profile.trade_profile.channels",
        "supply_profile.trade_profile.regions",
        "supply_profile.business_types",
        "supply_profile.trade_profile.oem_status",
    }
    assert all(item.state.value == "KNOWN" for item in observations)

    evaluation = _evaluate_shadow(candidate, profile, subject)
    shadow = evaluation.constraint_shadow[0]
    assert shadow.projected_outcome == "ELIGIBLE"
    assert shadow.parity_state is ShadowParityState.PARITY


def test_public_exclusion_gap_is_measured_without_changing_runtime_admission() -> None:
    subject = _subject()
    candidate = _product_candidate("ALCOHOL.TAKJU")
    evaluation = _evaluate_shadow(
        candidate,
        _general_profile(subject, category_level="EXCLUDED"),
        subject,
    )

    shadow = evaluation.constraint_shadow[0]
    assert evaluation.eligible_candidates == [candidate]
    assert shadow.projected_outcome == "FILTERED_OUT"
    assert shadow.parity_state is ShadowParityState.SAFETY_GAP
    assert "LEGACY_PASSED_PROJECTED_VIOLATION" in shadow.reason_codes


def test_unapproved_data_is_not_mapped_into_shadow_observations() -> None:
    subject = _subject()
    evaluation = _evaluate_shadow(
        _product_candidate("ALCOHOL.TAKJU", approved=False),
        _general_profile(subject, category_level="REQUIRED"),
        subject,
    )

    shadow = evaluation.constraint_shadow[0]
    assert evaluation.outcomes[0].filter_code == "ADMIN_NOT_APPROVED"
    assert shadow.projected_outcome == "INFORMATION_REQUIRED"
    assert shadow.parity_state is ShadowParityState.NOT_COMPARABLE
    assert "PUBLIC_CATALOG_NOT_APPROVED" in shadow.reason_codes


def test_invalid_candidate_observation_does_not_break_authoritative_filter() -> None:
    subject = _subject()
    candidate = _product_candidate("MADE.UP")
    evaluation = _evaluate_shadow(
        candidate,
        _general_profile(subject, category_level="REQUIRED"),
        subject,
    )

    shadow = evaluation.constraint_shadow[0]
    assert evaluation.eligible_candidates == [candidate]
    assert shadow.parity_state is ShadowParityState.ADAPTER_ERROR
    assert shadow.reason_codes == ("CANDIDATE_OBSERVATION_INVALID",)


def test_shadow_marks_a_comparable_legacy_decision_not_reproduced_as_divergence() -> None:
    subject = _subject()
    profile = _buyer_profile(subject)
    candidate = _exhibitor_candidate("CONDITIONAL")
    legacy = FilterOutcome(
        filter_evaluation_id=uuid.uuid4(),
        object_id=candidate.object_id,
        object_type=candidate.object_type,
        recommendable_id=candidate.recommendable_id,
        passed=False,
        filter_code="OEM_MISMATCH",
    )

    shadow = evaluate_runtime_constraint_shadow(
        profile=profile,
        candidates=(candidate,),
        legacy_outcomes=(legacy,),
    )[0]

    assert shadow.projected_outcome == "INFORMATION_REQUIRED"
    assert shadow.parity_state is ShadowParityState.DIVERGENCE
    assert "LEGACY_FILTER_NOT_REPRODUCED" in shadow.reason_codes


def test_shadow_output_omits_private_values_and_is_order_reproducible() -> None:
    subject = _subject()
    profile = _buyer_profile(subject)
    first_id = uuid.uuid4()
    second_id = uuid.uuid4()
    first_candidate = _exhibitor_candidate("NEGOTIABLE", object_id=first_id)
    second_candidate = _exhibitor_candidate("UNKNOWN", object_id=second_id)

    first = evaluate_hard_filters(
        candidates=[first_candidate, second_candidate],
        subject=subject,
        profile=profile,
        context=_context(subject),
        excluded_recommendable_ids=set(),
    )
    second = evaluate_hard_filters(
        candidates=[second_candidate, first_candidate],
        subject=subject,
        profile=profile,
        context=_context(subject),
        excluded_recommendable_ids=set(),
    )
    first_fingerprints = {
        item.candidate_ref: item.shadow_fingerprint for item in first.constraint_shadow
    }
    second_fingerprints = {
        item.candidate_ref: item.shadow_fingerprint for item in second.constraint_shadow
    }
    serialized = str(first.constraint_shadow[0].to_dict())

    assert first_fingerprints == second_fingerprints
    assert "NEGOTIABLE" not in serialized
    assert "status_value" not in serialized
    assert "supply_profile" not in serialized


def test_profile_without_hard_conditions_is_explicitly_not_applicable() -> None:
    subject = _subject()
    evaluation = _evaluate_shadow(
        _product_candidate("ALCOHOL.TAKJU"),
        _general_profile(subject),
        subject,
    )

    shadow = evaluation.constraint_shadow[0]
    assert shadow.parity_state is ShadowParityState.NOT_APPLICABLE
    assert shadow.projected_outcome is None
    assert shadow.reason_codes == ("NO_PROJECTED_HARD_CONSTRAINTS",)


def _shadow_gate_command(scenario: dict[str, object]) -> ConstraintShadowGateCommand:
    raw_state_counts = scenario["state_counts"]
    raw_reason_counts = scenario["safety_gap_reason_counts"]
    assert isinstance(raw_state_counts, dict)
    assert isinstance(raw_reason_counts, dict)
    return ConstraintShadowGateCommand(
        sample_window_ref=str(scenario["sample_window_ref"]),
        state_counts=tuple(
            ConstraintShadowStateCount(ConstraintShadowState(state), int(count))
            for state, count in raw_state_counts.items()
        ),
        safety_gap_reason_counts=tuple(
            ConstraintShadowReasonCount(reason_code, int(count))
            for reason_code, count in raw_reason_counts.items()
        ),
        source_policy_versions=tuple(SHADOW_GATE_PAYLOAD["source_policy_versions"]),
        regression_evidence_refs=tuple(scenario["regression_evidence_refs"]),
        rollback_evidence_refs=tuple(scenario["rollback_evidence_refs"]),
        safety_gap_review_evidence_refs=tuple(
            scenario["safety_gap_review_evidence_refs"]
        ),
    )


@pytest.mark.parametrize(
    "scenario",
    SHADOW_GATE_SCENARIOS,
    ids=[item["scenario_id"] for item in SHADOW_GATE_SCENARIOS],
)
def test_constraint_shadow_gate_fixture_is_reproducible_and_fail_closed(
    scenario: dict[str, object],
) -> None:
    assert (
        SHADOW_GATE_PAYLOAD["schema_version"]
        == "constraint-shadow-gate-fixture-v1.0"
    )
    command = _shadow_gate_command(scenario)
    result = evaluate_constraint_shadow_gate(command)
    reordered = ConstraintShadowGateCommand(
        sample_window_ref=command.sample_window_ref,
        state_counts=tuple(reversed(command.state_counts)),
        safety_gap_reason_counts=tuple(reversed(command.safety_gap_reason_counts)),
        source_policy_versions=tuple(reversed(command.source_policy_versions)),
        regression_evidence_refs=tuple(reversed(command.regression_evidence_refs)),
        rollback_evidence_refs=tuple(reversed(command.rollback_evidence_refs)),
        safety_gap_review_evidence_refs=tuple(
            reversed(command.safety_gap_review_evidence_refs)
        ),
    )
    repeated = evaluate_constraint_shadow_gate(reordered)

    assert result.outcome.value == scenario["expected_outcome"]
    assert list(result.blocker_reason_codes) == scenario["expected_blockers"]
    assert result.comparable_sample_count == scenario["expected_comparable_sample_count"]
    assert result.change_request_ready is scenario["expected_change_request_ready"]
    assert result.enforcement_allowed is False
    assert result.minimum_runtime_comparable_sample == 1000
    assert result.input_fingerprint == repeated.input_fingerprint
    assert result.result_fingerprint == repeated.result_fingerprint


def test_runtime_shadow_gate_adapter_aggregates_without_candidate_data() -> None:
    subject = _subject()
    profile = _buyer_profile(subject)
    shadow = _evaluate_shadow(
        _exhibitor_candidate("NEGOTIABLE"), profile, subject
    ).constraint_shadow[0]
    shadows = (shadow,) * MINIMUM_RUNTIME_COMPARABLE_SAMPLE

    command = build_runtime_constraint_shadow_gate_command(
        shadows,
        sample_window_ref="runtime:20260803-window-001",
        regression_evidence_refs=("report:backend-regression-20260803",),
        rollback_evidence_refs=("runbook:constraint-shadow-rollback-v1",),
        safety_gap_review_evidence_refs=("report:safety-gap-review-20260803",),
    )
    result = evaluate_runtime_constraint_shadow_gate(
        shadows,
        sample_window_ref="runtime:20260803-window-001",
        regression_evidence_refs=("report:backend-regression-20260803",),
        rollback_evidence_refs=("runbook:constraint-shadow-rollback-v1",),
        safety_gap_review_evidence_refs=("report:safety-gap-review-20260803",),
    )
    serialized = json.dumps(result.to_dict(), sort_keys=True)

    assert result.outcome.value == "INSUFFICIENT_EVIDENCE"
    assert result.change_request_ready is False
    assert result.enforcement_allowed is False
    assert sum(item.count for item in command.state_counts) == 1
    assert result.duplicate_shadow_count == 999
    assert "MINIMUM_RUNTIME_SAMPLE_NOT_MET" in result.blocker_reason_codes
    assert shadow.candidate_ref not in serialized
    assert "NEGOTIABLE" not in serialized
    assert "supply_profile" not in serialized


def test_constraint_shadow_gate_rejects_incomplete_or_unsafe_aggregates() -> None:
    with pytest.raises(
        ConstraintShadowGateValidationError,
        match="cover every shadow state",
    ):
        ConstraintShadowGateCommand(
            sample_window_ref="fixture:invalid",
            state_counts=(
                ConstraintShadowStateCount(ConstraintShadowState.PARITY, 1),
            ),
            safety_gap_reason_counts=(),
            source_policy_versions=("hard-filter-shadow-v1.0",),
        )

    with pytest.raises(
        ConstraintShadowGateValidationError,
        match="opaque reference",
    ):
        ConstraintShadowGateCommand(
            sample_window_ref="visitor@example.com",
            state_counts=tuple(
                ConstraintShadowStateCount(state, 0)
                for state in ConstraintShadowState
            ),
            safety_gap_reason_counts=(),
            source_policy_versions=("hard-filter-shadow-v1.0",),
        )
