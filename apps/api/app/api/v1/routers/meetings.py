"""상담(미팅) API 라우터 - 요청 생성/조회/상태전이 + 참가업체 포털(E-02~E-04).

근거 문서
---------
- docs/frontend-backend-ai-interface-spec.md 12절(상담 API: 가능시간·요청·업체 응답),
  15절(참가업체 포털 API), 4절(API 공통 계약 - 성공/오류 응답 봉투, Idempotency-Key,
  ETag/version 낙관적 잠금), 19절(오류 코드) - 1차 근거.
- docs/user-ia-wireframes.md 5.1절 U-14(상담 요청)·U-15(상담 상태), 6.2절(상담 상태
  머신: draft/requested/accepted/counter_proposed/rejected/cancelled/completed/no_show),
  8절 E-01~E-04(참가업체 포털 화면) - 화면이 필요로 하는 데이터·흐름의 근거.
- backend/app/models/meeting.py - 실제 테이블·상태 상수(MEETING_STATUSES 등)·제약조건의
  정본. 이 라우터는 그 파일이 정의한 컬럼과 CHECK 제약을 벗어나는 값을 저장하지 않는다.

단일 상담 표면 (통합 MERGE STEP 22)
------------------------------------
이 라우터가 상담(미팅)의 유일한 HTTP 표면이다. 통합 전 worktree(WAVE 2C)에는
``/buyer/meeting-requests`` / ``/partner/meeting-requests`` 아래에 같은
``interaction.meeting`` 행을 쓰는 두 번째 라우터(``meeting_buyer_extension.py``)가 있었지만
등록하지 않았다 - 그 모듈 자신의 docstring이 "최종적으로는 ``/meetings`` 하나의 표면만
남아야 한다"고 명시했고, 두 표면을 함께 두면 같은 상담 레코드가 어느 URL로 호출됐는지에
따라 서로 다른 연락처 공개 규칙을 적용받기 때문이다. 그 표면이 갖고 있던 계약은 여기로
접어 넣었다: ``MeetingCreateRequest.product_id``/``order_scale_code``,
``PartnerDecisionRequest.enable_contact_sharing``(연락처 공개 세 번째 게이트),
``PartnerDecisionRequest.reason_code``의 6개 값 Literal. 상태 머신·게이트·오케스트레이션의
도메인 규칙은 ``app/services/meeting/buyer_matching.py``가 갖고 있고, 이 라우터와 그
서비스 계층은 같은 암호화 함수·같은 ``contact_reveal_allowed()``를 공유한다.

라우팅 경로에 대한 메모
------------------------
이 모듈은 서로 다른 세 경로 그룹(``/meetings``, ``/partner/meetings``,
``/exhibitors/{id}/availability``)을 하나의 라우터에 담는다. app/api/v1/api.py(공용
aggregator, 이 작업 범위 밖)가 이 router를 include_router할 때 접두사(prefix)를 주지
않아야 문서의 경로(``/api/v1/meetings``, ``/api/v1/partner/meetings/...``)와 정확히
일치한다:

    from app.api.v1.routers import meetings
    api_router.include_router(meetings.router, tags=["meetings"])

동시성·원자성 처리 요약 (작업 지시 "이중예약 방지" 핵심)
---------------------------------------------------------
- ``_reserve_slot``: availability_slot 점유를 "SELECT로 여유를 확인한 뒤 UPDATE"가 아니라
  단일 조건부 UPDATE(``WHERE status='OPEN' AND reserved_count < capacity``)로 수행한다.
  PostgreSQL은 이 UPDATE 문 자체가 대상 행에 트랜잭션 종료까지 유지되는 행 잠금을 걸므로,
  동시에 같은 슬롯을 점유하려는 두 번째 트랜잭션은 첫 번째가 끝날 때까지 대기했다가 이미
  줄어든 여유 용량으로 WHERE 절을 재평가해 자연스럽게 실패한다(0 rows). 이는
  ``SELECT ... FOR UPDATE``로 먼저 잠그고 별도 UPDATE를 보내는 것과 동일한 원자성을
  왕복 한 번으로 얻는 "조건부 UPDATE" 기법이다.
- 상담 자체(``meeting`` 행)의 상태 전이(수락/거절/변경제안, 취소, 변경제안 응답)는
  ``SELECT ... FOR UPDATE``로 행을 먼저 잠근 뒤 ``row_version``(낙관적 잠금, interface-spec
  12.4절의 ``version`` 필드)을 검사한다 - 같은 상담에 대한 동시 결정 요청을 직렬화하고,
  버전이 이미 바뀐 요청은 ``409 MEETING_VERSION_CONFLICT``로 거부한다.
- 확정(accepted) 시점의 담당자·바이어 시간대 중복은 meeting.py의 EXCLUDE 제약이 DB
  차원에서 한 번 더 막는다. 위반 시 ``IntegrityError``를 잡아 ``409 MEETING_CONFLICT``로
  변환한다(방어적 이중 안전장치 - 애플리케이션 로직에 버그가 있어도 DB가 최종 보증한다).

알려진 임시방편(TODO)과 이유
------------------------------
1. 인증: 바이어 프로파일과 업체 담당자는 검증된 서버 세션/JWT principal에서
   DB로 파생한다. ``X-Profile-Id``/``X-Staff-Id``는 권한 결정에 사용하지 않는다.
2. 멱등키 저장소: interaction/integration 스키마의 영속 멱등성 테이블이 아직 없어
   프로세스 내 메모리 캐시(``_IDEMPOTENCY_CACHE``)로 대체한다. 재시작·다중 인스턴스 환경에서
   재사용되지 않는 한계가 있다.
3. 봉투 암호화: 상담 메시지·메모·후속조치는 공용 AEAD 봉투 형식으로 저장한다.
   배포에서는 ``AUTH_ENCRYPTION_KEY_B64``를 반드시 외부 비밀 저장소로 주입한다.
4. 상담주제/결과/후속조치 코드값: 6단계 매칭 분류체계 문서가 최근 생겼지만
   MEETING_OUTCOME.*/FOLLOW_UP_ACTION.* 네임스페이스는 아직 시드되지 않았다(meeting.py
   자체 TODO). 상담주제(topic)는 카탈로그의 BUSINESS_GOAL 네임스페이스로 최선노력
   해석하고 실패하면 검증 오류로 막는다(하드 필터·근거로 쓰이는 값이라 신뢰 가능해야
   하므로). 결과·후속조치 코드는 조회용 부가정보라 해석에 실패해도 저장 자체는 막지
   않고 taxonomy 참조만 NULL로 남긴다.
5. 응답 봉투: interface-spec 4.3/4.4절의 ``{"success", "data"/"error", "meta"}`` 형태를
   그대로 구현한다. 같은 저장소의 app/api/v1/endpoints/ontology.py는 아직 이 봉투를
   적용하지 않았는데, 그건 이 라우터의 책임 범위가 아니다 - 통합 단계에서 공용 응답
   미들웨어로 일원화할 수 있다.
"""

from __future__ import annotations

