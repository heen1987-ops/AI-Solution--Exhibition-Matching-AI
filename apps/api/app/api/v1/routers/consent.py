"""동의(consent) 등록·조회 및 개인정보 권리 요청(privacy-requests) 라우터.

근거 문서
---------
- docs/frontend-backend-ai-interface-spec.md
    5절(화면·API 매핑: U-03 자격·동의 -> PUT /consents/me, U-22 동의·권리 ->
    /consents/me, /privacy-requests) - 라우트 경로의 1차 근거.
    7.4절(자격·동의) - 요청 payload 형태(purpose/document_version/accepted 배열), "연령확인은
    마케팅 동의가 아니라 서비스 적격 확인", "동의 변경은 현재 상태와 불변 이력을 모두 남긴다"는
    원칙의 1차 근거.
    19절(오류 코드) - VALIDATION_FAILED/AUTH_REQUIRED 등 오류 코드의 1차 근거.
- docs/db-erd-table-spec.md 9.1~9.3절 - profile.consent_policy/user_consent,
  privacy.privacy_request 컬럼명의 1차 근거(backend/app/models/consent.py가 이미 구현했고,
  이 라우터는 그 모델을 그대로 사용한다).
- docs/user-ia-wireframes.md 5.1절 - U-03(`POST /consents`), U-22(`GET/PATCH /consents`).
  인터페이스 명세가 최종 근거이므로 실제 경로는 PUT/GET /consents/me로 통일하되, 와이어프레임
  표기와도 호환되도록 PATCH /consents/me 별칭도 같은 핸들러에 연결한다.

라우트 등록 방식에 대한 메모 (중요)
------------------------------------
이 라우터는 /consents/me와 /privacy-requests 두 개의 서로 다른 최상위 리소스에 걸쳐
있어(9~22절 U-22 화면이 이 둘을 함께 쓴다) app/api/v1/endpoints/ontology.py처럼 공통
prefix를 붙이는 방식을 쓸 수 없다. 아래 모든 경로는 이미 /api/v1 하위 완전한 상대경로다.
통합 시(app/api/v1/api.py, 이 작업 범위 밖) prefix 없이 등록해야 한다:

    from app.api.v1.routers import consent as consent_router
    api_router.include_router(consent_router.router, tags=["consent"])

현재 주체 해석(get_current_subject)은 app.api.v1.routers.profile 모듈의 것을 그대로
재사용한다 - 두 라우터가 이번 작업에서 함께 만들어지는 온보딩 도메인이고, 동의 등록도
프로파일과 동일한 (tenant_id, event_id, user_id|guest_session_id) 주체 개념을 쓰기 때문이다.
"""

from __future__ import annotations

import base64
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.routers.profile import (
    CurrentSubject,
    api_error,
    build_envelope,
    get_current_subject,
    get_request_id,
)
from app.db.session import get_db
from app.models.consent import ConsentPolicy, PrivacyRequest, UserConsent
from app.schemas.profile import Envelope

router = APIRouter()


# ---------------------------------------------------------------------------
# 요청/응답 스키마 (동의·개인정보 권리 요청은 이 파일 하나뿐이라 별도 schemas 파일을 두지
# 않고 여기 인라인으로 정의한다 - 작업 지시가 명시한 산출물 목록에 schemas/consent.py가
# 없다).
# ---------------------------------------------------------------------------


class ConsentItem(BaseModel):
    # db-erd 9.1절: purpose는 "예시"로만 나열되어 자유 문자열이다 (하드코딩 Enum 금지 원칙).
    purpose: str = Field(min_length=1, max_length=50)
    document_version: str = Field(min_length=1, max_length=50)
    accepted: bool
    source_channel: Literal["WEB", "QR", "KIOSK"] | None = None


class ConsentsPutRequest(BaseModel):
    consents: list[ConsentItem] = Field(min_length=1)


class ConsentStateItem(BaseModel):
    purpose: str
    document_version: str
    accepted: bool
    occurred_at: datetime
    required_for: str | None = None


class ConsentsPutResponse(BaseModel):
    consents: list[ConsentStateItem]


class ConsentsGetResponse(BaseModel):
    consents: list[ConsentStateItem]


class PrivacyRequestCreate(BaseModel):
    request_type: Literal["ACCESS", "EXPORT", "CORRECT", "DELETE", "WITHDRAW"]
    scope: dict[str, Any] | None = None


class PrivacyRequestView(BaseModel):
    privacy_request_id: uuid.UUID
    request_type: str
    status: str
    requested_at: datetime
    due_at: datetime | None
    completed_at: datetime | None


class PrivacyRequestListResponse(BaseModel):
    items: list[PrivacyRequestView]
    next_cursor: str | None = None


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------

# TODO(법령 근거 확인 필요, 합리적 기본값): 개인정보보호법 등 정확한 처리기한 규정을 반영해야
# 한다. 지금은 접수 후 30일을 기본 처리기한으로 둔다.
_PRIVACY_REQUEST_DUE_DAYS = 30


