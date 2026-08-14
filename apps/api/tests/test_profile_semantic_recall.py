from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.services.matching import candidate_generator
from app.services.matching.candidate_generator import (
    VECTOR_OBJECTS_PER_PARTICIPATION,
    _apply_vector_recall,
)
from app.services.matching.profile_semantic_recall import (
    ProfileSemanticRecall,
    build_profile_semantic_query,
    profile_semantic_fingerprint,
    recall_profile_participations,
)
from app.services.matching.semantic_search import (
    PreparedSemanticQuery,
    SemanticScoreBatch,
)
from app.services.matching.types import (
    GoalItem,
    MatchCandidate,
    ResolvedContext,
    ResolvedProfile,
    SubjectContext,
    TaxonomyItem,
    ValidatedRequest,
)


def _item(code: str, level: str = "PREFERRED") -> TaxonomyItem:
    return TaxonomyItem(code=code, level=level, confidence=0.9)


def _profile(*, reverse: bool = False, empty: bool = False) -> ResolvedProfile:
    goals = (
        []
        if empty
        else [
            GoalItem(
                code="GOAL.TASTING",
                priority=2,
                requirement_level="PREFERRED",
                confidence=0.8,
                source="USER_INPUT",
            ),
            GoalItem(
                code="GOAL.GIFT_SEARCH",
                priority=1,
                requirement_level="REQUIRED",
                confidence=1.0,
                source="USER_INPUT",
            ),
        ]
    )
    categories = (
        []
        if empty
        else [
            _item("ALCOHOL.TAKJU", "PREFERRED"),
            _item("ALCOHOL.YAKJU", "REQUIRED"),
            _item("ALCOHOL.BEER", "EXCLUDED"),
            _item("FREEFORM.secret-value", "PREFERRED"),
        ]
    )
    if reverse:
        goals.reverse()
        categories.reverse()
    return ResolvedProfile(
        profile_id=uuid.uuid4(),
        profile_version=7,
        profile_version_id=uuid.uuid4(),
        user_type="BUYER",
        completeness=85.0,
        goals=goals,
        categories=categories,
        channels=[],
        regions=[],
        taste=[] if empty else [_item("TASTE.SWEET")],
        aroma=[],
        extra={},
        numeric_conditions={"moq_max": 1200, "wholesale_price_max": 50000},
        raw_context={
            "email": "private-person@example.com",
            "company_registration_number": "123-45-67890",
        },
    )


def test_profile_semantic_query_is_stable_and_privacy_minimized() -> None:
    first = build_profile_semantic_query(_profile())
    second = build_profile_semantic_query(_profile(reverse=True))

    assert first == second
    assert profile_semantic_fingerprint(first) == profile_semantic_fingerprint(second)
    assert "GOAL.GIFT_SEARCH" in first
    assert "ALCOHOL.YAKJU" in first
    assert "ALCOHOL.BEER" not in first
    assert "FREEFORM.secret-value" not in first
    assert "private-person@example.com" not in first
    assert "123-45-67890" not in first
    assert "50000" not in first


class _RecordingSemanticScorer:
    def __init__(self, participation_id: uuid.UUID) -> None:
        self.participation_id = participation_id
        self.model_version_id = uuid.uuid4()
        self.query: str | None = None
        self.score_call: tuple[uuid.UUID, uuid.UUID, str] | None = None

    async def prepare(self, *, query: str) -> PreparedSemanticQuery:
        self.query = query
        return PreparedSemanticQuery((1.0, 0.0), "AVAILABLE", self.model_version_id)

    async def score(
        self,
        db: object,
        *,
        tenant_id: uuid.UUID,
        event_id: uuid.UUID,
        language: str,
        prepared: PreparedSemanticQuery,
    ) -> SemanticScoreBatch:
        del db
        assert prepared.status == "AVAILABLE"
        self.score_call = tenant_id, event_id, language
        return SemanticScoreBatch(
            {self.participation_id: 0.82},
            "AVAILABLE",
            self.model_version_id,
        )


@pytest.mark.asyncio
async def test_profile_recall_delegates_to_versioned_semantic_adapter() -> None:
    tenant_id = uuid.uuid4()
    event_id = uuid.uuid4()
    participation_id = uuid.uuid4()
    scorer = _RecordingSemanticScorer(participation_id)

    recall = await recall_profile_participations(
        object(),  # type: ignore[arg-type]
        tenant_id=tenant_id,
        event_id=event_id,
        profile=_profile(),
        semantic_scorer=scorer,
    )

    assert scorer.query == build_profile_semantic_query(_profile())
    assert scorer.score_call == (tenant_id, event_id, "ko")
    assert recall.status == "AVAILABLE"
    assert recall.participation_scores == {participation_id: 0.82}
    assert recall.model_version_id == scorer.model_version_id