import base64
import functools
import hashlib
import json
import threading
import uuid
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import case, func, literal, select, tuple_, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.router_auth import get_buyer_profile_id, get_staff_id
from app.db.session import get_db
from app.models.consent import AuditLog, ConsentPolicy
from app.models.exhibitor import ExhibitorParticipation, ExhibitorStaff, Product
from app.models.identity import UserAccount, UserIdentity
from app.models.matching import MatchResult, MatchRun
from app.models.meeting import (
    AvailabilitySlot,
    FollowUp,
    Lead,
    MeetingContactShare,
    MeetingRequest,
    MeetingSlotRequest,
    MeetingStatusHistory,
)
from app.models.profile import BuyerNeed, UserProfile
from app.schemas.meeting import (
    AvailabilityListResponse,
    AvailabilitySlotItem,
    BuyerNeedSummary,
    MeetingCancelRequest,
    MeetingCreateRequest,
    MeetingListResponse,
    MeetingOutcomeRequest,
    MeetingOutcomeResponse,
    MeetingRespondRequest,
    MeetingResponse,
    PartnerBuyerSummaryResponse,
    PartnerDecisionRequest,
    PartnerMeetingListItem,
    PartnerMeetingListResponse,
    SlotCandidate,
)
from app.services.meeting.buyer_matching import (
    contact_reveal_allowed,
    decrypt_meeting_text,
    enable_exhibitor_contact_sharing,
    encrypt_meeting_text,
    product_belongs_to_participation,
)
from meet_ai.ontology import Catalog, load_catalog
from meet_ai.ontology.catalog import stable_uuid

router = APIRouter()

_KST = timezone(timedelta(hours=9))

# --------------------------------------------------------------------------
# 행위자 식별 - 공용 어댑터(app/core/router_auth.py)가 정본이다.
# 아래 두 이름은 기존 Depends 참조와 테스트의 dependency_overrides 호환을 위한
# 동일 객체 별칭이다(헤더가 아니라 검증된 principal에서 파생한다).
# --------------------------------------------------------------------------

_buyer_profile_header = get_buyer_profile_id
_staff_header = get_staff_id


async def _load_active_staff(
    db: AsyncSession, staff_id: uuid.UUID | None
) -> ExhibitorStaff | None:
    if staff_id is None:
        return None
    staff = await db.get(ExhibitorStaff, staff_id)
    if staff is None or not staff.active:
        return None
    return staff


# --------------------------------------------------------------------------
# 응답 봉투 (interface-spec 4.3/4.4절)
# --------------------------------------------------------------------------


def _server_time() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _meta(request_id: str | None) -> dict[str, str]:
    return {
        "request_id": request_id or f"req_{uuid.uuid4().hex}",
        "server_time": _server_time(),
    }


def _ok(data: Any, *, request_id: str | None, status_code: int = 200) -> JSONResponse:
    payload = {
        "success": True,
        "data": jsonable_encoder(data),
        "meta": _meta(request_id),
    }
    return JSONResponse(status_code=status_code, content=payload)


def _fail(
    status_code: int,
    code: str,
    message: str,
    *,
    field_errors: list[dict[str, str]] | None = None,
    retryable: bool = False,
    retry_after_seconds: int | None = None,
    request_id: str | None = None,
) -> JSONResponse:
    payload = {
        "success": False,
        "error": {
            "code": code,
            "message": message,
            "field_errors": field_errors or [],
            "retryable": retryable,
            "retry_after_seconds": retry_after_seconds,
        },
        "meta": _meta(request_id),
    }
    return JSONResponse(status_code=status_code, content=payload)


# --------------------------------------------------------------------------
# 멱등키 처리 (모듈 docstring TODO 2 참고)
# --------------------------------------------------------------------------

_IDEMPOTENCY_LOCK = threading.Lock()
_IDEMPOTENCY_CACHE: dict[tuple[str, str, str], tuple[str, int, dict[str, Any]]] = {}


def _body_hash(body: dict[str, Any]) -> str:
    canonical = json.dumps(jsonable_encoder(body), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _idempotency_replay(
    idempotency_key: str | None,
    subject_id: str,
    path: str,
    body: dict[str, Any],
    *,
    request_id: str | None,
) -> JSONResponse | None:
    """같은 키·주체·경로·본문이면 저장된 결과를 재생하고, 본문이 다르면 409를 반환한다.

    None을 반환하면 호출자는 정상 처리를 계속하고 끝난 뒤 ``_idempotency_store``를
    호출해 결과를 기록해야 한다.
    """

    if not idempotency_key:
        return None
    key = (idempotency_key, subject_id, path)
    digest = _body_hash(body)
    with _IDEMPOTENCY_LOCK:
        cached = _IDEMPOTENCY_CACHE.get(key)
    if cached is None:
        return None
    cached_digest, cached_status, cached_payload = cached
    if cached_digest != digest:
        return _fail(
            409,
            "IDEMPOTENCY_KEY_REUSED",
            "동일한 Idempotency-Key가 다른 요청 본문과 함께 재사용되었습니다.",
            request_id=request_id,
        )
    return JSONResponse(status_code=cached_status, content=cached_payload)


def _idempotency_store(
    idempotency_key: str | None,
    subject_id: str,
    path: str,
    body: dict[str, Any],
    response: JSONResponse,
) -> None:
    if not idempotency_key:
        return
    key = (idempotency_key, subject_id, path)
    digest = _body_hash(body)
    payload = json.loads(bytes(response.body).decode("utf-8"))
    with _IDEMPOTENCY_LOCK:
        _IDEMPOTENCY_CACHE[key] = (digest, response.status_code, payload)


def _is_uuid(value: str | None) -> bool:
    if not value:
        return False
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True


# --------------------------------------------------------------------------
# AEAD 봉투 암호화 (모듈 docstring 3 참고)
#
# 정본은 app/services/meeting/buyer_matching.py에 있다. 상담 표면이 하나뿐이므로 라우터와
# 서비스 계층은 반드시 같은 봉투 형식·같은 purpose 태그·같은 fail-closed 동작을 쓴다.
# 아래 두 이름은 기존 호출부 호환을 위한 동일 객체 별칭이다.
# --------------------------------------------------------------------------

_encrypt_text = encrypt_meeting_text
_decrypt_text = decrypt_meeting_text


# --------------------------------------------------------------------------
# 불투명 커서 페이지네이션
# --------------------------------------------------------------------------


def _encode_cursor(created_at: datetime, row_id: uuid.UUID) -> str:
    raw = f"{created_at.isoformat()}|{row_id}"
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID] | None:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
        created_at_str, id_str = raw.split("|", 1)
        return datetime.fromisoformat(created_at_str), uuid.UUID(id_str)
    except Exception:
        return None


# --------------------------------------------------------------------------
# 온톨로지 코드 해석 (모듈 docstring TODO 4 참고)
# --------------------------------------------------------------------------

# U-14 화면의 상담주제 칩(입점·유통/OEM·PB/수출/기술·설비 등)은 catalog.v1.json의
# BUSINESS_GOAL 개념 타입(BIZ_GOAL.*)과 가장 가깝다. TODO(06-matching-ontology.md에
# 상담주제 전용 네임스페이스가 정의되면 교체).
_TOPIC_NAMESPACE_FALLBACKS: tuple[str, ...] = ("BIZ_GOAL",)
# meeting.py 자체 TODO: 아직 시드되지 않은 잠정 네임스페이스.
_OUTCOME_NAMESPACE_FALLBACKS: tuple[str, ...] = ("MEETING_OUTCOME",)
_FOLLOW_UP_NAMESPACE_FALLBACKS: tuple[str, ...] = ("FOLLOW_UP_ACTION",)


@functools.lru_cache(maxsize=1)
def _catalog() -> Catalog:
    return load_catalog()


@functools.lru_cache(maxsize=1)
def _concept_id_to_code() -> dict[uuid.UUID, str]:
    catalog = _catalog()
    return {
        stable_uuid("concept", item["code"]): item["code"] for item in catalog.concepts
    }


def _concept_code_for(concept_id: uuid.UUID | None) -> str | None:
    if concept_id is None:
        return None
    return _concept_id_to_code().get(concept_id)