async def _resolve_consent_policy(
    db: AsyncSession, subject: CurrentSubject, purpose: str, document_version: str
) -> ConsentPolicy:
    """(tenant, 행사 또는 공통, purpose, document_version)에 맞는 유효 정책을 찾는다.

    db-erd 9.1절: "행사별 정책, 공통이면 event_id NULL". 행사 전용 정책이 있으면 그것을,
    없으면 공통(event_id IS NULL) 정책을 쓴다.
    """

    now = datetime.now(timezone.utc)
    stmt = (
        select(ConsentPolicy)
        .where(
            ConsentPolicy.tenant_id == subject.tenant_id,
            or_(ConsentPolicy.event_id == subject.event_id, ConsentPolicy.event_id.is_(None)),
            ConsentPolicy.purpose == purpose,
            ConsentPolicy.document_version == document_version,
            ConsentPolicy.effective_from <= now,
            or_(ConsentPolicy.effective_until.is_(None), ConsentPolicy.effective_until >= now),
        )
        .order_by(ConsentPolicy.event_id.is_(None).asc())
        .limit(1)
    )
    result = await db.execute(stmt)
    policy = result.scalars().first()
    if policy is None:
        raise api_error(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "VALIDATION_FAILED",
            f"등록되지 않았거나 만료된 동의 정책입니다: {purpose} ({document_version})",
            field_errors=[{"field": "purpose", "reason": "unknown_consent_policy"}],
        )
    return policy


def _encode_cursor(value: datetime) -> str:
    return base64.urlsafe_b64encode(value.isoformat().encode()).decode()


def _decode_cursor(cursor: str) -> datetime:
    try:
        return datetime.fromisoformat(base64.urlsafe_b64decode(cursor.encode()).decode())
    except (ValueError, UnicodeDecodeError) as exc:
        raise api_error(
            status.HTTP_400_BAD_REQUEST, "VALIDATION_FAILED", "cursor 형식이 올바르지 않습니다."
        ) from exc


# ===========================================================================
# 7.4절 자격·동의
# ===========================================================================


