"""추천 API - docs/frontend-backend-ai-interface-spec.md 9절·16절.

이 라우터가 구현하는 실제 공개 경로 (05번 문서 12.1절이 아니라 인터페이스 명세를 기준으로
한다 - 05번 문서의 내부 모듈 이름은 파이프라인 구성요소 경계 설명일 뿐 공개 라우트가 아니다):

    POST /api/v1/recommendations                              - 9.1 추천 생성
    GET  /api/v1/recommendation-sessions/{id}/items            - 9.4 추천 목록(조회)
    POST /api/v1/interactions/batch                            - 16.1 행동 이벤트 등록
         (노출/조회/저장/제외 등 - RECOMMENDATION_IMPRESSION/OPENED/SAVED/DISMISSED 포함)

라우터 내부에서는 이 파일이 직접 파이프라인 단계를 구현하지 않고
``app.services.matching.orchestrator.RecommendationOrchestrator``만 호출한다(단계별 로직은
``app/services/matching/*`` 각 모듈 책임).

주체(subject) 해석에 대한 중요한 메모
--------------------------------------
인터페이스 명세 9.1절: "서버는 현재 인증·익명 세션에서 profile_id, visit_session_id,
event_id를 파생한다. 클라이언트가 다른 프로파일 ID를 지정할 수 없다." 이 저장소에는 그
세션 해석 미들웨어가 아직 없다(인증 도메인 에이전트 책임, 이 작업 범위 밖). 그 미들웨어가
나오기 전까지 ``resolve_subject_context``가 사이트별 BFF/PHP/Netlify 어댑터가 해석하고
HMAC 서명한 요청 헤더(X-Tenant-Id/X-Event-Id/X-Profile-Id/X-Visit-Session-Id/X-User-Id/
X-Guest-Session-Id)로 주체를 해석한다. 브라우저는 서명키를 갖지 않으며, 로컬 디버그에서만
무서명 헤더를 허용한다. 인증 모듈이 구현되면 이 함수 내부만 교체하도록 반환 타입
(``SubjectContext``)은 고정한다.

오류 응답에 대한 메모
----------------------
``RecommendationApiException`` 전용 처리기가 인증·검증·파이프라인 오류를 인터페이스
명세 4.4절의 ``success=false/error/meta`` 봉투로 직렬화한다. FastAPI 기본 ``detail``
래퍼는 공개 추천 API에 노출하지 않는다.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal, NoReturn

from fastapi import APIRouter, Depends, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.site_context import verify_site_context
from app.db.session import get_db
from app.models.common import new_uuid7
from app.models.exhibitor import Booth, EventProduct, ExhibitorParticipation
from app.models.matching import (
    InteractionClientEventDedupe,
    InteractionEvent,
    MatchReason,
    MatchResult,
    MatchRun,
    Recommendable,
    RecommendationImpression,
    SlateItem,
    SlateResult,
)
from app.schemas.recommendation import (
    AvailabilityView,
    Envelope,
    ErrorBody,
    ErrorEnvelope,
    FieldError,
    InteractionBatchRequest,
    InteractionBatchResponse,
    InteractionEventIn,
    InteractionEventResult,
    Meta,
    ReasonView,
    RecommendationItem,
    RecommendationRequest,
    RecommendationResponse,
    RecommendationSessionItemsResponse,
)
from app.services.matching.errors import (
    RecommendationError,
    auth_required,
    resource_forbidden,
    service_temporarily_unavailable,
    validation_failed,
)
from app.services.matching.orchestrator import recommendation_orchestrator
from app.services.matching.types import (
    MatchCandidate,
    RecommendationOutcome,
    SubjectContext,
    score_to_match_level,
)

router = APIRouter()
DbSession = Annotated[AsyncSession, Depends(get_db)]
logger = logging.getLogger(__name__)

try:  # pragma: no cover - CANONICAL_EVENTS는 typing_extensions 여부와 무관한 순수 상수.
    from meet_ai.ontology.catalog import CANONICAL_EVENTS
except (
    ImportError
):  # pragma: no cover - 카탈로그 패키지가 없는 극단적 상황에 대한 방어.
    CANONICAL_EVENTS = frozenset()


class RecommendationApiException(Exception):
    """Typed route error rendered by ``recommendation_exception_handler``."""

    def __init__(self, status_code: int, error: ErrorBody) -> None:
        super().__init__(error.message)
        self.status_code = status_code
        self.error = error


async def recommendation_exception_handler(
    request: Request, error: RecommendationApiException
) -> JSONResponse:
    request_id = request.headers.get("X-Request-ID") or str(new_uuid7())
    body = ErrorEnvelope(error=error.error, meta=_meta(request_id))
    return JSONResponse(
        status_code=error.status_code,
        content=jsonable_encoder(body),
    )


async def database_exception_handler(
    request: Request, error: SQLAlchemyError
) -> JSONResponse:
    logger.error(
        "database operation failed while serving %s",
        request.url.path,
        exc_info=(type(error), error, error.__traceback__),
    )
    mapped = service_temporarily_unavailable(
        "추천 데이터를 처리하는 중 일시적인 오류가 발생했습니다."
    )
    body = ErrorEnvelope(
        error=ErrorBody(
            code=mapped.code,
            message=mapped.message,
            field_errors=[],
            retryable=mapped.retryable,
            retry_after_seconds=mapped.retry_after_seconds,
        ),
        meta=_meta(request.headers.get("X-Request-ID") or str(new_uuid7())),
    )
    return JSONResponse(
        status_code=mapped.http_status,
        content=jsonable_encoder(body),
    )


def _raise_http(error: RecommendationError) -> NoReturn:
    """RecommendationError -> HTTPException. 모듈 docstring "오류 응답에 대한 메모" 참고.

    라우터 함수 바깥(FastAPI 의존성, 헤더 해석 등)에서 발생한 오류도 항상 이 함수를 거쳐
    HTTPException으로 변환해야 한다 - RecommendationError를 그대로 raise하면 이 저장소에는
    아직 전역 예외 핸들러가 없어(main.py 소유, 이 작업 범위 밖) FastAPI 기본 처리로 500이
    나가버린다.
    """

    raise RecommendationApiException(
        error.http_status,
        ErrorBody(
            code=error.code,
            message=error.message,
            field_errors=[
                FieldError(field=fe.field, reason=fe.reason)
                for fe in error.field_errors
            ],
            retryable=error.retryable,
            retry_after_seconds=error.retry_after_seconds,
        ),
    )


def _meta(request_id: str) -> Meta:
    return Meta(request_id=request_id, server_time=datetime.now(UTC))


# ---------------------------------------------------------------------------
# 주체 컨텍스트 임시 해석기 (모듈 docstring 참고)
# ---------------------------------------------------------------------------
# 아래 헬퍼들은 실패 시 RecommendationError를 raise하지 않고 곧바로 _raise_http로 변환한다 -
# resolve_subject_context는 각 엔드포인트에서 try/except 바깥(다른 인자 검증 이전)에 호출되므로,
# 여기서 HTTPException으로 바로 변환해 두어야 앞서 설명한 500 오작동을 피할 수 있다.


def _require_uuid_header(request: Request, name: str) -> uuid.UUID:
    raw = request.headers.get(name)
    if not raw:
        _raise_http(auth_required(f"{name} 헤더가 필요합니다."))
    try:
        return uuid.UUID(raw)
    except ValueError:
        _raise_http(validation_failed(f"{name} 헤더는 UUID 형식이어야 합니다."))
    raise AssertionError("unreachable")  # pragma: no cover


def _optional_uuid_header(request: Request, name: str) -> uuid.UUID | None:
    raw = request.headers.get(name)
    if not raw:
        return None
    try:
        return uuid.UUID(raw)
    except ValueError:
        _raise_http(validation_failed(f"{name} 헤더는 UUID 형식이어야 합니다."))
    raise AssertionError("unreachable")  # pragma: no cover


def resolve_subject_context(request: Request) -> SubjectContext:
    settings = get_settings()
    local_unsigned_context = settings.DEBUG and settings.ENV.lower() in {
        "local",
        "dev",
        "test",
    }
    if not local_unsigned_context:
        verification = verify_site_context(
            request.headers, secret=settings.site_context_secret
        )
        if not verification.valid:
            _raise_http(
                auth_required(
                    "사이트 어댑터의 사용자 컨텍스트 서명을 확인할 수 없습니다."
                )
            )
    tenant_id = _require_uuid_header(request, "X-Tenant-Id")
    event_id = _require_uuid_header(request, "X-Event-Id")
    profile_id = _require_uuid_header(request, "X-Profile-Id")
    visit_session_id = _optional_uuid_header(request, "X-Visit-Session-Id")
    user_id = _optional_uuid_header(request, "X-User-Id")
    guest_session_id = _optional_uuid_header(request, "X-Guest-Session-Id")
    if (user_id is None) == (guest_session_id is None):
        _raise_http(
            auth_required("X-User-Id와 X-Guest-Session-Id 중 정확히 하나가 필요합니다.")
        )
    request_id = request.headers.get("X-Request-ID") or str(new_uuid7())
    idempotency_key = request.headers.get("Idempotency-Key")
    return SubjectContext(
        tenant_id=tenant_id,
        event_id=event_id,
        profile_id=profile_id,
        visit_session_id=visit_session_id,
        user_id=user_id,
        guest_session_id=guest_session_id,
        request_id=request_id,
        idempotency_key=idempotency_key,
        server_time=datetime.now(UTC),
    )


# ---------------------------------------------------------------------------
# 9.1 추천 생성
# ---------------------------------------------------------------------------


def _item_view(candidate: MatchCandidate) -> RecommendationItem:
    return RecommendationItem(
        match_result_id=candidate.match_result_id,
        rank=candidate.rank,
        object_type=candidate.object_type,
        object_id=candidate.public_object_id,
        exhibitor_id=candidate.exhibitor_id,
        match_level=candidate.match_level(),
        reasons=[
            ReasonView(code=r.code, text=r.text, evidence_refs=r.evidence_refs)
            for r in candidate.reasons
        ],
        distance_meters=candidate.distance_meters,
        estimated_walk_minutes=candidate.estimated_walk_minutes,
        estimated_wait_minutes=candidate.estimated_wait_minutes,
        status_observed_at=candidate.status_observed_at,
        availability=AvailabilityView(**candidate.availability),
        recommended_action=candidate.recommended_action,
        slot_type=candidate.slot_type,
        related_object_ids=list(candidate.related_object_ids),
        recommendation_confidence=candidate.recommendation_confidence,
        cold_start_status=candidate.cold_start_state,
        cold_start_reason_codes=list(candidate.cold_start_reason_codes),
    )


def _outcome_response(outcome: RecommendationOutcome) -> RecommendationResponse:
    return RecommendationResponse(
        recommendation_session_id=outcome.recommendation_session_id,
        generated_at=outcome.generated_at,
        expires_at=outcome.expires_at,
        profile_version=outcome.profile_version,
        ranking_version=outcome.ranking_version,
        explanation_version=outcome.explanation_version,
        policy_version=outcome.policy_version,
        items=[_item_view(candidate) for candidate in outcome.items],
        stale=outcome.stale,
    )


@router.post("/recommendations", response_model=Envelope[RecommendationResponse])
async def create_recommendation(
    payload: RecommendationRequest,
    request: Request,
    db: DbSession,
) -> Envelope[RecommendationResponse]:
    subject = resolve_subject_context(request)
    # TODO(integration.idempotency_record 확정 후 구현): Idempotency-Key 재사용 시 동일 요청
    # 본문이면 최초 결과를 재사용하고, 다른 본문이면 409 IDEMPOTENCY_KEY_REUSED를 반환해야
    # 한다(인터페이스 명세 4.2절). 그 저장소가 이 작업 범위 밖이라 지금은 매번 새로 생성한다.
    try:
        outcome = await recommendation_orchestrator.generate(
            db,
            subject=subject,
            recommendation_type=payload.recommendation_type,
            context_input=payload.context.model_dump(),
            limit=payload.limit,
        )
    except RecommendationError as error:
        _raise_http(error)
        raise  # pragma: no cover - _raise_http는 항상 예외를 던진다.

    return Envelope(data=_outcome_response(outcome), meta=_meta(subject.request_id))


# ---------------------------------------------------------------------------
# 9.4 추천 목록
# ---------------------------------------------------------------------------

# exhibition.recommendable.object_type(app/models/matching.py CHECK 제약: BOOTH,
# EVENT_PRODUCT, EXHIBITOR, PROGRAM)과 공개 API·recommendation_type 어휘(BOOTH, PRODUCT,
# EXHIBITOR, PROGRAM, MIXED - 인터페이스 명세 9.1절)는 제품 유형 이름이 서로 다르다
# ("EVENT_PRODUCT" vs "PRODUCT"). 이 라우터는 항상 공개 어휘만 노출해야 하므로 여기서
# 양방향으로 변환한다.
_PUBLIC_TO_INTERNAL_OBJECT_TYPE = {"PRODUCT": "EVENT_PRODUCT"}
_INTERNAL_TO_PUBLIC_OBJECT_TYPE = {"EVENT_PRODUCT": "PRODUCT"}


def _encode_rank_cursor(rank: int) -> str:
    payload = base64.urlsafe_b64encode(f"rank:{rank}".encode("ascii")).decode("ascii")
    return payload.rstrip("=")


def _decode_rank_cursor(cursor: str) -> int:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        decoded = base64.b64decode(
            padded,
            altchars=b"-_",
            validate=True,
        ).decode("ascii")
        prefix, rank_text = decoded.split(":", maxsplit=1)
        rank = int(rank_text)
    except (ValueError, UnicodeDecodeError, binascii.Error) as exc:
        raise validation_failed("cursor 형식이 올바르지 않습니다.") from exc
    if prefix != "rank" or rank < 0:
        raise validation_failed("cursor 형식이 올바르지 않습니다.")
    return rank


async def _resolve_result_object_id(
    db: AsyncSession, recommendable: Recommendable
) -> tuple[str, uuid.UUID | None]:
    """recommendable 행에서 공개 object_id 문자열과 exhibitor_id를 뽑는다.

    EXHIBITOR 유형은 recommendable.participation_id를 저장하므로 공개 object_id(=exhibitor_id)를
    보여주려면 exhibitor_participation을 한 번 더 조회해야 한다.
    """

    if recommendable.object_type == "BOOTH":
        exhibitor_id = (
            await db.execute(
                select(ExhibitorParticipation.exhibitor_id)
                .join(
                    Booth,
                    Booth.participation_id == ExhibitorParticipation.participation_id,
                )
                .where(
                    Booth.booth_id == recommendable.booth_id,
                    Booth.tenant_id == recommendable.tenant_id,
                    Booth.event_id == recommendable.event_id,
                )
            )
        ).scalar_one_or_none()
        return str(recommendable.booth_id), exhibitor_id
    if recommendable.object_type == "EVENT_PRODUCT":
        product_row = (
            await db.execute(
                select(EventProduct.product_id, ExhibitorParticipation.exhibitor_id)
                .join(
                    ExhibitorParticipation,
                    ExhibitorParticipation.participation_id
                    == EventProduct.participation_id,
                )
                .where(
                    EventProduct.event_product_id == recommendable.event_product_id,
                    EventProduct.tenant_id == recommendable.tenant_id,
                    EventProduct.event_id == recommendable.event_id,
                )
            )
        ).first()
        if product_row is not None:
            return str(product_row.product_id), product_row.exhibitor_id
        return str(recommendable.event_product_id), None
    if recommendable.object_type == "PROGRAM":
        return str(recommendable.program_id), None
    if recommendable.object_type == "EXHIBITOR":
        exhibitor_id = (
            await db.execute(
                select(ExhibitorParticipation.exhibitor_id).where(
                    ExhibitorParticipation.participation_id
                    == recommendable.participation_id,
                    ExhibitorParticipation.tenant_id == recommendable.tenant_id,
                    ExhibitorParticipation.event_id == recommendable.event_id,
                )
            )
        ).scalar_one_or_none()
        return str(exhibitor_id or recommendable.participation_id), exhibitor_id
    return str(recommendable.recommendable_id), None


@router.get(
    "/recommendation-sessions/{recommendation_session_id}/items",
    response_model=Envelope[RecommendationSessionItemsResponse],
)
async def list_recommendation_session_items(
    recommendation_session_id: uuid.UUID,
    request: Request,
    db: DbSession,
    object_type: Literal["BOOTH", "PRODUCT", "EXHIBITOR", "PROGRAM"] | None = Query(
        default=None, alias="type"
    ),
    sort: Literal["RECOMMENDED"] = Query(default="RECOMMENDED"),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=50),
) -> Envelope[RecommendationSessionItemsResponse]:
    subject = resolve_subject_context(request)

    match_run = await db.get(MatchRun, recommendation_session_id)
    if (
        match_run is None
        or match_run.tenant_id != subject.tenant_id
        or match_run.event_id != subject.event_id
        or match_run.profile_id != subject.profile_id
    ):
        # 인터페이스 명세 5절: "모든 리소스 조회는 역할뿐 아니라 tenant_id, event_id, 소유권을
        # 검사한다." 존재 여부를 노출하지 않기 위해 404 대신 403으로 통일한다.
        _raise_http(resource_forbidden("본인 소유의 추천 세션만 조회할 수 있습니다."))

    stmt = (
        select(MatchResult, Recommendable, SlateItem)
        .join(
            Recommendable,
            Recommendable.recommendable_id == MatchResult.recommendable_id,
        )
        .outerjoin(SlateItem, SlateItem.match_result_id == MatchResult.match_result_id)
        .where(MatchResult.recommendation_session_id == recommendation_session_id)
    )
    if object_type:
        internal_object_type = _PUBLIC_TO_INTERNAL_OBJECT_TYPE.get(
            object_type, object_type
        )
        stmt = stmt.where(Recommendable.object_type == internal_object_type)
    if cursor:
        try:
            after_rank = _decode_rank_cursor(cursor)
        except RecommendationError as error:
            _raise_http(error)
            raise  # pragma: no cover
        stmt = stmt.where(MatchResult.rank > after_rank)
    # sort=RECOMMENDED가 기본이자 유일하게 지원하는 정렬이다(순위 자체가 이미 최종 추천
    # 순서). TODO(다른 정렬 기준이 정책으로 확정되면 분기 추가).
    stmt = stmt.order_by(MatchResult.rank.asc()).limit(limit + 1)

    rows = (await db.execute(stmt)).all()
    has_more = len(rows) > limit
    rows = rows[:limit]

    items: list[RecommendationItem] = []
    for match_result, recommendable, slate_item in rows:
        context_details = match_result.context_details or {}
        reasons = (
            (
                await db.execute(
                    select(MatchReason)
                    .where(MatchReason.match_result_id == match_result.match_result_id)
                    .order_by(MatchReason.display_order)
                )
            )
            .scalars()
            .all()
        )
        object_id, exhibitor_id = await _resolve_result_object_id(db, recommendable)
        public_object_type = _INTERNAL_TO_PUBLIC_OBJECT_TYPE.get(
            recommendable.object_type, recommendable.object_type
        )
        items.append(
            RecommendationItem(
                match_result_id=match_result.match_result_id,
                rank=match_result.rank,
                object_type=public_object_type,
                object_id=object_id,
                exhibitor_id=exhibitor_id,
                match_level=score_to_match_level(
                    float(match_result.final_score or 0.0)
                ),
                reasons=[
                    ReasonView(
                        code=r.reason_code,
                        text=r.reason_text or "",
                        evidence_refs=r.evidence_refs or [],
                    )
                    for r in reasons
                ],
                distance_meters=context_details.get("distance_meters"),
                estimated_walk_minutes=context_details.get("estimated_walk_minutes"),
                estimated_wait_minutes=context_details.get("estimated_wait_minutes"),
                status_observed_at=context_details.get("status_observed_at"),
                availability=AvailabilityView(
                    **(context_details.get("availability") or {})
                ),
                recommended_action=match_result.recommended_action or "SAVE_FOR_LATER",
                slot_type=slate_item.slot_type if slate_item else "CORE",
                related_object_ids=(
                    slate_item.related_object_ids if slate_item else []
                ),
                recommendation_confidence=(
                    float(match_result.recommendation_confidence)
                    if match_result.recommendation_confidence is not None
                    else None
                ),
                cold_start_status=(match_result.cold_start_details or {}).get("state"),
                cold_start_reason_codes=(
                    (match_result.cold_start_details or {}).get("reason_codes") or []
                ),
            )
        )

    stale = bool(match_run.expires_at and match_run.expires_at < datetime.now(UTC))
    next_cursor = _encode_rank_cursor(rows[-1][0].rank) if has_more and rows else None

    return Envelope(
        data=RecommendationSessionItemsResponse(
            items=items, next_cursor=next_cursor, stale=stale
        ),
        meta=_meta(subject.request_id),
    )


# ---------------------------------------------------------------------------
# 16.1 행동 이벤트 등록 (조회·저장·제외 등)
# ---------------------------------------------------------------------------

_MAX_CONTEXT_STRING_LENGTH = 500
_ALLOWED_CONTEXT_KEYS = frozenset(
    {
        "source",
        "component",
        "variant",
        "reason_code",
        "network_state",
        "offline_replay",
    }
)


def _sanitize_context(
    context: dict[str, Any] | None, *, zone: str | None
) -> dict[str, Any] | None:
    """16.2절 마지막 문단: 직접 식별정보·자유메모 원문·OTP·토큰·전체 URL query string 금지.

    스키마만으로는 강제할 수 없어(자유 dict) 여기서 명백히 위험한 키·값을 걸러낸다.
    """

    sanitized: dict[str, Any] = {"zone": zone} if zone else {}
    for key, value in (context or {}).items():
        if key not in _ALLOWED_CONTEXT_KEYS:
            continue
        if isinstance(value, str):
            if len(value) > _MAX_CONTEXT_STRING_LENGTH:
                continue
        elif not isinstance(value, bool | int | float) and value is not None:
            continue
        sanitized[key] = value
    return sanitized or None


def _event_payload_hash(event: InteractionEventIn) -> str:
    payload = json.dumps(
        event.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


async def _resolve_recommendable_id(
    db: AsyncSession, subject: SubjectContext, event: InteractionEventIn
) -> uuid.UUID | None:
    if event.match_result_id is not None:
        if event.recommendation_session_id is None:
            return None
        return (
            await db.execute(
                select(MatchResult.recommendable_id).where(
                    MatchResult.match_result_id == event.match_result_id,
                    MatchResult.recommendation_session_id
                    == event.recommendation_session_id,
                    MatchResult.tenant_id == subject.tenant_id,
                    MatchResult.event_id == subject.event_id,
                )
            )
        ).scalar_one_or_none()

    if not event.object_type or not event.object_id:
        return None
    try:
        domain_id = uuid.UUID(event.object_id)
    except ValueError:
        return None

    if event.object_type == "BOOTH":
        column = Recommendable.booth_id
    elif event.object_type == "PRODUCT":
        return (
            await db.execute(
                select(Recommendable.recommendable_id)
                .join(
                    EventProduct,
                    EventProduct.event_product_id == Recommendable.event_product_id,
                )
                .where(
                    EventProduct.product_id == domain_id,
                    Recommendable.tenant_id == subject.tenant_id,
                    Recommendable.event_id == subject.event_id,
                )
                .limit(1)
            )
        ).scalar_one_or_none()
    elif event.object_type == "PROGRAM":
        column = Recommendable.program_id
    elif event.object_type == "EXHIBITOR":
        # 공개 object_id는 exhibitor_id지만 recommendable은 participation_id를 저장한다
        # (app/models/matching.py Recommendable 참고) - 한 번 더 조회해 변환한다.
        participation_id = (
            await db.execute(
                select(ExhibitorParticipation.participation_id).where(
                    ExhibitorParticipation.exhibitor_id == domain_id,
                    ExhibitorParticipation.tenant_id == subject.tenant_id,
                    ExhibitorParticipation.event_id == subject.event_id,
                )
            )
        ).scalar_one_or_none()
        if participation_id is None:
            return None
        domain_id = participation_id
        column = Recommendable.participation_id
    else:
        return None

    return (
        await db.execute(
            select(Recommendable.recommendable_id).where(
                column == domain_id,
                Recommendable.tenant_id == subject.tenant_id,
                Recommendable.event_id == subject.event_id,
            )
        )
    ).scalar_one_or_none()


@router.post("/interactions/batch", response_model=Envelope[InteractionBatchResponse])
async def submit_interaction_batch(
    payload: InteractionBatchRequest,
    request: Request,
    db: DbSession,
) -> Envelope[InteractionBatchResponse]:
    subject = resolve_subject_context(request)

    results: list[InteractionEventResult] = []
    accepted = 0

    for event in payload.events:
        if event.event_type not in CANONICAL_EVENTS:
            results.append(
                InteractionEventResult(
                    client_event_id=event.client_event_id,
                    interaction_event_id=None,
                    accepted=False,
                    reason="UNKNOWN_EVENT_TYPE",
                )
            )
            continue

        event_date = event.occurred_at.astimezone(UTC).date()
        payload_hash = _event_payload_hash(event)

        if event.recommendation_session_id is not None:
            owned_session = (
                await db.execute(
                    select(MatchRun.recommendation_session_id).where(
                        MatchRun.recommendation_session_id
                        == event.recommendation_session_id,
                        MatchRun.tenant_id == subject.tenant_id,
                        MatchRun.event_id == subject.event_id,
                        MatchRun.profile_id == subject.profile_id,
                    )
                )
            ).scalar_one_or_none()
            if owned_session is None:
                results.append(
                    InteractionEventResult(
                        client_event_id=event.client_event_id,
                        interaction_event_id=None,
                        accepted=False,
                        reason="SESSION_FORBIDDEN",
                    )
                )
                continue

        if event.client_event_id is not None:
            existing_claim = (
                await db.execute(
                    select(InteractionClientEventDedupe)
                    .where(
                        InteractionClientEventDedupe.tenant_id == subject.tenant_id,
                        InteractionClientEventDedupe.client_event_id
                        == event.client_event_id,
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()
            if existing_claim is not None:
                # 4.2절: 같은 클라이언트 이벤트를 재전송한 경우 최초 결과를 재사용한다
                # (오프라인 재전송 지원 - 20절 "체크인·피드백은 오프라인 큐 재전송을 허용한다").
                same_payload = existing_claim.payload_hash == payload_hash
                results.append(
                    InteractionEventResult(
                        client_event_id=event.client_event_id,
                        interaction_event_id=(
                            existing_claim.interaction_event_id
                            if same_payload
                            else None
                        ),
                        accepted=same_payload,
                        reason=(
                            "DUPLICATE_IGNORED"
                            if same_payload
                            else "IDEMPOTENCY_CONFLICT"
                        ),
                    )
                )
                accepted += int(same_payload)
                continue

        recommendable_id = await _resolve_recommendable_id(db, subject, event)
        if event.match_result_id is not None and recommendable_id is None:
            results.append(
                InteractionEventResult(
                    client_event_id=event.client_event_id,
                    interaction_event_id=None,
                    accepted=False,
                    reason="MATCH_RESULT_NOT_FOUND",
                )
            )
            continue

        slate_projection: tuple[SlateItem, SlateResult] | None = None
        if event.event_type == "RECOMMENDATION_IMPRESSION":
            slate_projection = (
                await db.execute(
                    select(SlateItem, SlateResult)
                    .join(
                        SlateResult,
                        SlateResult.slate_result_id == SlateItem.slate_result_id,
                    )
                    .where(
                        SlateItem.match_result_id == event.match_result_id,
                        SlateResult.recommendation_session_id
                        == event.recommendation_session_id,
                        SlateResult.tenant_id == subject.tenant_id,
                        SlateResult.event_id == subject.event_id,
                    )
                )
            ).first()
            if slate_projection is None:
                results.append(
                    InteractionEventResult(
                        client_event_id=event.client_event_id,
                        interaction_event_id=None,
                        accepted=False,
                        reason="SLATE_ITEM_NOT_FOUND",
                    )
                )
                continue
            slate_item, _slate_result = slate_projection
            if event.rank_at_event != slate_item.final_rank:
                results.append(
                    InteractionEventResult(
                        client_event_id=event.client_event_id,
                        interaction_event_id=None,
                        accepted=False,
                        reason="IMPRESSION_RANK_MISMATCH",
                    )
                )
                continue
        if (event.object_type or event.object_id) and recommendable_id is None:
            results.append(
                InteractionEventResult(
                    client_event_id=event.client_event_id,
                    interaction_event_id=None,
                    accepted=False,
                    reason="TARGET_NOT_FOUND",
                )
            )
            continue

        row = InteractionEvent(
            event_date=event_date,
            interaction_event_id=new_uuid7(),
            tenant_id=subject.tenant_id,
            event_id=subject.event_id,
            user_id=subject.user_id,
            guest_session_id=subject.guest_session_id,
            visit_session_id=subject.visit_session_id,
            event_type=event.event_type,
            recommendable_id=recommendable_id,
            recommendation_session_id=event.recommendation_session_id,
            match_result_id=event.match_result_id,
            rank_at_event=event.rank_at_event,
            screen_code=event.screen,
            context_json=_sanitize_context(event.context, zone=event.zone),
            client_event_id=event.client_event_id,
            consent_snapshot_id=event.consent_snapshot_id,
            occurred_at=event.occurred_at,
        )
        try:
            async with db.begin_nested():
                db.add(row)
                if event.client_event_id is not None:
                    db.add(
                        InteractionClientEventDedupe(
                            tenant_id=subject.tenant_id,
                            event_id=subject.event_id,
                            client_event_id=event.client_event_id,
                            event_date=event_date,
                            interaction_event_id=row.interaction_event_id,
                            payload_hash=payload_hash,
                        )
                    )
                if slate_projection is not None:
                    slate_item, slate_result = slate_projection
                    db.add(
                        RecommendationImpression(
                            tenant_id=subject.tenant_id,
                            event_id=subject.event_id,
                            event_date=event_date,
                            interaction_event_id=row.interaction_event_id,
                            user_id=subject.user_id,
                            guest_session_id=subject.guest_session_id,
                            visit_session_id=subject.visit_session_id,
                            slate_result_id=slate_result.slate_result_id,
                            slate_item_id=slate_item.slate_item_id,
                            recommendable_id=slate_item.recommendable_id,
                            exhibitor_id=slate_item.exhibitor_id,
                            object_type=slate_item.object_type,
                            final_rank=slate_item.final_rank,
                            slot_type=slate_item.slot_type,
                            content_type="PERSONALIZED_RECOMMENDATION",
                            visible_duration_ms=event.visible_duration_ms or 0,
                            occurred_at=event.occurred_at,
                        )
                    )
                await db.flush()
        except SQLAlchemyError:
            existing_claim = None
            if event.client_event_id is not None:
                existing_claim = (
                    await db.execute(
                        select(InteractionClientEventDedupe)
                        .where(
                            InteractionClientEventDedupe.tenant_id == subject.tenant_id,
                            InteractionClientEventDedupe.client_event_id
                            == event.client_event_id,
                        )
                        .limit(1)
                    )
                ).scalar_one_or_none()
            if (
                existing_claim is not None
                and existing_claim.payload_hash == payload_hash
            ):
                results.append(
                    InteractionEventResult(
                        client_event_id=event.client_event_id,
                        interaction_event_id=existing_claim.interaction_event_id,
                        accepted=True,
                        reason="DUPLICATE_IGNORED",
                    )
                )
                accepted += 1
                continue
            if existing_claim is not None:
                results.append(
                    InteractionEventResult(
                        client_event_id=event.client_event_id,
                        interaction_event_id=None,
                        accepted=False,
                        reason="IDEMPOTENCY_CONFLICT",
                    )
                )
                continue
            results.append(
                InteractionEventResult(
                    client_event_id=event.client_event_id,
                    interaction_event_id=None,
                    accepted=False,
                    reason="PERSIST_FAILED",
                )
            )
            continue

        results.append(
            InteractionEventResult(
                client_event_id=event.client_event_id,
                interaction_event_id=row.interaction_event_id,
                accepted=True,
            )
        )
        accepted += 1

    await db.commit()

    return Envelope(
        data=InteractionBatchResponse(
            accepted=accepted, rejected=len(results) - accepted, results=results
        ),
        meta=_meta(subject.request_id),
    )