def _resolve_concept(
    code: str, *, namespace_fallbacks: tuple[str, ...]
) -> tuple[uuid.UUID, uuid.UUID, str] | None:
    """자유 입력 코드를 카탈로그 concept_code로 해석한다 (정확한 코드 우선, 네임스페이스 접두 보정).

    성공하면 시드 생성기(meet_ai.ontology.catalog.emit_postgres_seed)와 동일한 규칙으로
    파생한 (taxonomy_version_id, concept_id, 실제 매칭된 코드)를 반환한다 - 그 시드가
    적용된 DB라면 여기서 계산한 concept_id가 ontology.concept_revision의 실제 행과
    일치한다.
    """

    catalog = _catalog()
    candidates = [code]
    if "." not in code:
        candidates.extend(f"{namespace}.{code}" for namespace in namespace_fallbacks)
    for candidate in candidates:
        try:
            catalog.get(candidate)
        except KeyError:
            continue
        return (
            stable_uuid("taxonomy-version", catalog.version),
            stable_uuid("concept", candidate),
            candidate,
        )
    return None


# --------------------------------------------------------------------------
# availability_slot 원자적 점유/반환
# --------------------------------------------------------------------------


async def _reserve_slot(
    db: AsyncSession, *, slot_id: uuid.UUID, participation_id: uuid.UUID
) -> AvailabilitySlot | None:
    """조건부 UPDATE로 슬롯을 원자적으로 점유한다 (모듈 docstring "동시성·원자성 처리 요약" 참고).

    매치되는 행이 없으면(이미 가득 찼거나 BLOCKED이거나 다른 참가업체 소속) None을 반환한다.
    """

    new_reserved_count = AvailabilitySlot.reserved_count + 1
    stmt = (
        update(AvailabilitySlot)
        .where(
            AvailabilitySlot.availability_slot_id == slot_id,
            AvailabilitySlot.participation_id == participation_id,
            AvailabilitySlot.status == "OPEN",
            AvailabilitySlot.reserved_count < AvailabilitySlot.capacity,
            AvailabilitySlot.start_at > func.now(),
        )
        .values(
            reserved_count=new_reserved_count,
            status=case(
                (new_reserved_count >= AvailabilitySlot.capacity, literal("FULL")),
                else_=AvailabilitySlot.status,
            ),
            row_version=AvailabilitySlot.row_version + 1,
        )
        .returning(AvailabilitySlot)
    )
    result = await db.execute(stmt)
    return result.scalars().first()


async def _release_slot(db: AsyncSession, *, slot_id: uuid.UUID) -> None:
    """``_reserve_slot``이 점유한 용량을 반환한다 (취소·거절·재제안 시 호출)."""

    new_reserved_count = AvailabilitySlot.reserved_count - 1
    stmt = (
        update(AvailabilitySlot)
        .where(
            AvailabilitySlot.availability_slot_id == slot_id,
            AvailabilitySlot.reserved_count > 0,
        )
        .values(
            reserved_count=new_reserved_count,
            status=case(
                (AvailabilitySlot.status == "BLOCKED", literal("BLOCKED")),
                (new_reserved_count < AvailabilitySlot.capacity, literal("OPEN")),
                else_=AvailabilitySlot.status,
            ),
            row_version=AvailabilitySlot.row_version + 1,
        )
    )
    await db.execute(stmt)


async def _release_all_held_slots(db: AsyncSession, meeting: MeetingRequest) -> None:
    """이 상담이 점유 중인 모든 슬롯 용량을 반환한다 (취소·거절 시 호출).

    meeting_slot_request.status='SELECTED'인 후보(요청 시점에 자동 점유되었거나 업체가
    COUNTER_PROPOSE로 새로 제안한 슬롯)와, 이미 확정된 confirmed_slot_id를 모두 대상으로
    한다. 후자는 accepted 상태에서 취소하는 경우에 필요하다.
    """

    stmt = select(MeetingSlotRequest).where(
        MeetingSlotRequest.meeting_id == meeting.meeting_id,
        MeetingSlotRequest.status == "SELECTED",
    )
    selected_rows = (await db.execute(stmt)).scalars().all()
    released_ids: set[uuid.UUID] = set()
    for row in selected_rows:
        await _release_slot(db, slot_id=row.availability_slot_id)
        released_ids.add(row.availability_slot_id)
        row.status = "WITHDRAWN"
    if (
        meeting.confirmed_slot_id is not None
        and meeting.confirmed_slot_id not in released_ids
    ):
        await _release_slot(db, slot_id=meeting.confirmed_slot_id)


# --------------------------------------------------------------------------
# 응답 조립 헬퍼
# --------------------------------------------------------------------------


async def _load_candidate_slots(
    db: AsyncSession, meeting_id: uuid.UUID
) -> list[SlotCandidate]:
    stmt = (
        select(MeetingSlotRequest, AvailabilitySlot)
        .join(
            AvailabilitySlot,
            AvailabilitySlot.availability_slot_id
            == MeetingSlotRequest.availability_slot_id,
        )
        .where(MeetingSlotRequest.meeting_id == meeting_id)
        .order_by(MeetingSlotRequest.preference_order)
    )
    rows = (await db.execute(stmt)).all()
    return [
        SlotCandidate(
            slot_id=slot.availability_slot_id,
            start_at=slot.start_at,
            end_at=slot.end_at,
            preference_order=slot_request.preference_order,
            request_status=slot_request.status,
        )
        for slot_request, slot in rows
    ]


async def _build_meeting_response(
    db: AsyncSession, meeting: MeetingRequest
) -> MeetingResponse:
    candidate_slots = await _load_candidate_slots(db, meeting.meeting_id)
    contact_share = (
        await db.execute(
            select(MeetingContactShare).where(
                MeetingContactShare.meeting_id == meeting.meeting_id
            )
        )
    ).scalar_one_or_none()
    participation = await db.get(ExhibitorParticipation, meeting.participation_id)
    return MeetingResponse(
        meeting_id=meeting.meeting_id,
        status=meeting.status,
        exhibitor_id=participation.exhibitor_id
        if participation
        else meeting.participation_id,
        participation_id=meeting.participation_id,
        topic_code=_concept_code_for(meeting.concept_id),
        message_preview=_decrypt_text(meeting.message_enc, purpose="meeting-message"),
        candidate_slots=candidate_slots,
        confirmed_start=meeting.confirmed_start,
        confirmed_end=meeting.confirmed_end,
        contact_share_accepted=contact_share is not None,
        contact_share_fields=list(contact_share.shared_fields) if contact_share else [],
        viewed_at=meeting.viewed_at,
        row_version=meeting.row_version,
        created_at=meeting.created_at,
        updated_at=meeting.updated_at,
    )


async def _match_result_belongs_to_profile(
    db: AsyncSession, match_result_id: uuid.UUID, profile_id: uuid.UUID
) -> bool:
    stmt = (
        select(MatchResult.match_result_id)
        .join(
            MatchRun,
            MatchRun.recommendation_session_id == MatchResult.recommendation_session_id,
        )
        .where(
            MatchResult.match_result_id == match_result_id,
            MatchRun.profile_id == profile_id,
        )
    )
    return (await db.execute(stmt)).scalar_one_or_none() is not None


# interface-spec 12.3절은 연락처 공유 동의의 purpose 코드명을 명시하지 않는다.
# consent_policy.purpose는 "예시" 값 목록의 자유 문자열이므로(consent.py docstring) 이
# 네임스페이스를 잠정 채택한다. TODO(동의 정책 상세설계 확정 후 재검증).
_MEETING_CONTACT_SHARE_PURPOSE = "MEETING_CONTACT_SHARE"