async def _upsert_consents(
    payload: ConsentsPutRequest,
    subject: CurrentSubject,
    request_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    recorded: list[ConsentStateItem] = []
    for item in payload.consents:
        policy = await _resolve_consent_policy(db, subject, item.purpose, item.document_version)
        consent = UserConsent(
            tenant_id=subject.tenant_id,
            event_id=subject.event_id,
            user_id=subject.user_id,
            guest_session_id=subject.guest_session_id,
            consent_policy_id=policy.consent_policy_id,
            accepted=item.accepted,
            source_channel=item.source_channel,
        )
        # db-erd 9.2절: "선택 이력은 불변으로 쌓는다 - 과거 행을 update하여 철회를 덮어쓰지
        # 않는다." 그래서 매번 새 행을 추가만 한다(append-only).
        db.add(consent)
        await db.flush()
        recorded.append(
            ConsentStateItem(
                purpose=policy.purpose,
                document_version=policy.document_version,
                accepted=consent.accepted,
                occurred_at=consent.occurred_at,
                required_for=policy.required_for,
            )
        )
    await db.commit()
    return build_envelope(ConsentsPutResponse(consents=recorded), request_id)


@router.put("/consents/me", response_model=Envelope[ConsentsPutResponse])
async def put_consents(
    payload: ConsentsPutRequest,
    subject: CurrentSubject = Depends(get_current_subject),
    request_id: str = Depends(get_request_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await _upsert_consents(payload, subject, request_id, db)


@router.patch("/consents/me", response_model=Envelope[ConsentsPutResponse])
async def patch_consents(
    payload: ConsentsPutRequest,
    subject: CurrentSubject = Depends(get_current_subject),
    request_id: str = Depends(get_request_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """와이어프레임 5.1절(U-22)의 PATCH /consents 표기 호환용 별칭. 동작은 PUT과 동일하다."""

    return await _upsert_consents(payload, subject, request_id, db)


@router.get("/consents/me", response_model=Envelope[ConsentsGetResponse])
async def get_consents(
    subject: CurrentSubject = Depends(get_current_subject),
    request_id: str = Depends(get_request_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """U-22 MY·동의관리 화면: purpose별 최신(현재) 동의 상태만 반환한다."""

    stmt = (
        select(UserConsent, ConsentPolicy)
        .join(ConsentPolicy, ConsentPolicy.consent_policy_id == UserConsent.consent_policy_id)
        .where(UserConsent.tenant_id == subject.tenant_id)
    )
    if subject.user_id is not None:
        stmt = stmt.where(UserConsent.user_id == subject.user_id)
    else:
        stmt = stmt.where(UserConsent.guest_session_id == subject.guest_session_id)
    stmt = stmt.order_by(UserConsent.occurred_at.asc())

    result = await db.execute(stmt)
    latest_by_purpose: dict[str, ConsentStateItem] = {}
    for consent, policy in result.all():
        # occurred_at 오름차순으로 훑으면서 덮어쓰므로 각 purpose의 마지막 값이 최신 상태다.
        latest_by_purpose[policy.purpose] = ConsentStateItem(
            purpose=policy.purpose,
            document_version=policy.document_version,
            accepted=consent.accepted,
            occurred_at=consent.occurred_at,
            required_for=policy.required_for,
        )

    data = ConsentsGetResponse(consents=list(latest_by_purpose.values()))
    return build_envelope(data, request_id)


# ===========================================================================
# 개인정보 권리 요청 (U-22, db-erd 9.3절)
# ===========================================================================


@router.post(
    "/privacy-requests",
    response_model=Envelope[PrivacyRequestView],
    status_code=status.HTTP_201_CREATED,
)
async def create_privacy_request(
    payload: PrivacyRequestCreate,
    subject: CurrentSubject = Depends(get_current_subject),
    request_id: str = Depends(get_request_id),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """개인정보 열람·이전·정정·삭제·철회 요청 접수.

    privacy.privacy_request.user_id는 NOT NULL이라(익명 게스트에게는 식별정보 보관소
    권리요청 개념이 아직 없다) 인증된 사용자만 접수할 수 있다.

    TODO(멱등성 저장소, 이 작업 범위 밖): Idempotency-Key 중복 감지는 integration 스키마의
    전용 멱등성 테이블이 필요하다. 지금은 헤더를 받기만 하고 실제 dedupe는 하지 않는다 -
    같은 키로 두 번 호출하면 요청이 두 번 생성될 수 있다.
    """

    del idempotency_key  # 위 TODO 참고. 서명은 계약 문서와 맞추기 위해 미리 받아둔다.

    if subject.user_id is None:
        raise api_error(
            status.HTTP_401_UNAUTHORIZED,
            "AUTH_REQUIRED",
            "개인정보 권리 요청은 인증된 계정에서만 접수할 수 있습니다.",
        )

    now = datetime.now(timezone.utc)
    privacy_request = PrivacyRequest(
        tenant_id=subject.tenant_id,
        user_id=subject.user_id,
        request_type=payload.request_type,
        scope_json=payload.scope,
        status="RECEIVED",
        requested_at=now,
        due_at=now + timedelta(days=_PRIVACY_REQUEST_DUE_DAYS),
    )
    db.add(privacy_request)
    await db.commit()

    data = PrivacyRequestView(
        privacy_request_id=privacy_request.privacy_request_id,
        request_type=privacy_request.request_type,
        status=privacy_request.status,
        requested_at=privacy_request.requested_at,
        due_at=privacy_request.due_at,
        completed_at=privacy_request.completed_at,
    )
    return build_envelope(data, request_id)


@router.get("/privacy-requests", response_model=Envelope[PrivacyRequestListResponse])
async def list_privacy_requests(
    subject: CurrentSubject = Depends(get_current_subject),
    request_id: str = Depends(get_request_id),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    if subject.user_id is None:
        raise api_error(status.HTTP_401_UNAUTHORIZED, "AUTH_REQUIRED", "인증이 필요합니다.")

    stmt = (
        select(PrivacyRequest)
        .where(
            PrivacyRequest.tenant_id == subject.tenant_id,
            PrivacyRequest.user_id == subject.user_id,
        )
        .order_by(PrivacyRequest.requested_at.desc())
    )
    if cursor:
        stmt = stmt.where(PrivacyRequest.requested_at < _decode_cursor(cursor))
    stmt = stmt.limit(limit + 1)

    result = await db.execute(stmt)
    rows = result.scalars().all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = _encode_cursor(rows[-1].requested_at) if has_more and rows else None

    data = PrivacyRequestListResponse(
        items=[
            PrivacyRequestView(
                privacy_request_id=row.privacy_request_id,
                request_type=row.request_type,
                status=row.status,
                requested_at=row.requested_at,
                due_at=row.due_at,
                completed_at=row.completed_at,
            )
            for row in rows
        ],
        next_cursor=next_cursor,
    )
    return build_envelope(data, request_id)


@router.get(
    "/privacy-requests/{privacy_request_id}", response_model=Envelope[PrivacyRequestView]
)
async def get_privacy_request(
    privacy_request_id: uuid.UUID,
    subject: CurrentSubject = Depends(get_current_subject),
    request_id: str = Depends(get_request_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    if subject.user_id is None:
        raise api_error(status.HTTP_401_UNAUTHORIZED, "AUTH_REQUIRED", "인증이 필요합니다.")

    privacy_request = await db.get(PrivacyRequest, privacy_request_id)
    if (
        privacy_request is None
        or privacy_request.tenant_id != subject.tenant_id
        or privacy_request.user_id != subject.user_id
    ):
        raise api_error(
            status.HTTP_403_FORBIDDEN,
            "RESOURCE_FORBIDDEN",
            "요청을 찾을 수 없거나 접근 권한이 없습니다.",
        )

    data = PrivacyRequestView(
        privacy_request_id=privacy_request.privacy_request_id,
        request_type=privacy_request.request_type,
        status=privacy_request.status,
        requested_at=privacy_request.requested_at,
        due_at=privacy_request.due_at,
        completed_at=privacy_request.completed_at,
    )
    return build_envelope(data, request_id)
