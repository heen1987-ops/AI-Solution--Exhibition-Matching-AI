"""Search and recommendation facade endpoints (BAC-008)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import (
    ApiRequestContext,
    get_request_context,
    require_operator,
    require_persistent_profile,
)
from app.api.v1.errors import api_error
from app.db.session import get_db
from app.models.identity import GuestSession
from app.models.matching import MatchReason, MatchResult, RecommendationSession
from app.models.ontology_refs import concept, concept_revision
from app.models.profile import UserProfile
from app.models.search import SearchQuery as PersistedSearchQuery
from app.models.search import SearchResult, SearchSession
from app.services.matching.search_pipeline_contract import fallback_reason_for_recovery
from app.services.matching.search_provider import (
    ReciprocalRankFusionCombiner,
    SearchCandidate,
    SearchQuery,
    SearchScoreBreakdown,
    StructuredSearchProvider,
)
from app.services.matching.search_recovery import (
    SearchRecoveryInput,
    decide_search_recovery,
)

router = APIRouter()

SearchChannel = Literal["REGISTERED_WEB", "GUEST_WEB", "BUYER_WEB", "ADMIN_PREVIEW"]
QueryType = Literal["FREE_TEXT", "CATEGORY"]
TargetType = Literal["BOOTH", "EVENT_PRODUCT", "EXHIBITOR", "PROGRAM"]

_DEFAULT_LIMIT = 20
_PROVIDER_LIMIT = 80


class PageMeta(BaseModel):
    page: int
    page_size: int
    total_count: int


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel: SearchChannel
    query_type: QueryType
    profile_id: uuid.UUID | None = None
    guest_session_id: uuid.UUID | None = None
    query_text: str | None = Field(default=None, max_length=500)
    concept_codes: list[str] = Field(default_factory=list, max_length=100)


class SearchClarifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    search_session_id: uuid.UUID
    clarification_text: str = Field(min_length=1, max_length=500)


class SearchResultItem(BaseModel):
    recommendable_id: uuid.UUID
    rank: int
    final_score: float | None = None
    reason_codes: list[str]


class SearchResponseMeta(BaseModel):
    code: Literal["SEARCH_NO_RESULT"] | None = None
    recovery_action: str | None = None
    clarification_question: str | None = None
    unavailable_providers: list[str] = Field(default_factory=list)


class SearchResponse(BaseModel):
    search_query_id: uuid.UUID
    result_count: int
    results: list[SearchResultItem]
    meta: SearchResponseMeta | None = None


class RecommendationReasonItem(BaseModel):
    reason_code: str
    reason_text: str


class RecommendationResultItem(BaseModel):
    match_result_id: uuid.UUID
    recommendable_id: uuid.UUID
    rank: int
    normalized_score: float
    recommended_action: str | None = None
    reasons: list[RecommendationReasonItem]


class RecommendationListResponse(BaseModel):
    recommendation_session_id: uuid.UUID | None = None
    results: list[RecommendationResultItem]
    page: PageMeta


def _now() -> datetime:
    return datetime.now(UTC)


def _target_type(payload: SearchRequest) -> TargetType:
    if payload.channel == "REGISTERED_WEB":
        return "EVENT_PRODUCT"
    return "EXHIBITOR"


def _score(value: Decimal | float | None) -> float | None:
    if value is None:
        return None
    return float(value)


def _score_breakdown(candidate: SearchCandidate) -> SearchScoreBreakdown:
    return candidate.score_breakdown or SearchScoreBreakdown()


async def _load_profile_for_search(
    db: AsyncSession,
    *,
    profile_id: uuid.UUID,
    context: ApiRequestContext,
    channel: SearchChannel,
) -> UserProfile:
    if channel == "BUYER_WEB" and context.user_type != "BUYER_REGISTERED":
        raise api_error(
            "PERMISSION_DENIED",
            "이 작업을 수행할 권한이 없습니다.",
            status_code=403,
        )
    if channel == "REGISTERED_WEB" and context.user_type == "GUEST_WEB":
        raise api_error(
            "PERMISSION_DENIED",
            "이 작업을 수행할 권한이 없습니다.",
            status_code=403,
        )
    context_profile_id = require_persistent_profile(context)
    if profile_id != context_profile_id:
        raise api_error(
            "PERMISSION_DENIED",
            "이 작업을 수행할 권한이 없습니다.",
            status_code=403,
        )
    profile = await db.get(UserProfile, profile_id)
    if profile is None or profile.deleted_at is not None or profile.user_id is None:
        raise api_error(
            "RESOURCE_NOT_FOUND",
            "요청한 대상을 찾을 수 없습니다.",
            status_code=404,
            details={"resource": "profile"},
        )
    return profile


async def _load_guest_for_search(
    db: AsyncSession, guest_session_id: uuid.UUID
) -> GuestSession:
    guest_session = await db.get(GuestSession, guest_session_id)
    if (
        guest_session is None
        or guest_session.entry_channel != "WEB"
        or guest_session.expires_at <= _now()
        or guest_session.converted_user_id is not None
    ):
        raise api_error(
            "GUEST_SESSION_EXPIRED",
            "게스트 웹 세션이 만료되었습니다.",
            status_code=410,
            details={"resource": "guest_session"},
        )
    return guest_session


async def _authorize_search_session_access(
    db: AsyncSession,
    *,
    search_session: SearchSession,
    context: ApiRequestContext,
) -> None:
    if search_session.guest_session_id is not None:
        await _load_guest_for_search(db, search_session.guest_session_id)
        return
    if search_session.channel == "ADMIN_PREVIEW":
        operator_user_id = require_operator(context)
        if search_session.user_id != operator_user_id:
            raise api_error(
                "PERMISSION_DENIED",
                "이 작업을 수행할 권한이 없습니다.",
                status_code=403,
            )
        return
    profile_id = require_persistent_profile(context)
    profile = await db.get(UserProfile, profile_id)
    if (
        profile is None
        or profile.deleted_at is not None
        or profile.user_id != search_session.user_id
    ):
        raise api_error(
            "RESOURCE_NOT_FOUND",
            "요청한 대상을 찾을 수 없습니다.",
            status_code=404,
            details={"resource": "search_session"},
        )


async def _resolve_concept_codes(
    db: AsyncSession, concept_codes: list[str]
) -> frozenset[uuid.UUID]:
    if not concept_codes:
        return frozenset()
    rows = await db.execute(
        select(concept_revision.c.concept_id)
        .join(concept, concept.c.concept_id == concept_revision.c.concept_id)
        .where(
            concept.c.concept_code.in_(concept_codes),
            concept_revision.c.assignable.is_(True),
            concept_revision.c.status == "ACTIVE",
        )
    )
    concept_ids = {row.concept_id for row in rows}
    if len(concept_ids) != len(set(concept_codes)):
        raise api_error(
            "SEARCH_QUERY_INVALID",
            "검색 조건이 올바르지 않습니다.",
            status_code=422,
            details={"field": "concept_codes"},
        )
    return frozenset(concept_ids)


async def _next_sequence_no(db: AsyncSession, search_session_id: uuid.UUID) -> int:
    max_sequence = await db.scalar(
        select(func.max(PersistedSearchQuery.sequence_no)).where(
            PersistedSearchQuery.search_session_id == search_session_id
        )
    )
    return int(max_sequence or 0) + 1


async def _create_search_session(
    db: AsyncSession,
    *,
    payload: SearchRequest,
    context: ApiRequestContext,
) -> SearchSession:
    if payload.channel == "GUEST_WEB":
        if payload.guest_session_id is None:
            raise api_error(
                "SEARCH_QUERY_INVALID",
                "검색 조건이 올바르지 않습니다.",
                status_code=422,
                details={"field": "guest_session_id"},
            )
        guest_session = await _load_guest_for_search(db, payload.guest_session_id)
        search_session = SearchSession(
            tenant_id=guest_session.tenant_id,
            event_id=guest_session.event_id,
            channel=payload.channel,
            guest_session_id=guest_session.guest_session_id,
            status="ACTIVE",
        )
    elif payload.channel == "ADMIN_PREVIEW":
        operator_user_id = require_operator(context)
        if payload.profile_id is None:
            raise api_error(
                "SEARCH_QUERY_INVALID",
                "검색 조건이 올바르지 않습니다.",
                status_code=422,
                details={"field": "profile_id"},
            )
        profile = await db.get(UserProfile, payload.profile_id)
        if profile is None or profile.deleted_at is not None:
            raise api_error(
                "RESOURCE_NOT_FOUND",
                "요청한 대상을 찾을 수 없습니다.",
                status_code=404,
                details={"resource": "profile"},
            )
        search_session = SearchSession(
            tenant_id=profile.tenant_id,
            event_id=profile.event_id,
            channel=payload.channel,
            user_id=operator_user_id,
            status="ACTIVE",
        )
    else:
        profile_id = payload.profile_id or context.profile_id
        if profile_id is None:
            raise api_error(
                "AUTHENTICATION_REQUIRED",
                "로그인이 필요합니다.",
                status_code=401,
            )
        profile = await _load_profile_for_search(
            db, profile_id=profile_id, context=context, channel=payload.channel
        )
        search_session = SearchSession(
            tenant_id=profile.tenant_id,
            event_id=profile.event_id,
            channel=payload.channel,
            user_id=profile.user_id,
            status="ACTIVE",
        )

    db.add(search_session)
    await db.flush()
    return search_session


async def _run_structured_search(
    db: AsyncSession,
    *,
    payload: SearchRequest,
    search_session: SearchSession,
    concept_ids: frozenset[uuid.UUID],
) -> list[SearchCandidate]:
    query = SearchQuery(
        event_id=search_session.event_id,
        target_type=_target_type(payload),
        channel=payload.channel,
        raw_text=payload.query_text,
        preferred_concept_ids=concept_ids,
        locale="ko-KR",
    )
    provider = StructuredSearchProvider(session=db)
    structured = await provider.search(query, limit=_PROVIDER_LIMIT)
    return ReciprocalRankFusionCombiner().combine({"STRUCTURED": structured})[:_DEFAULT_LIMIT]


async def _persist_search_query(
    db: AsyncSession,
    *,
    payload: SearchRequest,
    search_session: SearchSession,
    candidates: list[SearchCandidate],
    recovery_reason_codes: tuple[str, ...],
    fallback_reason: str | None,
) -> PersistedSearchQuery:
    query = PersistedSearchQuery(
        search_session_id=search_session.search_session_id,
        sequence_no=await _next_sequence_no(db, search_session.search_session_id),
        query_type=payload.query_type,
        query_text=payload.query_text,
        concept_codes=payload.concept_codes,
        intent_json={
            "channel": payload.channel,
            "target_type": _target_type(payload),
            "recovery_reason_codes": list(recovery_reason_codes),
        },
        result_count=len(candidates),
        fallback_reason=fallback_reason,
    )
    db.add(query)
    await db.flush()

    for candidate in candidates:
        breakdown = _score_breakdown(candidate)
        db.add(
            SearchResult(
                search_query_id=query.search_query_id,
                recommendable_id=candidate.recommendable_id,
                rank=candidate.rank,
                structured_score=breakdown.structured_score,
                keyword_score=breakdown.keyword_score,
                semantic_score=breakdown.semantic_score,
                data_quality_score=breakdown.data_quality_score,
                availability_score=breakdown.availability_score,
                final_score=breakdown.final_score,
                reason_codes=list(breakdown.reason_codes),
            )
        )
    return query


def _search_response(
    query: PersistedSearchQuery,
    candidates: list[SearchCandidate],
    *,
    meta: SearchResponseMeta | None,
) -> SearchResponse:
    return SearchResponse(
        search_query_id=query.search_query_id,
        result_count=len(candidates),
        results=[
            SearchResultItem(
                recommendable_id=candidate.recommendable_id,
                rank=candidate.rank,
                final_score=_score(_score_breakdown(candidate).final_score),
                reason_codes=list(_score_breakdown(candidate).reason_codes),
            )
            for candidate in candidates
        ],
        meta=meta,
    )


async def _execute_search(
    db: AsyncSession,
    *,
    payload: SearchRequest,
    search_session: SearchSession,
) -> SearchResponse:
    concept_ids = await _resolve_concept_codes(db, payload.concept_codes)
    candidates = await _run_structured_search(
        db,
        payload=payload,
        search_session=search_session,
        concept_ids=concept_ids,
    )
    recovery = decide_search_recovery(
        SearchRecoveryInput(
            channel=payload.channel,  # type: ignore[arg-type]
            query_type=payload.query_type,
            result_count=len(candidates),
            confidence=0.8,
            required_concept_count=len(concept_ids),
            preferred_concept_count=len(concept_ids),
            unmapped_term_count=1 if payload.query_text and not concept_ids else 0,
            has_raw_text=bool(payload.query_text),
        )
    )
    fallback_reason = (
        fallback_reason_for_recovery(recovery.action)
        if recovery.meta_code == "SEARCH_NO_RESULT" or len(candidates) == 0
        else None
    )
    query = await _persist_search_query(
        db,
        payload=payload,
        search_session=search_session,
        candidates=candidates,
        recovery_reason_codes=recovery.reason_codes,
        fallback_reason=fallback_reason,
    )
    await db.commit()

    meta = None
    if recovery.action != "NONE":
        meta = SearchResponseMeta(
            code="SEARCH_NO_RESULT" if recovery.meta_code == "SEARCH_NO_RESULT" else None,
            recovery_action=recovery.action,
            clarification_question=recovery.clarification_question,
            unavailable_providers=[
                "KEYWORD",
                "VECTOR",
                "POPULAR",
            ],
        )
    return _search_response(query, candidates, meta=meta)


async def _load_query_response(
    db: AsyncSession, query: PersistedSearchQuery
) -> SearchResponse:
    rows = await db.scalars(
        select(SearchResult)
        .where(SearchResult.search_query_id == query.search_query_id)
        .order_by(SearchResult.rank.asc())
    )
    results = rows.all()
    return SearchResponse(
        search_query_id=query.search_query_id,
        result_count=query.result_count,
        results=[
            SearchResultItem(
                recommendable_id=result.recommendable_id,
                rank=result.rank,
                final_score=_score(result.final_score),
                reason_codes=list(result.reason_codes or []),
            )
            for result in results
        ],
        meta=(
            SearchResponseMeta(code="SEARCH_NO_RESULT")
            if query.fallback_reason == "NO_RESULT"
            else None
        ),
    )


@router.post("/search", response_model=SearchResponse, operation_id="submitSearch")
async def submit_search(
    payload: SearchRequest,
    context: Annotated[ApiRequestContext, Depends(get_request_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SearchResponse:
    if payload.query_type == "FREE_TEXT" and not payload.query_text:
        raise api_error(
            "SEARCH_QUERY_INVALID",
            "검색 조건이 올바르지 않습니다.",
            status_code=422,
            details={"field": "query_text"},
        )
    if payload.query_type == "CATEGORY" and not payload.concept_codes:
        raise api_error(
            "SEARCH_QUERY_INVALID",
            "검색 조건이 올바르지 않습니다.",
            status_code=422,
            details={"field": "concept_codes"},
        )
    search_session = await _create_search_session(db, payload=payload, context=context)
    return await _execute_search(db, payload=payload, search_session=search_session)


@router.post(
    "/guest/sessions/{guest_session_id}/search",
    response_model=SearchResponse,
    operation_id="submitGuestWebSearch",
)
async def submit_guest_session_search(
    guest_session_id: uuid.UUID,
    payload: SearchRequest,
    context: Annotated[ApiRequestContext, Depends(get_request_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SearchResponse:
    guest_payload = payload.model_copy(
        update={
            "channel": "GUEST_WEB",
            "guest_session_id": guest_session_id,
            "profile_id": None,
        }
    )
    return await submit_search(guest_payload, context, db)


@router.post(
    "/search/clarify",
    response_model=SearchResponse,
    operation_id="clarifySearch",
)
async def clarify_search(
    payload: SearchClarifyRequest,
    context: Annotated[ApiRequestContext, Depends(get_request_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SearchResponse:
    search_session = await db.get(SearchSession, payload.search_session_id)
    if search_session is None:
        raise api_error(
            "RESOURCE_NOT_FOUND",
            "요청한 대상을 찾을 수 없습니다.",
            status_code=404,
            details={"resource": "search_session"},
        )
    await _authorize_search_session_access(
        db, search_session=search_session, context=context
    )
    clarify_payload = SearchRequest(
        channel=search_session.channel,  # type: ignore[arg-type]
        query_type="FREE_TEXT",
        query_text=payload.clarification_text,
        guest_session_id=search_session.guest_session_id,
    )
    return await _execute_search(
        db, payload=clarify_payload, search_session=search_session
    )


@router.get(
    "/search/{search_session_id}",
    response_model=SearchResponse,
    operation_id="getSearchSession",
)
async def get_search_session(
    search_session_id: uuid.UUID,
    context: Annotated[ApiRequestContext, Depends(get_request_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SearchResponse:
    search_session = await db.get(SearchSession, search_session_id)
    if search_session is None:
        raise api_error(
            "RESOURCE_NOT_FOUND",
            "요청한 대상을 찾을 수 없습니다.",
            status_code=404,
            details={"resource": "search_session"},
        )
    await _authorize_search_session_access(
        db, search_session=search_session, context=context
    )
    query = await db.scalar(
        select(PersistedSearchQuery)
        .where(PersistedSearchQuery.search_session_id == search_session_id)
        .order_by(PersistedSearchQuery.sequence_no.desc())
        .limit(1)
    )
    if query is None:
        raise api_error(
            "RESOURCE_NOT_FOUND",
            "요청한 대상을 찾을 수 없습니다.",
            status_code=404,
            details={"resource": "search_query"},
        )
    return await _load_query_response(db, query)


async def _recommendation_reasons(
    db: AsyncSession, result_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[RecommendationReasonItem]]:
    if not result_ids:
        return {}
    rows = await db.scalars(
        select(MatchReason)
        .where(MatchReason.match_result_id.in_(result_ids))
        .order_by(MatchReason.match_result_id, MatchReason.display_order)
    )
    reasons: dict[uuid.UUID, list[RecommendationReasonItem]] = {}
    for reason in rows:
        reasons.setdefault(reason.match_result_id, []).append(
            RecommendationReasonItem(
                reason_code=reason.reason_code,
                reason_text=reason.reason_text,
            )
        )
    return reasons


async def _recommendation_response(
    db: AsyncSession,
    session: RecommendationSession | None,
    *,
    page: int,
    page_size: int,
) -> RecommendationListResponse:
    if session is None:
        return RecommendationListResponse(
            results=[],
            page=PageMeta(page=page, page_size=page_size, total_count=0),
        )
    base_filter = MatchResult.recommendation_session_id == session.recommendation_session_id
    total_count = await db.scalar(
        select(func.count()).select_from(MatchResult).where(base_filter)
    )
    rows = await db.scalars(
        select(MatchResult)
        .where(base_filter)
        .order_by(MatchResult.rank.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    results = rows.all()
    reasons = await _recommendation_reasons(
        db, [result.match_result_id for result in results]
    )
    return RecommendationListResponse(
        recommendation_session_id=session.recommendation_session_id,
        results=[
            RecommendationResultItem(
                match_result_id=result.match_result_id,
                recommendable_id=result.recommendable_id,
                rank=result.rank,
                normalized_score=float(result.normalized_score),
                recommended_action=result.recommended_action,
                reasons=reasons.get(result.match_result_id, []),
            )
            for result in results
        ],
        page=PageMeta(
            page=page,
            page_size=page_size,
            total_count=int(total_count or 0),
        ),
    )


@router.get(
    "/recommendations",
    response_model=RecommendationListResponse,
    operation_id="getRecommendations",
)
async def get_recommendations(
    context: Annotated[ApiRequestContext, Depends(get_request_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    recommendation_type: Annotated[str | None, Query(max_length=20)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> RecommendationListResponse:
    profile_id = require_persistent_profile(context)
    filters = [RecommendationSession.profile_id == profile_id]
    if recommendation_type is not None:
        filters.append(RecommendationSession.recommendation_type == recommendation_type)
    session = await db.scalar(
        select(RecommendationSession)
        .where(*filters)
        .order_by(RecommendationSession.generated_at.desc())
        .limit(1)
    )
    return await _recommendation_response(
        db, session, page=page, page_size=page_size
    )


@router.get(
    "/recommendations/{recommendation_session_id}",
    response_model=RecommendationListResponse,
    operation_id="getRecommendationSession",
)
async def get_recommendation_session(
    recommendation_session_id: uuid.UUID,
    context: Annotated[ApiRequestContext, Depends(get_request_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> RecommendationListResponse:
    profile_id = require_persistent_profile(context)
    session = await db.get(RecommendationSession, recommendation_session_id)
    if session is None or session.profile_id != profile_id:
        raise api_error(
            "RESOURCE_NOT_FOUND",
            "요청한 대상을 찾을 수 없습니다.",
            status_code=404,
            details={"resource": "recommendation_session"},
        )
    return await _recommendation_response(
        db, session, page=page, page_size=page_size
    )