async def _resolve_meeting_contact_consent_policy(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    event_id: uuid.UUID,
    document_version: str | None,
) -> ConsentPolicy | None:
    stmt = select(ConsentPolicy).where(
        ConsentPolicy.tenant_id == tenant_id,
        (ConsentPolicy.event_id == event_id) | (ConsentPolicy.event_id.is_(None)),
        ConsentPolicy.purpose == _MEETING_CONTACT_SHARE_PURPOSE,
        ConsentPolicy.document_version == document_version,
    )
    return (await db.execute(stmt)).scalars().first()


# --------------------------------------------------------------------------
# 12.2 상담 가능시간
# --------------------------------------------------------------------------


@router.get("/exhibitors/{exhibitor_id}/availability")
async def list_availability(
    exhibitor_id: uuid.UUID,
    date_: Annotated[date, Query(alias="date")],
    topic: Annotated[str | None, Query()] = None,
    db: AsyncSession = Depends(get_db),
    buyer_profile_id: uuid.UUID | None = Depends(_buyer_profile_header),
    x_request_id: Annotated[str | None, Header(alias="X-Request-ID")] = None,
) -> JSONResponse:
    if buyer_profile_id is None:
        return _fail(
            401, "AUTH_REQUIRED", "인증이 필요합니다.", request_id=x_request_id
        )
    profile = await db.get(UserProfile, buyer_profile_id)
    if profile is None:
        return _fail(
            403,
            "RESOURCE_FORBIDDEN",
            "프로파일을 찾을 수 없습니다.",
            request_id=x_request_id,
        )

    participation_stmt = select(ExhibitorParticipation).where(
        ExhibitorParticipation.tenant_id == profile.tenant_id,
        ExhibitorParticipation.event_id == profile.event_id,
        ExhibitorParticipation.exhibitor_id == exhibitor_id,
    )
    participation = (await db.execute(participation_stmt)).scalar_one_or_none()
    if participation is None:
        return _fail(
            404,
            "RESOURCE_FORBIDDEN",
            "업체를 찾을 수 없습니다.",
            request_id=x_request_id,
        )

    topic_concept_id: uuid.UUID | None = None
    if topic:
        resolved = _resolve_concept(
            topic, namespace_fallbacks=_TOPIC_NAMESPACE_FALLBACKS
        )
        if resolved is not None:
            topic_concept_id = resolved[1]

    # 요청 date_는 interface-spec 2.4절 "UI는 Asia/Seoul로 표시" 원칙에 따라 KST 달력일로
    # 해석하고, DB에 저장된 UTC 시각과 비교하기 위해 KST 하루 경계를 계산한다.
    day_start = datetime.combine(date_, datetime.min.time(), tzinfo=_KST)
    day_end = datetime.combine(date_, datetime.max.time(), tzinfo=_KST)
    stmt = select(AvailabilitySlot).where(
        AvailabilitySlot.participation_id == participation.participation_id,
        AvailabilitySlot.status == "OPEN",
        AvailabilitySlot.start_at >= day_start,
        AvailabilitySlot.start_at <= day_end,
    )
    if topic_concept_id is not None:
        stmt = stmt.where(
            (AvailabilitySlot.concept_id == topic_concept_id)
            | (AvailabilitySlot.concept_id.is_(None))
        )
    stmt = stmt.order_by(AvailabilitySlot.start_at)
    rows = (await db.execute(stmt)).scalars().all()

    items = [
        AvailabilitySlotItem(
            slot_id=row.availability_slot_id,
            start_at=row.start_at,
            end_at=row.end_at,
            capacity=row.capacity,
            reserved_count=row.reserved_count,
            topic_code=_concept_code_for(row.concept_id),
            version=row.row_version,
        )
        for row in rows
    ]
    return _ok(AvailabilityListResponse(items=items), request_id=x_request_id)


# --------------------------------------------------------------------------
# 12.3 상담 요청 생성
# --------------------------------------------------------------------------