class _MustNotRunScorer:
    async def prepare(self, *, query: str) -> PreparedSemanticQuery:
        raise AssertionError(f"empty profile must not be embedded: {query}")

    async def score(self, *args: object, **kwargs: object) -> SemanticScoreBatch:
        raise AssertionError((args, kwargs))


@pytest.mark.asyncio
async def test_empty_profile_disables_semantic_recall_without_provider_call() -> None:
    recall = await recall_profile_participations(
        object(),  # type: ignore[arg-type]
        tenant_id=uuid.uuid4(),
        event_id=uuid.uuid4(),
        profile=_profile(empty=True),
        semantic_scorer=_MustNotRunScorer(),
    )

    assert recall.status == "DISABLED"
    assert recall.participation_scores == {}


def _candidate(participation_id: uuid.UUID, *, quality: float) -> MatchCandidate:
    object_id = uuid.uuid4()
    return MatchCandidate(
        object_type="PRODUCT",
        object_id=object_id,
        recommendable_id=uuid.uuid4(),
        exhibitor_id=uuid.uuid4(),
        participation_id=participation_id,
        public_object_id=str(object_id),
        payload={"buyer_score": quality},
    )


@pytest.mark.asyncio
async def test_candidate_generator_connects_profile_recall_to_vector_channel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid.uuid4()
    event_id = uuid.uuid4()
    participation_id = uuid.uuid4()
    scorer = _RecordingSemanticScorer(participation_id)
    candidate = _candidate(participation_id, quality=70)

    async def fake_fetch(*args: object, **kwargs: object) -> list[MatchCandidate]:
        del args, kwargs
        return [candidate]

    async def fake_supply(*args: object, **kwargs: object) -> dict[uuid.UUID, dict]:
        del args, kwargs
        return {}

    async def fake_interest(*args: object, **kwargs: object) -> set[uuid.UUID]:
        del args, kwargs
        return set()

    monkeypatch.setattr(candidate_generator, "_fetch_product_candidates", fake_fetch)
    monkeypatch.setattr(candidate_generator, "_load_supply_profiles", fake_supply)
    monkeypatch.setattr(candidate_generator, "_interest_related_ids", fake_interest)

    now = datetime.now(UTC)
    subject = SubjectContext(
        tenant_id=tenant_id,
        event_id=event_id,
        profile_id=uuid.uuid4(),
        visit_session_id=None,
        user_id=uuid.uuid4(),
        guest_session_id=None,
        request_id="engine-test",
        idempotency_key=None,
        server_time=now,
    )
    validated = ValidatedRequest(
        subject=subject,
        request_valid=True,
        user_type="BUYER",
        recommendation_type="PRODUCT",
        limit=10,
        context_input={},
        missing_fields=[],
        policy_route="BUYER_MATCHING_V1",
    )
    context = ResolvedContext(
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
        server_time=now,
    )

    candidates, counts = await candidate_generator.generate_candidates(
        object(),  # type: ignore[arg-type]
        validated=validated,
        profile=_profile(),
        context=context,
        semantic_scorer=scorer,
    )

    assert candidates == [candidate]
    assert counts["VECTOR"] == 1
    assert "VECTOR_DISABLED" not in counts
    assert "VECTOR_UNAVAILABLE" not in counts
    assert candidate.source_channels >= {"STRUCTURED", "VECTOR"}
    assert candidate.payload["vector_relevance_score"] == 0.82


def test_vector_recall_caps_each_participation_and_preserves_rank_score() -> None:
    first_participation = uuid.uuid4()
    second_participation = uuid.uuid4()
    pool = [
        *[
            _candidate(first_participation, quality=value)
            for value in range(10, 60, 10)
        ],
        _candidate(second_participation, quality=90),
    ]
    selected: dict[tuple[str, uuid.UUID], MatchCandidate] = {}
    fingerprint = "f" * 64

    count = _apply_vector_recall(
        pool,
        selected,
        recall=ProfileSemanticRecall(
            {
                first_participation: 0.9,
                second_participation: 0.8,
            },
            "AVAILABLE",
            fingerprint,
            uuid.uuid4(),
        ),
        user_type="BUYER",
    )

    first_hits = [
        candidate
        for candidate in selected.values()
        if candidate.participation_id == first_participation
    ]
    assert len(first_hits) == VECTOR_OBJECTS_PER_PARTICIPATION
    assert count == VECTOR_OBJECTS_PER_PARTICIPATION + 1
    assert {candidate.payload["buyer_score"] for candidate in first_hits} == {
        30,
        40,
        50,
    }
    assert all(
        candidate.source_channels == {"VECTOR"} for candidate in selected.values()
    )
    assert all(candidate.final_score == 0.0 for candidate in selected.values())
    assert all(
        candidate.payload["vector_profile_fingerprint"] == fingerprint
        for candidate in selected.values()
    )
