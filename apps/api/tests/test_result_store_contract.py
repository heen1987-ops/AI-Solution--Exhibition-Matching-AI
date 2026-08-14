from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from app.models.matching import (
    MatchReason,
    MatchResult,
    MatchRun,
    SlateItem,
    SlateResult,
)
from app.services.matching.errors import RecommendationError
from app.services.matching.result_store import EXPLANATION_VERSION, store_recommendation
from app.services.matching.types import (
    MatchCandidate,
    MatchReasonDraft,
    PipelineTrace,
    ResolvedContext,
    ResolvedProfile,
    SubjectContext,
    ValidatedRequest,
)


class _QueryResult:
    def __init__(self, *, first: Any = None, scalar: Any = None) -> None:
        self._first = first
        self._scalar = scalar

    def first(self) -> Any:
        return self._first

    def scalar_one_or_none(self) -> Any:
        return self._scalar


class _FakeSession:
    def __init__(self, *, missing_policy: bool = False) -> None:
        self.added: list[Any] = []
        self.commit_count = 0
        self.missing_policy = missing_policy
        self.taxonomy_version_id = uuid.uuid4()
        self.model_version_id = uuid.uuid4()
        self.policy_version_id = uuid.uuid4()

    async def execute(self, statement: Any, params: Any = None) -> _QueryResult:
        del params
        if statement.__class__.__name__ == "TextClause":
            return _QueryResult(first=(self.taxonomy_version_id,))
        entity = statement.column_descriptions[0].get("entity")
        if getattr(entity, "__name__", None) == "ModelVersion":
            return _QueryResult(
                scalar=SimpleNamespace(model_version_id=self.model_version_id)
            )
        if getattr(entity, "__name__", None) == "MatchPolicyVersion":
            scalar = None
            if not self.missing_policy:
                scalar = SimpleNamespace(match_policy_version_id=self.policy_version_id)
            return _QueryResult(scalar=scalar)
        raise AssertionError(f"unexpected statement: {statement}")

    def add(self, row: Any) -> None:
        self.added.append(row)

    async def flush(self) -> None:
        for row in self.added:
            if isinstance(row, MatchResult) and row.match_result_id is None:
                row.match_result_id = uuid.uuid4()
            if isinstance(row, SlateResult) and row.slate_result_id is None:
                row.slate_result_id = uuid.uuid4()

    async def commit(self) -> None:
        self.commit_count += 1