@router.post("/meetings")
async def create_meeting(
    payload: MeetingCreateRequest,
    db: AsyncSession = Depends(get_db),
    buyer_profile_id: uuid.UUID | None = Depends(_buyer_profile_header),
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    x_request_id: Annotated[str | None, Header(alias="X-Request-ID")] = None,
) -> JSONResponse:
    if buyer_profile_id is None:
        return _fail(
            401,
            "AUTH_REQUIRED",
            "휴대전화 인증 후 이용할 수 있습니다.",
            request_id=x_request_id,
        )

    subject = str(buyer_profile_id)
    path = "POST:/meetings"
    body_dict = payload.model_dump(mode="json")
    replay = _idempotency_replay(
        idempotency_key, subject, path, body_dict, request_id=x_request_id
    )
    if replay is not None:
        return replay

    profile = await db.get(UserProfile, buyer_profile_id)
    if profile is None or profile.deleted_at is not None:
        return _fail(
            403,
            "RESOURCE_FORBIDDEN",
            "프로파일을 찾을 수 없습니다.",
            request_id=x_request_id,
        )
    if profile.user_type != "BUYER":
        return _fail(
            403,
            "RESOURCE_FORBIDDEN",
            "바이어 프로파일만 상담을 요청할 수 있습니다.",
            request_id=x_request_id,
        )
    if profile.user_id is None:
        return _fail(
            401,
            "AUTH_REQUIRED",
            "휴대전화 인증 후 이용할 수 있습니다.",
            request_id=x_request_id,
        )
    account = await db.get(UserAccount, profile.user_id)
    if account is None or account.authentication_state not in (
        "PHONE_VERIFIED",
        "ACCOUNT_AUTHENTICATED",
    ):
        return _fail(
            401,
            "AUTH_REQUIRED",
            "휴대전화 인증 후 이용할 수 있습니다.",
            request_id=x_request_id,
        )

    participation_stmt = select(ExhibitorParticipation).where(
        ExhibitorParticipation.tenant_id == profile.tenant_id,
        ExhibitorParticipation.event_id == profile.event_id,
        ExhibitorParticipation.exhibitor_id == payload.exhibitor_id,
        ExhibitorParticipation.participation_status == "APPROVED",
    )
    participation = (await db.execute(participation_stmt)).scalar_one_or_none()
    if participation is None:
        return _fail(
            404,
            "RESOURCE_FORBIDDEN",
            "상담을 요청할 수 있는 업체를 찾을 수 없습니다.",
            request_id=x_request_id,
        )
    if not participation.consultation_enabled:
        return _fail(
            422,
            "NO_CANDIDATE",
            "이 업체는 현재 상담 요청을 받지 않습니다.",
            field_errors=[{"field": "exhibitor_id", "reason": "consultation_disabled"}],
            request_id=x_request_id,
        )

    # interaction.meeting에는 (participation_id, product_id) 복합 FK가 없으므로 "요청한
    # 제품이 정말 이 업체의 승인된 제품인가"는 애플리케이션 계층이 검증한다. 미승인/삭제된
    # 제품을 상담에 슬쩍 연결하는 경로를 막는다(AGENTS.md 승인 경계 불변식).
    if payload.product_id is not None:
        product = await db.get(Product, payload.product_id)
        if not product_belongs_to_participation(product, participation=participation):
            await db.rollback()
            return _fail(
                400,
                "VALIDATION_FAILED",
                "이 업체의 제품을 찾을 수 없습니다.",
                field_errors=[{"field": "product_id", "reason": "product_not_found"}],
                request_id=x_request_id,
            )

    topic_resolved = _resolve_concept(
        payload.topic, namespace_fallbacks=_TOPIC_NAMESPACE_FALLBACKS
    )
    if topic_resolved is None:
        return _fail(
            400,
            "VALIDATION_FAILED",
            "지원하지 않는 상담주제 코드입니다.",
            field_errors=[{"field": "topic", "reason": "unknown_taxonomy_code"}],
            request_id=x_request_id,
        )
    taxonomy_version_id, concept_id, _resolved_topic_code = topic_resolved

    reserved_slot: AvailabilitySlot | None = None
    for slot_id in payload.requested_slot_ids:
        candidate = await _reserve_slot(
            db, slot_id=slot_id, participation_id=participation.participation_id
        )
        if candidate is not None:
            reserved_slot = candidate
            break
    if reserved_slot is None:
        await db.rollback()
        return _fail(
            409,
            "MEETING_CONFLICT",
            "요청하신 시간에 여유가 없습니다. 다른 시간을 선택해 주세요.",
            retryable=True,
            request_id=x_request_id,
        )

    # meeting_id는 아래 자식 레코드(슬롯 요청·연락처 공유·상태이력)가 FK로 참조해야 하므로
    # 컬럼 기본값(default=uuid.uuid4, meeting.py)에 맡기지 않고 여기서 먼저 생성한다.
    meeting_id = uuid.uuid4()

    contact_share_row: MeetingContactShare | None = None
    if payload.contact_share is not None and payload.contact_share.accepted:
        consent_policy = await _resolve_meeting_contact_consent_policy(
            db,
            tenant_id=profile.tenant_id,
            event_id=profile.event_id,
            document_version=payload.contact_share.document_version,
        )
        if consent_policy is None:
            await db.rollback()
            return _fail(
                400,
                "VALIDATION_FAILED",
                "알 수 없는 연락처 공유 동의 문서 버전입니다.",
                field_errors=[
                    {
                        "field": "contact_share.document_version",
                        "reason": "unknown_document_version",
                    }
                ],
                request_id=x_request_id,
            )
        contact_share_row = MeetingContactShare(
            meeting_contact_share_id=uuid.uuid4(),
            meeting_id=meeting_id,
            consent_policy_id=consent_policy.consent_policy_id,
            shared_fields=payload.contact_share.fields,
            accepted_at=datetime.now(UTC),
        )

    match_result_id: uuid.UUID | None = None
    if payload.match_result_id is not None:
        if await _match_result_belongs_to_profile(
            db, payload.match_result_id, profile.profile_id
        ):
            match_result_id = payload.match_result_id

    meeting = MeetingRequest(
        meeting_id=meeting_id,
        tenant_id=profile.tenant_id,
        event_id=profile.event_id,
        buyer_profile_id=profile.profile_id,
        participation_id=participation.participation_id,
        staff_id=reserved_slot.staff_id,
        booth_id=reserved_slot.booth_id,
        taxonomy_version_id=taxonomy_version_id,
        concept_id=concept_id,
        product_id=payload.product_id,
        order_scale_code=payload.order_scale_code,
        message_enc=_encrypt_text(payload.message, purpose="meeting-message"),
        status="requested",
        match_result_id=match_result_id,
    )
    db.add(meeting)

    for order, slot_id in enumerate(payload.requested_slot_ids, start=1):
        db.add(
            MeetingSlotRequest(
                meeting_slot_request_id=uuid.uuid4(),
                meeting_id=meeting_id,
                availability_slot_id=slot_id,
                preference_order=order,
                status="SELECTED"
                if slot_id == reserved_slot.availability_slot_id
                else "PENDING",
            )
        )

    if contact_share_row is not None:
        db.add(contact_share_row)

    db.add(
        MeetingStatusHistory(
            meeting_status_history_id=uuid.uuid4(),
            meeting_id=meeting_id,
            previous_status=None,
            new_status="requested",
            changed_by_user_id=profile.user_id,
            request_id=uuid.UUID(idempotency_key)
            if _is_uuid(idempotency_key)
            else None,
        )
    )

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return _fail(
            409,
            "MEETING_CONFLICT",
            "요청을 처리하는 중 충돌이 발생했습니다. 다시 시도해 주세요.",
            retryable=True,
            request_id=x_request_id,
        )

    data = await _build_meeting_response(db, meeting)
    response = _ok(data, request_id=x_request_id, status_code=201)
    _idempotency_store(idempotency_key, subject, path, body_dict, response)
    return response


# --------------------------------------------------------------------------
# 조회 (바이어)
# --------------------------------------------------------------------------


@router.get("/meetings")
async def list_meetings(
    db: AsyncSession = Depends(get_db),
    buyer_profile_id: uuid.UUID | None = Depends(_buyer_profile_header),
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    x_request_id: Annotated[str | None, Header(alias="X-Request-ID")] = None,
) -> JSONResponse:
    if buyer_profile_id is None:
        return _fail(
            401, "AUTH_REQUIRED", "인증이 필요합니다.", request_id=x_request_id
        )

    stmt = select(MeetingRequest).where(
        MeetingRequest.buyer_profile_id == buyer_profile_id
    )
    if status_filter:
        stmt = stmt.where(MeetingRequest.status == status_filter)
    decoded = _decode_cursor(cursor) if cursor else None
    if decoded is not None:
        cursor_created_at, cursor_id = decoded
        stmt = stmt.where(
            tuple_(MeetingRequest.created_at, MeetingRequest.meeting_id)
            < (cursor_created_at, cursor_id)
        )
    stmt = stmt.order_by(
        MeetingRequest.created_at.desc(), MeetingRequest.meeting_id.desc()
    ).limit(limit + 1)
    rows = list((await db.execute(stmt)).scalars().all())

    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_cursor = _encode_cursor(rows[-1].created_at, rows[-1].meeting_id)

    items = [await _build_meeting_response(db, meeting) for meeting in rows]
    data = MeetingListResponse(items=items, next_cursor=next_cursor)
    return _ok(data, request_id=x_request_id)


@router.get("/meetings/{meeting_id}")
async def get_meeting(
    meeting_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    buyer_profile_id: uuid.UUID | None = Depends(_buyer_profile_header),
    x_request_id: Annotated[str | None, Header(alias="X-Request-ID")] = None,
) -> JSONResponse:
    if buyer_profile_id is None:
        return _fail(
            401, "AUTH_REQUIRED", "인증이 필요합니다.", request_id=x_request_id
        )
    meeting = await db.get(MeetingRequest, meeting_id)
    if meeting is None or meeting.buyer_profile_id != buyer_profile_id:
        return _fail(
            404,
            "RESOURCE_FORBIDDEN",
            "상담 요청을 찾을 수 없습니다.",
            request_id=x_request_id,
        )
    data = await _build_meeting_response(db, meeting)
    return _ok(data, request_id=x_request_id)


# --------------------------------------------------------------------------
# 상태 변경 (바이어: 취소, 변경제안 응답)
# --------------------------------------------------------------------------

_BUYER_CANCELLABLE_STATUSES = ("draft", "requested", "accepted", "counter_proposed")


@router.post("/meetings/{meeting_id}/cancel")
async def cancel_meeting(
    meeting_id: uuid.UUID,
    payload: MeetingCancelRequest,
    db: AsyncSession = Depends(get_db),
    buyer_profile_id: uuid.UUID | None = Depends(_buyer_profile_header),
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    x_request_id: Annotated[str | None, Header(alias="X-Request-ID")] = None,
) -> JSONResponse:
    if buyer_profile_id is None:
        return _fail(
            401, "AUTH_REQUIRED", "인증이 필요합니다.", request_id=x_request_id
        )

    subject = str(buyer_profile_id)
    path = f"POST:/meetings/{meeting_id}/cancel"
    body_dict = payload.model_dump(mode="json")
    replay = _idempotency_replay(
        idempotency_key, subject, path, body_dict, request_id=x_request_id
    )
    if replay is not None:
        return replay

    stmt = (
        select(MeetingRequest)
        .where(MeetingRequest.meeting_id == meeting_id)
        .with_for_update()
    )
    meeting = (await db.execute(stmt)).scalar_one_or_none()
    if meeting is None or meeting.buyer_profile_id != buyer_profile_id:
        await db.rollback()
        return _fail(
            404,
            "RESOURCE_FORBIDDEN",
            "상담 요청을 찾을 수 없습니다.",
            request_id=x_request_id,
        )
    if meeting.row_version != payload.version:
        await db.rollback()
        return _fail(
            409,
            "MEETING_VERSION_CONFLICT",
            "최신 상태를 다시 확인해 주세요.",
            request_id=x_request_id,
        )
    if meeting.status not in _BUYER_CANCELLABLE_STATUSES:
        await db.rollback()
        return _fail(
            409,
            "MEETING_CONFLICT",
            "이미 종료된 상담은 취소할 수 없습니다.",
            request_id=x_request_id,
        )

    await _release_all_held_slots(db, meeting)
    previous_status = meeting.status
    meeting.status = "cancelled"
    meeting.row_version += 1
    profile = await db.get(UserProfile, buyer_profile_id)
    db.add(
        MeetingStatusHistory(
            meeting_status_history_id=uuid.uuid4(),
            meeting_id=meeting.meeting_id,
            previous_status=previous_status,
            new_status="cancelled",
            changed_by_user_id=profile.user_id if profile else None,
            reason_code=payload.reason_code,
        )
    )
    await db.commit()

    data = await _build_meeting_response(db, meeting)
    response = _ok(data, request_id=x_request_id)
    _idempotency_store(idempotency_key, subject, path, body_dict, response)
    return response


@router.post("/meetings/{meeting_id}/respond")
async def respond_to_counter_proposal(
    meeting_id: uuid.UUID,
    payload: MeetingRespondRequest,
    db: AsyncSession = Depends(get_db),
    buyer_profile_id: uuid.UUID | None = Depends(_buyer_profile_header),
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    x_request_id: Annotated[str | None, Header(alias="X-Request-ID")] = None,
) -> JSONResponse:
    if buyer_profile_id is None:
        return _fail(
            401, "AUTH_REQUIRED", "인증이 필요합니다.", request_id=x_request_id
        )

    subject = str(buyer_profile_id)
    path = f"POST:/meetings/{meeting_id}/respond"
    body_dict = payload.model_dump(mode="json")
    replay = _idempotency_replay(
        idempotency_key, subject, path, body_dict, request_id=x_request_id
    )
    if replay is not None:
        return replay

    stmt = (
        select(MeetingRequest)
        .where(MeetingRequest.meeting_id == meeting_id)
        .with_for_update()
    )
    meeting = (await db.execute(stmt)).scalar_one_or_none()
    if meeting is None or meeting.buyer_profile_id != buyer_profile_id:
        await db.rollback()
        return _fail(
            404,
            "RESOURCE_FORBIDDEN",
            "상담 요청을 찾을 수 없습니다.",
            request_id=x_request_id,
        )
    if meeting.row_version != payload.version:
        await db.rollback()
        return _fail(
            409,
            "MEETING_VERSION_CONFLICT",
            "최신 상태를 다시 확인해 주세요.",
            request_id=x_request_id,
        )
    if meeting.status != "counter_proposed":
        await db.rollback()
        return _fail(
            409,
            "MEETING_CONFLICT",
            "변경 제안 상태의 상담만 응답할 수 있습니다.",
            request_id=x_request_id,
        )

    held_stmt = (
        select(MeetingSlotRequest, AvailabilitySlot)
        .join(
            AvailabilitySlot,
            AvailabilitySlot.availability_slot_id
            == MeetingSlotRequest.availability_slot_id,
        )
        .where(
            MeetingSlotRequest.meeting_id == meeting.meeting_id,
            MeetingSlotRequest.status == "SELECTED",
        )
    )
    held_rows = (await db.execute(held_stmt)).all()
    if not held_rows:
        await db.rollback()
        return _fail(
            409,
            "MEETING_CONFLICT",
            "제안된 시간을 찾을 수 없습니다.",
            request_id=x_request_id,
        )
    _held_slot_request, held_slot = held_rows[0]

    previous_status = meeting.status
    if payload.action == "ACCEPT_COUNTER":
        meeting.status = "accepted"
        meeting.confirmed_slot_id = held_slot.availability_slot_id
        meeting.confirmed_start = held_slot.start_at
        meeting.confirmed_end = held_slot.end_at
    else:
        await _release_all_held_slots(db, meeting)
        meeting.status = "cancelled"
    meeting.row_version += 1

    profile = await db.get(UserProfile, buyer_profile_id)
    db.add(
        MeetingStatusHistory(
            meeting_status_history_id=uuid.uuid4(),
            meeting_id=meeting.meeting_id,
            previous_status=previous_status,
            new_status=meeting.status,
            changed_by_user_id=profile.user_id if profile else None,
            reason_code=payload.reason_code,
        )
    )

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return _fail(
            409,
            "MEETING_CONFLICT",
            "겹치는 확정 상담이 있어 처리할 수 없습니다.",
            request_id=x_request_id,
        )

    data = await _build_meeting_response(db, meeting)
    response = _ok(data, request_id=x_request_id)
    _idempotency_store(idempotency_key, subject, path, body_dict, response)
    return response


# --------------------------------------------------------------------------
# 15절 참가업체 포털 - E-02 목록, E-03 바이어 상세
# --------------------------------------------------------------------------


@router.get("/partner/meetings")
async def list_partner_meetings(
    db: AsyncSession = Depends(get_db),
    staff_id: uuid.UUID | None = Depends(_staff_header),
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    x_request_id: Annotated[str | None, Header(alias="X-Request-ID")] = None,
) -> JSONResponse:
    staff = await _load_active_staff(db, staff_id)
    if staff is None:
        return _fail(
            401,
            "AUTH_REQUIRED",
            "파트너 계정 인증이 필요합니다.",
            request_id=x_request_id,
        )

    # wireframes 8절 E-02: "자기 업체 요청만" - 담당자 개인이 아니라 참가(participation)
    # 단위로 스코프한다(같은 업체 팀 전체가 볼 수 있음, exhibitor.py ExhibitorStaff docstring).
    stmt = select(MeetingRequest).where(
        MeetingRequest.participation_id == staff.participation_id
    )
    if status_filter:
        stmt = stmt.where(MeetingRequest.status == status_filter)
    decoded = _decode_cursor(cursor) if cursor else None
    if decoded is not None:
        cursor_created_at, cursor_id = decoded
        stmt = stmt.where(
            tuple_(MeetingRequest.created_at, MeetingRequest.meeting_id)
            < (cursor_created_at, cursor_id)
        )
    stmt = stmt.order_by(
        MeetingRequest.created_at.desc(), MeetingRequest.meeting_id.desc()
    ).limit(limit + 1)
    rows = list((await db.execute(stmt)).scalars().all())

    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_cursor = _encode_cursor(rows[-1].created_at, rows[-1].meeting_id)

    items = []
    for meeting in rows:
        candidate_slots = await _load_candidate_slots(db, meeting.meeting_id)
        items.append(
            PartnerMeetingListItem(
                meeting_id=meeting.meeting_id,
                status=meeting.status,
                topic_code=_concept_code_for(meeting.concept_id),
                candidate_slots=candidate_slots,
                confirmed_start=meeting.confirmed_start,
                confirmed_end=meeting.confirmed_end,
                viewed_at=meeting.viewed_at,
                created_at=meeting.created_at,
            )
        )
    data = PartnerMeetingListResponse(items=items, next_cursor=next_cursor)
    return _ok(data, request_id=x_request_id)