def _request_data() -> tuple[
    ValidatedRequest, ResolvedProfile, ResolvedContext, MatchCandidate, PipelineTrace
]:
    now = datetime(2026, 8, 1, 12, tzinfo=UTC)
    subject = SubjectContext(
        tenant_id=uuid.uuid4(),
        event_id=uuid.uuid4(),
        profile_id=uuid.uuid4(),
        visit_session_id=None,
        user_id=None,
        guest_session_id=uuid.uuid4(),
        request_id="req-result-store-001",
        idempotency_key="idem-result-store-001",
        server_time=now,
    )
    validated = ValidatedRequest(
        subject=subject,
        request_valid=True,
        user_type="GENERAL_VISITOR",
        recommendation_type="PRODUCT",
        limit=5,
        context_input={},
        missing_fields=[],
        policy_route="CONSUMER",
    )
    profile = ResolvedProfile(
        profile_id=subject.profile_id,
        profile_version=2,
        profile_version_id=uuid.uuid4(),
        user_type="GENERAL_VISITOR",
        completeness=90,
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
    context = ResolvedContext(
        current_zone="A",
        current_zone_id=uuid.uuid4(),
        remaining_minutes=60,
        visited_booth_ids=set(),
        upcoming_meetings=[],
        upcoming_meeting_booth_ids=set(),
        operational_snapshot_version=3,
        exclude_visited=True,
        include_meetings=True,
        avoid_congestion=False,
        server_time=now,
    )
    object_id = uuid.uuid4()
    candidate = MatchCandidate(
        object_type="PRODUCT",
        object_id=object_id,
        recommendable_id=uuid.uuid4(),
        exhibitor_id=uuid.uuid4(),
        participation_id=uuid.uuid4(),
        public_object_id=str(object_id),
        filter_evaluation_id=str(uuid.uuid4()),
        raw_score=0.92,
        normalized_score=0.90,
        final_score=0.86,
        rank=1,
        directional_policy_version="consumer-score-v1.0",
        directional_components={"goal": 1.0, "category": 0.8},
        directional_effective_weights={"goal": 0.5, "category": 0.5},
        directional_contributions={"goal": 50.0, "category": 40.0},
        directional_missing_components=("sensory",),
        directional_confidence=0.88,
        directional_grade="R5",
        directional_score_fingerprint="a" * 64,
        context_policy_version="context-rerank-v1.0",
        context_components={"operational_availability": 1.0},
        context_effective_weights={"operational_availability": 1.0},
        context_contributions={"operational_availability": 1.0},
        context_missing_components=("proximity",),
        context_input_fingerprint="b" * 64,
        context_score_fingerprint="c" * 64,
        context_blended_score=0.86,
        cold_start_policy_version="cold-start-policy-v1.0",
        cold_start_state="WARMING",
        cold_start_quality_score=0.82,
        recommendation_confidence=0.72,
        cold_start_reason_codes=("MISSING_AWARE",),
        cold_start_input_fingerprint="1" * 64,
        slate_policy_version="slate-policy-v1.0",
        slate_base_rank=1,
        slate_score=0.87,
        mmr_score=0.81,
        fairness_adjustment=0.01,
        slot_type="CORE",
        slate_reason_codes=("CORE_RELEVANCE", "EXPOSURE_DEFICIT"),
        related_object_ids=("related-product-001",),
        slate_input_fingerprint="d" * 64,
        slate_score_fingerprint="e" * 64,
        score_components={
            "preference_score": 0.8,
            "goal_score": 1.0,
            "trade_score": None,
            "context_score": 0.7,
            "behavior_score": None,
            "trust_score": 0.9,
        },
        recommended_action="VISIT_NOW",
        reasons=[
            MatchReasonDraft(
                code="CATEGORY_MATCH",
                text="관심 있으신 주종과 일치합니다.",
                evidence_refs=[
                    f"profile:{subject.profile_id}:v2",
                    f"product:{object_id}:category_match",
                ],
                contribution_score=0.8,
                generated_by="TEMPLATE",
                explanation_policy_version=EXPLANATION_VERSION,
                input_fingerprint="3" * 64,
            )
        ],
    )
    trace = PipelineTrace(
        candidate_count=4,
        filtered_count=2,
        result_count=1,
        source_channel_counts={"CATEGORY": 4},
        latency_ms={"total": 37},
        slate_policy_version="slate-policy-v1.0",
        slate_input_fingerprint="f" * 64,
        slate_score_fingerprint="0" * 64,
        slate_metrics={
            "diversity_score": 0.42,
            "category_coverage": 0.75,
            "exposure_fairness_score": 0.83,
            "relevance_loss_top10": 0.02,
        },
        cold_start_policy_version="cold-start-policy-v1.0",
        cold_start_input_fingerprint="2" * 64,
        cold_start_metrics={
            "state": "WARMING",
            "exploration_ratio": 0.15,
        },
    )
    return validated, profile, context, candidate, trace


@pytest.mark.asyncio
async def test_store_uses_real_registry_ids_and_commits_once() -> None:
    validated, profile, context, candidate, trace = _request_data()
    session = _FakeSession()

    outcome = await store_recommendation(
        session,  # type: ignore[arg-type]
        validated=validated,
        profile=profile,
        context=context,
        candidates=[candidate],
        trace=trace,
    )

    assert session.commit_count == 1
    run = next(row for row in session.added if isinstance(row, MatchRun))
    result = next(row for row in session.added if isinstance(row, MatchResult))
    slate_result = next(row for row in session.added if isinstance(row, SlateResult))
    slate_item = next(row for row in session.added if isinstance(row, SlateItem))
    reason = next(row for row in session.added if isinstance(row, MatchReason))
    assert run.filter_evaluation_id == uuid.UUID(candidate.filter_evaluation_id)
    assert run.policy_version_id == session.policy_version_id
    assert run.ranking_model_version_id == session.model_version_id
    assert result.directional_policy_version_id == session.policy_version_id
    assert result.tenant_id == validated.subject.tenant_id
    assert result.event_id == validated.subject.event_id
    assert result.directional_score_fingerprint == "a" * 64
    assert result.context_policy_version_id == session.policy_version_id
    assert result.context_input_fingerprint == "b" * 64
    assert result.context_score_fingerprint == "c" * 64
    assert result.normalized_score == 0.90
    assert result.final_score == 0.86
    assert result.context_details["distance_meters"] is None
    assert result.context_details["availability"] == {}
    assert result.context_details["policy_version"] == "context-rerank-v1.0"
    assert result.context_details["context_blended_score"] == 0.86
    assert result.cold_start_policy_version_id == session.policy_version_id
    assert result.cold_start_details["state"] == "WARMING"
    assert result.cold_start_details["input_fingerprint"] == "1" * 64
    assert result.recommendation_confidence == 0.72
    assert reason.explanation_policy_version == EXPLANATION_VERSION
    assert reason.input_fingerprint == "3" * 64
    assert reason.evidence_refs == [
        f"profile:{profile.profile_id}:v2",
        f"product:{candidate.object_id}:category_match",
    ]
    assert slate_result.slate_policy_version_id == session.policy_version_id
    assert slate_result.input_fingerprint == "f" * 64
    assert slate_result.score_fingerprint == "0" * 64
    assert slate_result.relevance_loss == 0.02
    assert slate_item.match_result_id == result.match_result_id
    assert slate_item.slate_result_id == slate_result.slate_result_id
    assert slate_item.base_rank == 1
    assert slate_item.final_rank == 1
    assert slate_item.slot_type == "CORE"
    assert slate_item.related_object_ids == ["related-product-001"]
    assert candidate.match_result_id == result.match_result_id
    assert outcome.policy_version == "consumer-score-v1.0"


@pytest.mark.asyncio
async def test_missing_published_policy_never_reports_success() -> None:
    validated, profile, context, candidate, trace = _request_data()
    session = _FakeSession(missing_policy=True)

    with pytest.raises(RecommendationError) as raised:
        await store_recommendation(
            session,  # type: ignore[arg-type]
            validated=validated,
            profile=profile,
            context=context,
            candidates=[candidate],
            trace=trace,
        )

    assert raised.value.code == "PERSISTENCE_CONTRACT_VIOLATION"
    assert session.commit_count == 0
    assert session.added == []


@pytest.mark.asyncio
async def test_unregistered_candidate_is_not_silently_skipped() -> None:
    validated, profile, context, candidate, trace = _request_data()
    candidate.recommendable_id = None
    session = _FakeSession()

    with pytest.raises(RecommendationError) as raised:
        await store_recommendation(
            session,  # type: ignore[arg-type]
            validated=validated,
            profile=profile,
            context=context,
            candidates=[candidate],
            trace=trace,
        )

    assert raised.value.code == "PERSISTENCE_CONTRACT_VIOLATION"
    assert session.commit_count == 0