@router.get("/partner/meetings/{meeting_id}/buyer-summary")
async def get_partner_buyer_summary(
    meeting_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    staff_id: uuid.UUID | None = Depends(_staff_header),
    x_request_id: Annotated[str | None, Header(alias="X-Request-ID")] = None,
) -> JSONResponse:
    staff = await _load_active_staff(db, staff_id)
    if staff is None:
        return _fail(
            401,
            "AUTH_REQUIRED",
            "파트너 계정 인증이 필요합니다.",
            request_id=x_request_id,
        )

    meeting = await db.get(MeetingRequest, meeting_id)
    if meeting is None or meeting.participation_id != staff.participation_id:
        return _fail(
            404,
            "RESOURCE_FORBIDDEN",
            "상담 요청을 찾을 수 없습니다.",
            request_id=x_request_id,
        )

    # interface-spec 12.1절 "VIEWED는 상담 상태가 아니라 viewed_at 메타데이터" - 업체가
    # 바이어 상세를 처음 열람하는 시점을 "읽음" 표시로 기록한다(E-02 신규 요청 뱃지 근거).
    if meeting.viewed_at is None:
        meeting.viewed_at = datetime.now(UTC)

    buyer_need_row = (
        await db.execute(
            select(BuyerNeed).where(BuyerNeed.profile_id == meeting.buyer_profile_id)
        )
    ).scalar_one_or_none()
    buyer_need = (
        BuyerNeedSummary(
            organization_type=buyer_need_row.organization_type,
            target_price_min_amount=buyer_need_row.target_price_min_amount,
            target_price_max_amount=buyer_need_row.target_price_max_amount,
            currency=buyer_need_row.currency,
            monthly_units_min=buyer_need_row.monthly_units_min,
            monthly_units_max=buyer_need_row.monthly_units_max,
            decision_timeline=buyer_need_row.decision_timeline,
        )
        if buyer_need_row is not None
        else None
    )

    contact_share = (
        await db.execute(
            select(MeetingContactShare).where(
                MeetingContactShare.meeting_id == meeting.meeting_id
            )
        )
    ).scalar_one_or_none()

    contact: dict[str, str] | None = None
    # 연락처 공개 게이트는 app/services/meeting/buyer_matching.py의
    # contact_reveal_allowed()가 단일 진실 공급원이다: 상담 확정 + 바이어 동의 +
    # 업체측 명시적 opt-in(exhibitor_enabled_at) 세 조건을 모두 만족해야 한다.
    # wireframes 8절 E-03: "연락처 열람 시 목적 확인과 감사로그 기록".
    if contact_reveal_allowed(
        meeting_status=meeting.status, contact_share=contact_share
    ):
        assert contact_share is not None  # contact_reveal_allowed가 이미 보장
        buyer_profile = await db.get(UserProfile, meeting.buyer_profile_id)
        identity = None
        if buyer_profile is not None and buyer_profile.user_id is not None:
            identity = (
                await db.execute(
                    select(UserIdentity).where(
                        UserIdentity.user_id == buyer_profile.user_id
                    )
                )
            ).scalar_one_or_none()
        if identity is not None:
            # 식별정보도 동일 봉투 형식인 경우에만 복호화한다.
            # 구 평문/uc190상 데이터는 _decrypt_text가 None으로 차단한다.
            field_values = {
                "NAME": _decrypt_text(identity.name_enc, purpose="identity-name"),
                "PHONE": _decrypt_text(identity.phone_enc, purpose="identity-phone"),
                "BUSINESS_EMAIL": _decrypt_text(
                    identity.email_enc, purpose="identity-email"
                ),
                "EMAIL": _decrypt_text(identity.email_enc, purpose="identity-email"),
            }
            contact = {
                field: value
                for field in contact_share.shared_fields
                if (value := field_values.get(field)) is not None
            }
        if contact_share.disclosed_at is None:
            contact_share.disclosed_at = datetime.now(UTC)
            contact_share.disclosed_to_user_id = staff.user_id
            db.add(
                AuditLog(
                    # audit_log_id는 consent.py의 관례(new_uuid7 컬럼 기본값)에 맡긴다 -
                    # 이 요청 안에서 다른 레코드가 이 ID를 참조하지 않는다.
                    tenant_id=meeting.tenant_id,
                    event_id=meeting.event_id,
                    actor_user_id=staff.user_id,
                    actor_role="EXHIBITOR",
                    action_type="VIEW",
                    resource_type="interaction.meeting_contact_share",
                    resource_id=contact_share.meeting_contact_share_id,
                    reason_code="PARTNER_BUYER_CONTACT_VIEW",
                )
            )

    await db.commit()

    data = PartnerBuyerSummaryResponse(
        meeting_id=meeting.meeting_id,
        status=meeting.status,
        topic_code=_concept_code_for(meeting.concept_id),
        message_preview=_decrypt_text(meeting.message_enc, purpose="meeting-message"),
        buyer_need=buyer_need,
        contact=contact,
        contact_disclosed=contact is not None,
    )
    return _ok(data, request_id=x_request_id)


# --------------------------------------------------------------------------
# 12.4 업체 응답 (수락/거절/변경제안)
# --------------------------------------------------------------------------

_DECIDABLE_SOURCE_STATUSES: dict[str, tuple[str, ...]] = {
    "ACCEPT": ("requested", "counter_proposed"),
    "REJECT": ("requested", "counter_proposed"),
    "COUNTER_PROPOSE": ("requested",),
}


@router.post("/partner/meetings/{meeting_id}/decision")
async def decide_meeting(
    meeting_id: uuid.UUID,
    payload: PartnerDecisionRequest,
    db: AsyncSession = Depends(get_db),
    staff_id: uuid.UUID | None = Depends(_staff_header),
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    x_request_id: Annotated[str | None, Header(alias="X-Request-ID")] = None,
) -> JSONResponse:
    staff = await _load_active_staff(db, staff_id)
    if staff is None:
        return _fail(
            401,
            "AUTH_REQUIRED",
            "파트너 계정 인증이 필요합니다.",
            request_id=x_request_id,
        )

    subject = str(staff.staff_id)
    path = f"POST:/partner/meetings/{meeting_id}/decision"
    body_dict = payload.model_dump(mode="json")
    replay = _idempotency_replay(
        idempotency_key, subject, path, body_dict, request_id=x_request_id
    )
    if replay is not None:
        return replay

    stmt = (
        select(MeetingRequest)
        .where(MeetingRequest.meeting_id == meeting_id)
        .with_for_update()
    )
    meeting = (await db.execute(stmt)).scalar_one_or_none()
    if meeting is None or meeting.participation_id != staff.participation_id:
        await db.rollback()
        return _fail(
            404,
            "RESOURCE_FORBIDDEN",
            "상담 요청을 찾을 수 없습니다.",
            request_id=x_request_id,
        )
    if meeting.row_version != payload.version:
        await db.rollback()
        return _fail(
            409,
            "MEETING_VERSION_CONFLICT",
            "최신 상태를 다시 확인해 주세요.",
            request_id=x_request_id,
        )
    allowed_sources = _DECIDABLE_SOURCE_STATUSES[payload.action]
    if meeting.status not in allowed_sources:
        await db.rollback()
        return _fail(
            409,
            "MEETING_CONFLICT",
            "현재 상태에서는 처리할 수 없는 작업입니다.",
            request_id=x_request_id,
        )

    previous_status = meeting.status

    if payload.action == "REJECT":
        await _release_all_held_slots(db, meeting)
        meeting.status = "rejected"
    else:
        assert payload.slot_id is not None, (
            "schema validator guarantees slot_id for ACCEPT/COUNTER_PROPOSE"
        )
        held_stmt = select(MeetingSlotRequest).where(
            MeetingSlotRequest.meeting_id == meeting.meeting_id,
            MeetingSlotRequest.availability_slot_id == payload.slot_id,
        )
        held_slot_request = (await db.execute(held_stmt)).scalar_one_or_none()
        if held_slot_request is not None and held_slot_request.status == "SELECTED":
            slot = await db.get(AvailabilitySlot, payload.slot_id)
        else:
            slot = await _reserve_slot(
                db, slot_id=payload.slot_id, participation_id=staff.participation_id
            )
            if slot is None:
                await db.rollback()
                return _fail(
                    409,
                    "MEETING_CONFLICT",
                    "선택한 시간에 여유가 없습니다.",
                    retryable=True,
                    request_id=x_request_id,
                )
            if held_slot_request is None:
                next_order_stmt = select(
                    func.coalesce(func.max(MeetingSlotRequest.preference_order), 0)
                ).where(MeetingSlotRequest.meeting_id == meeting.meeting_id)
                next_order = (await db.execute(next_order_stmt)).scalar_one() + 1
                held_slot_request = MeetingSlotRequest(
                    meeting_slot_request_id=uuid.uuid4(),
                    meeting_id=meeting.meeting_id,
                    availability_slot_id=payload.slot_id,
                    preference_order=next_order,
                    status="PENDING",
                )
                db.add(held_slot_request)

        # 이번에 확정/제안하는 슬롯 외에 이전에 점유해 둔 다른 후보는 반환한다.
        other_selected_stmt = select(MeetingSlotRequest).where(
            MeetingSlotRequest.meeting_id == meeting.meeting_id,
            MeetingSlotRequest.status == "SELECTED",
            MeetingSlotRequest.availability_slot_id != payload.slot_id,
        )
        for other in (await db.execute(other_selected_stmt)).scalars().all():
            await _release_slot(db, slot_id=other.availability_slot_id)
            other.status = "DECLINED"
        held_slot_request.status = "SELECTED"

        if payload.action == "ACCEPT":
            meeting.status = "accepted"
            meeting.staff_id = staff.staff_id
            meeting.confirmed_slot_id = slot.availability_slot_id
            meeting.confirmed_start = slot.start_at
            meeting.confirmed_end = slot.end_at
            if payload.enable_contact_sharing:
                # 연락처 공개의 세 번째 게이트. 바이어가 애초에 동의하지 않았다면
                # (contact_share 행 자체가 없다면) 업체가 켜기를 요청해도 만들어주지
                # 않는다 - 바이어 동의는 업체가 대신 만들 수 없다.
                existing_share = (
                    await db.execute(
                        select(MeetingContactShare).where(
                            MeetingContactShare.meeting_id == meeting.meeting_id
                        )
                    )
                ).scalar_one_or_none()
                enable_exhibitor_contact_sharing(existing_share, staff=staff)
        else:
            meeting.status = "counter_proposed"

    meeting.row_version += 1
    db.add(
        MeetingStatusHistory(
            meeting_status_history_id=uuid.uuid4(),
            meeting_id=meeting.meeting_id,
            previous_status=previous_status,
            new_status=meeting.status,
            changed_by_user_id=staff.user_id,
            reason_code=payload.reason_code,
        )
    )

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return _fail(
            409,
            "MEETING_CONFLICT",
            "겹치는 확정 상담이 있어 처리할 수 없습니다.",
            request_id=x_request_id,
        )

    data = await _build_meeting_response(db, meeting)
    response = _ok(data, request_id=x_request_id)
    _idempotency_store(idempotency_key, subject, path, body_dict, response)
    return response


# --------------------------------------------------------------------------
# 15절 참가업체 포털 - E-04 상담결과·후속조치
# --------------------------------------------------------------------------

_OUTCOME_ALLOWED_SOURCE_STATUSES = ("accepted", "completed")


@router.post("/partner/meetings/{meeting_id}/outcome")
async def record_meeting_outcome(
    meeting_id: uuid.UUID,
    payload: MeetingOutcomeRequest,
    db: AsyncSession = Depends(get_db),
    staff_id: uuid.UUID | None = Depends(_staff_header),
    x_request_id: Annotated[str | None, Header(alias="X-Request-ID")] = None,
) -> JSONResponse:
    staff = await _load_active_staff(db, staff_id)
    if staff is None:
        return _fail(
            401,
            "AUTH_REQUIRED",
            "파트너 계정 인증이 필요합니다.",
            request_id=x_request_id,
        )

    meeting = await db.get(MeetingRequest, meeting_id)
    if meeting is None or meeting.participation_id != staff.participation_id:
        return _fail(
            404,
            "RESOURCE_FORBIDDEN",
            "상담 요청을 찾을 수 없습니다.",
            request_id=x_request_id,
        )
    if meeting.status not in _OUTCOME_ALLOWED_SOURCE_STATUSES:
        return _fail(
            409,
            "MEETING_CONFLICT",
            "확정되었거나 완료된 상담에만 결과를 기록할 수 있습니다.",
            request_id=x_request_id,
        )

    outcome_resolved = _resolve_concept(
        payload.outcome_code, namespace_fallbacks=_OUTCOME_NAMESPACE_FALLBACKS
    )

    lead = (
        await db.execute(select(Lead).where(Lead.meeting_id == meeting.meeting_id))
    ).scalar_one_or_none()
    if lead is None:
        lead = Lead(meeting_outcome_id=uuid.uuid4(), meeting_id=meeting.meeting_id)
        db.add(lead)
    lead.is_qualified_lead = payload.is_qualified_lead
    if outcome_resolved is not None:
        lead.taxonomy_version_id, lead.concept_id, _resolved_outcome_code = (
            outcome_resolved
        )
    lead.expected_amount = payload.expected_amount
    lead.currency = payload.currency
    lead.expected_probability_percent = payload.expected_probability_percent
    lead.memo_enc = _encrypt_text(payload.memo, purpose="lead-memo")
    lead.completed_at = datetime.now(UTC)
    lead.recorded_by_user_id = staff.user_id

    follow_up_id: uuid.UUID | None = None
    if payload.follow_up is not None:
        follow_up_resolved = _resolve_concept(
            payload.follow_up.action_code,
            namespace_fallbacks=_FOLLOW_UP_NAMESPACE_FALLBACKS,
        )
        follow_up = FollowUp(
            follow_up_action_id=uuid.uuid4(),
            meeting_id=meeting.meeting_id,
            assignee_user_id=staff.user_id,
            due_date=payload.follow_up.due_date,
            status="PENDING",
            note_enc=_encrypt_text(payload.follow_up.note, purpose="follow-up-note"),
        )
        if follow_up_resolved is not None:
            (
                follow_up.taxonomy_version_id,
                follow_up.concept_id,
                _resolved_action_code,
            ) = follow_up_resolved
        db.add(follow_up)
        follow_up_id = follow_up.follow_up_action_id

    previous_status = meeting.status
    if meeting.status == "accepted":
        meeting.status = "completed"
        meeting.row_version += 1
        db.add(
            MeetingStatusHistory(
                meeting_status_history_id=uuid.uuid4(),
                meeting_id=meeting.meeting_id,
                previous_status=previous_status,
                new_status="completed",
                changed_by_user_id=staff.user_id,
                reason_code="OUTCOME_RECORDED",
            )
        )

    await db.commit()

    data = MeetingOutcomeResponse(
        meeting_id=meeting.meeting_id,
        meeting_outcome_id=lead.meeting_outcome_id,
        meeting_status=meeting.status,
        is_qualified_lead=lead.is_qualified_lead,
        follow_up_action_id=follow_up_id,
    )
    return _ok(data, request_id=x_request_id)
