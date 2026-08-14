"""온보딩·프로파일 라우터: 프로파일 세션 생성/수정, 답변 제출, 조회, 속성 수정, 완성도 조회.

근거 문서 (Read로 정독, 충돌 시 우선순위: 인터페이스 명세 > db-erd > 07 문서)
--------------------------------------------------------------------------
- docs/frontend-backend-ai-interface-spec.md
    4절(API 공통 계약: 성공/오류 봉투, If-Match/ETag, X-Request-ID) - 응답 형태의 1차 근거.
    6절(화면·API 매핑) - "프론트는 /me 또는 현재 세션 경로만 쓰고, 서버가 인증 주체에 속한
    프로파일을 해석한다"는 원칙의 근거. 그래서 이 파일의 모든 라우트는 {profile_id} 경로
    파라미터를 받지 않고 /profiles/me/... 형태로 통일한다.
    7.3절(PATCH /profiles/me/user-type), 8.1절(PUT /profiles/me/goals),
    8.2절(PUT /profiles/me/consumer-preferences), 8.3절(PUT /profiles/me/buyer-needs),
    8.4절(PUT /visit-sessions/current/plan), 14절(PATCH /profiles/me, add/remove 시맨틱)
    - 요청/응답 필드명의 1차 근거.
- docs/07-user-profile-model.md
    17.1~17.3절(완성도 가중치·구간), 22.1~22.5절(DB 컬럼명), 26.1~26.4절(프로파일
    조회/속성수정/완성도/버전 조회 API - 다만 26절 각주가 "경로 표기는 인터페이스 명세
    우선"이라 명시하므로 여기서는 GET/PATCH /profiles/me/attributes, GET
    /profiles/me/completeness, GET /profiles/me/versions로 옮겨 구현한다), 27절(추천용
    프로파일 출력 형태 - GET /profiles/me 응답 형태 참고).
- docs/user-ia-wireframes.md 5.1절 - U-01(시작), U-02(유형), U-04~07(온보딩 질문 단계)
  라우트 표. "POST /profile-sessions", "POST /answers"라는 일반화된 이름을 쓰지만, 인터페이스
  명세가 각 단계별로 더 구체적인 PATCH/PUT 엔드포인트를 이미 정의하므로(우선순위 원칙) 그
  구체적 엔드포인트를 그대로 구현한다. "프로파일 세션 생성"은 이 파일에서 아래 헬퍼
  _get_or_create_profile로 구현한다(각 쓰기 엔드포인트가 최초 호출 시 프로파일을 멱등
  생성한다) - 자세한 이유는 그 함수의 docstring 참고.

라우트 등록 방식에 대한 메모 (중요)
------------------------------------
이 라우터는 /profiles/me/...와 /visit-sessions/current/plan 두 개의 서로 다른 최상위
리소스에 걸쳐 있다. 그래서 app/api/v1/endpoints/ontology.py처럼 "라우터 전체에 공통
prefix를 붙이는" 방식을 쓸 수 없다. 이 파일의 모든 경로는 이미 /api/v1 하위의 완전한
상대경로(예: "/profiles/me/goals")를 담고 있다. app/api/v1/api.py(이 작업 범위 밖, 다른
에이전트가 통합)에서 이 router를 추가할 때는 prefix 없이 등록해야 한다:

    from app.api.v1.routers import profile as profile_router
    api_router.include_router(profile_router.router, tags=["profile"])

온톨로지 코드값에 대한 메모
---------------------------
방문목적·주종·맛·채널·지역 등은 6단계 매칭 온톨로지 문서가 아직 없어 하드코딩 Enum으로
제한하지 않는다(작업 지시 원칙). 대신 src/meet_ai/ontology/catalog.v1.json(이미
app/api/v1/endpoints/ontology.py가 읽는 것과 동일한 카탈로그)로 코드 존재 여부를 검증하고,
그 카탈로그의 emit_postgres_seed가 실제 사용하는 규칙(stable_uuid("concept", code),
stable_uuid("taxonomy-version", catalog.version))으로 concept_id/taxonomy_version_id를
결정론적으로 계산해 profile.profile_attribute의 FK(ontology.concept/concept_revision)를
만족시킨다. 카탈로그가 아직 DB에 시드되지 않은 로컬 환경에서는 FK 위반으로 실패할 수
있는데, 그건 정상이다(시드 데이터가 없다는 뜻이므로) - 이 라우터가 먼저 카탈로그 자체에서
코드 존재를 검증해 최소한 "알 수 없는 코드"와 "시드 누락"을 구분되게 422로 알린다.

TODO(다중 taxonomy_version 지원): app/models/core.py의 Event.current_taxonomy_version_id는
행사별로 다른 온톨로지 버전을 고정할 수 있게 해 두었지만, 이 라우터는 아직 그 값을 조회하지
않고 항상 load_catalog()가 읽는 단일 카탈로그(현재 catalog.v1.json, taxonomy_version 1.0.0)를
쓴다. 여러 taxonomy_version이 동시에 운영되는 시점에는 subject.event_id로 Event를 조회해
그 event.current_taxonomy_version_id에 맞는 카탈로그를 선택하도록 확장해야 한다.

비온톨로지 스칼라 값(alcohol_percentage, price, purchase_intent 등)에 대한 메모
--------------------------------------------------------------------------------
backend/app/models/profile.py의 모듈 docstring이 명시하듯 profile.consumer_preference류
테이블은 이번 단계에서 의도적으로 제외되어 아직 없다. profile_attribute는 ontology FK가
필수라 비-코드성 숫자 범위값을 넣을 수 없다. 그래서 이런 스칼라 값은 profile_version의
snapshot_json(FK 없는 JSONB, "전체 스냅샷" 용도로 이미 설계됨)에 저장하고, 다음 스냅샷을
만들 때 이전 스냅샷의 consumer_preferences 섹션을 이어받아 병합한다(_bump_version 참고).
전용 컬럼이 생기면 그쪽으로 옮기는 것이 TODO다.

인증/세션 상태에 대한 메모
--------------------------
docs/frontend-backend-ai-interface-spec.md 7.1~7.2절(서명된 guest 쿠키 발급, 세션 쿠키
검증, 휴대전화 인증)은 별도 세션/인증 라우터의 책임이며 이 작업 범위 밖이다. get_current_subject
의 TODO 주석을 참고하라.
"""

from __future__ import annotations

import base64
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import VerifiedGuest, VerifiedPrincipal, get_verified_subject
from app.db.session import get_db
from app.models.matching import MatchRun
from app.models.profile import (
    BuyerNeed,
    ContextProfile,
    InferredPreference,
    ProfileAttribute,
    ProfileVersion,
    UserProfile,
    VisitSession,
)
from app.schemas.profile import (
    AddRemove,
    AttributePatchItem,
    AttributesPatchRequest,
    AttributesPatchResponse,
    AttributeView,
    BuyerNeedsRequest,
    BuyerNeedsResponse,
    BuyerNeedView,
    CompletenessResponse,
    ConsumerPreferencesRequest,
    ConsumerPreferencesResponse,
    Envelope,
    GoalsUpdateRequest,
    GoalsUpdateResponse,
    GoalView,
    Meta,
    ProfileGeneralPatchRequest,
    ProfileGeneralPatchResponse,
    ProfileVersionItem,
    ProfileVersionsResponse,
    ProfileView,
    SelectedGoalView,
    UserTypeUpdateRequest,
    UserTypeUpdateResponse,
    VisitPlanRequest,
    VisitPlanResponse,
)
from meet_ai.ontology import Catalog, load_catalog
from meet_ai.ontology.catalog import stable_uuid

router = APIRouter()


# ---------------------------------------------------------------------------
# 현재 주체(테넌트/행사/인증·익명 사용자) 해석
#
# consent.py도 이 CurrentSubject/get_current_subject/build_envelope/get_request_id/
# api_error를 그대로 재사용한다(두 라우터가 같은 작업에서 함께 만들어지는 온보딩 도메인이라
# 별도 공용 모듈을 새로 만들지 않고 여기서 가져다 쓴다).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CurrentSubject:
    tenant_id: uuid.UUID
    event_id: uuid.UUID
    user_id: uuid.UUID | None
    guest_session_id: uuid.UUID | None


def _parse_uuid(value: str | None, field: str) -> uuid.UUID | None:
    if value is None:
        return None
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise api_error(
            status.HTTP_400_BAD_REQUEST,
            "VALIDATION_FAILED",
            f"{field} 헤더 형식이 올바르지 않습니다.",
            field_errors=[{"field": field, "reason": "invalid_uuid"}],
        ) from exc


async def get_current_subject(
    verified: Annotated[
        VerifiedPrincipal | VerifiedGuest, Depends(get_verified_subject)
    ],
) -> CurrentSubject:
    """서버가 검증한 세션에서만 현재 주체와 tenant/event 경계를 파생한다."""

    if isinstance(verified, VerifiedPrincipal):
        event_id = verified.principal.event_id
        if event_id is None:
            raise api_error(
                status.HTTP_401_UNAUTHORIZED,
                "SESSION_EXPIRED",
                "행사 세션 컨텍스트가 없습니다.",
            )
        return CurrentSubject(
            tenant_id=verified.principal.tenant_id,
            event_id=event_id,
            user_id=verified.user_id,
            guest_session_id=None,
        )
    return CurrentSubject(
        tenant_id=verified.tenant_id,
        event_id=verified.event_id,
        user_id=None,
        guest_session_id=verified.guest_session_id,
    )


# ---------------------------------------------------------------------------
# 응답 봉투 / 오류 / 요청ID 공용 헬퍼 (인터페이스 명세 4.2~4.4절)
# ---------------------------------------------------------------------------


def get_request_id(
    x_request_id: str | None = Header(default=None, alias="X-Request-ID"),
) -> str:
    """"서버는 클라이언트 요청 ID를 검증하고, 누락 시 새 ID를 생성한다" (4.2절)."""

    return x_request_id or f"req_{uuid.uuid4().hex}"


def build_envelope(data: Any, request_id: str) -> dict[str, Any]:
    return {
        "success": True,
        "data": data,
        "meta": Meta(request_id=request_id, server_time=datetime.now(timezone.utc)),
    }


def api_error(
    status_code: int,
    code: str,
    message: str,
    *,
    field_errors: list[dict[str, str]] | None = None,
    retryable: bool = False,
    retry_after_seconds: int | None = None,
) -> HTTPException:
    """4.4절 오류 봉투와 같은 shape을 detail에 담는다 (모듈 docstring의 Envelope 참고).

    main.py에 전역 예외 핸들러가 아직 없어(이 작업 범위 밖) FastAPI 기본 처리대로
    {"detail": {...}} 형태로 나가지만, detail 내부 shape 자체는 이미 4.4절과 동일하다.
    """

    return HTTPException(
        status_code=status_code,
        detail={
            "code": code,
            "message": message,
            "field_errors": field_errors or [],
            "retryable": retryable,
            "retry_after_seconds": retry_after_seconds,
        },
    )


# ---------------------------------------------------------------------------
# 온톨로지 코드 검증/해석
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _catalog() -> Catalog:
    return load_catalog()


def _concept_type_of(code: str) -> str | None:
    concept = _catalog().by_code.get(code)
    return concept.get("concept_type") if concept else None


def _resolve_concept(code: str) -> tuple[uuid.UUID, uuid.UUID]:
    catalog = _catalog()
    try:
        catalog.get(code)
    except KeyError as exc:
        raise api_error(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "VALIDATION_FAILED",
            f"알 수 없는 온톨로지 코드입니다: {code}",
            field_errors=[{"field": code, "reason": "unknown_ontology_code"}],
        ) from exc
    concept_id = stable_uuid("concept", code)
    taxonomy_version_id = stable_uuid("taxonomy-version", catalog.version)
    return concept_id, taxonomy_version_id


# ---------------------------------------------------------------------------
# 프로파일 조회/생성
# ---------------------------------------------------------------------------


async def _find_profile(db: AsyncSession, subject: CurrentSubject) -> UserProfile | None:
    stmt = select(UserProfile).where(
        UserProfile.tenant_id == subject.tenant_id,
        UserProfile.event_id == subject.event_id,
        UserProfile.deleted_at.is_(None),
    )
    if subject.user_id is not None:
        stmt = stmt.where(UserProfile.user_id == subject.user_id)
    else:
        stmt = stmt.where(UserProfile.guest_session_id == subject.guest_session_id)
    stmt = stmt.order_by(UserProfile.created_at.desc())
    result = await db.execute(stmt)
    return result.scalars().first()


async def _get_or_create_profile(db: AsyncSession, subject: CurrentSubject) -> UserProfile:
    """현재 주체의 프로파일을 찾거나, 없으면 만든다("프로파일 세션 생성").

    정식 흐름에서는 인터페이스 명세 7.1절 POST /sessions(익명 세션 생성, 이 작업 범위 밖)가
    guest_session_id/visit_session_id와 함께 profile_id를 먼저 발급한다. 이 라우터는 그
    라우터가 아직 없어도 온보딩 흐름 전체를 독립적으로 검증할 수 있도록, 최초 프로파일
    관련 요청이 들어오면 없던 프로파일을 즉시 만든다(멱등 - 이미 있으면 그 행을 재사용).
    """

    profile = await _find_profile(db, subject)
    if profile is not None:
        return profile

    profile = UserProfile(
        tenant_id=subject.tenant_id,
        event_id=subject.event_id,
        user_id=subject.user_id,
        guest_session_id=subject.guest_session_id,
        user_type="GENERAL_VISITOR",
        profile_status="DRAFT",
        completeness_score=0,
        current_version=1,
        row_version=1,
    )
    db.add(profile)
    await db.flush()

    db.add(
        ProfileVersion(
            profile_id=profile.profile_id,
            version_number=1,
            snapshot_json={},
            change_reason="PROFILE_CREATED",
        )
    )
    await db.flush()
    return profile


# ---------------------------------------------------------------------------
# 동시성 제어 (If-Match / ETag)
# ---------------------------------------------------------------------------

_IF_MATCH_PATTERN = re.compile(r'^"?profile-v(\d+)"?$')


def _check_if_match(if_match: str | None, row_version: int) -> None:
    if if_match is None:
        return
    match = _IF_MATCH_PATTERN.match(if_match.strip())
    if not match:
        raise api_error(
            status.HTTP_400_BAD_REQUEST,
            "VALIDATION_FAILED",
            'If-Match 헤더 형식이 올바르지 않습니다 (예: "profile-v4").',
        )
    if int(match.group(1)) != row_version:
        raise api_error(
            status.HTTP_409_CONFLICT,
            "PROFILE_VERSION_CONFLICT",
            "프로파일이 이미 다른 요청으로 변경되었습니다. 최신 값을 다시 조회해 주세요.",
            retryable=True,
        )


def _etag(row_version: int) -> str:
    return f'"profile-v{row_version}"'


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# 버전 스냅샷 (profile.profile_version)
# ---------------------------------------------------------------------------


def _buyer_need_to_dict(buyer_need: BuyerNeed) -> dict[str, Any]:
    return {
        "organization_type": buyer_need.organization_type,
        "target_price_min_amount": buyer_need.target_price_min_amount,
        "target_price_max_amount": buyer_need.target_price_max_amount,
        "currency": buyer_need.currency,
        "price_basis": buyer_need.price_basis,
        "monthly_units_min": buyer_need.monthly_units_min,
        "monthly_units_max": buyer_need.monthly_units_max,
        "decision_timeline": buyer_need.decision_timeline,
        "business_email_verified": buyer_need.business_email_verified,
        "company_verified": buyer_need.company_verified,
    }


async def _latest_snapshot(db: AsyncSession, profile: UserProfile) -> dict[str, Any]:
    stmt = (
        select(ProfileVersion)
        .where(ProfileVersion.profile_id == profile.profile_id)
        .order_by(ProfileVersion.version_number.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    latest = result.scalars().first()
    return dict(latest.snapshot_json or {}) if latest is not None else {}


async def _bump_version(
    db: AsyncSession,
    profile: UserProfile,
    change_reason: str,
    consumer_preferences_patch: dict[str, Any] | None = None,
) -> ProfileVersion:
    """프로파일 버전을 올리고 전체 스냅샷을 남긴다 (07 22.5절, 4.4절 "추천 세션 스냅샷").

    consumer_preferences 섹션은 비-온톨로지 스칼라 값의 유일한 영속 저장소이므로(모듈
    docstring 참고), 매번 이전 스냅샷 값을 이어받은 뒤 이번 요청에서 바뀐 부분만 덮어쓴다.
    """

    previous = await _latest_snapshot(db, profile)
    consumer_preferences = dict(previous.get("consumer_preferences") or {})
    if consumer_preferences_patch is not None:
        consumer_preferences.update(consumer_preferences_patch)

    attrs_result = await db.execute(
        select(ProfileAttribute).where(
            ProfileAttribute.profile_id == profile.profile_id,
            ProfileAttribute.active.is_(True),
        )
    )
    attributes = [
        {
            "attribute_code": row.attribute_code,
            "value_json": row.value_json,
            "requirement_level": row.requirement_level,
            "priority": row.priority,
            "source_type": row.source_type,
        }
        for row in attrs_result.scalars().all()
    ]

    buyer_need = await db.get(BuyerNeed, profile.profile_id)

    snapshot = {
        "user_type": profile.user_type,
        "profile_status": profile.profile_status,
        "primary_goal_code": profile.primary_goal_code,
        "attributes": attributes,
        "buyer_need": _buyer_need_to_dict(buyer_need) if buyer_need is not None else None,
        "consumer_preferences": consumer_preferences,
    }

    profile.current_version += 1
    profile.row_version += 1

    version = ProfileVersion(
        profile_id=profile.profile_id,
        version_number=profile.current_version,
        snapshot_json=snapshot,
        change_reason=change_reason,
    )
    db.add(version)
    await db.flush()
    return version


async def _invalidate_active_recommendations(
    db: AsyncSession, profile: UserProfile
) -> list[uuid.UUID]:
    """9.2절 "recommendation_session"의 활성 세션을 무효화한다 (matching.recommendation_session).

    matching 도메인은 이 작업 범위 밖이지만, MatchRun(=matching.recommendation_session)
    모델이 이미 존재하므로 상태 갱신 정도는 실제로 수행한다 - 새 추천을 만드는 로직 자체는
    추천 오케스트레이터(다른 단계)의 책임이다.
    """

    stmt = select(MatchRun).where(
        MatchRun.profile_id == profile.profile_id, MatchRun.status == "ACTIVE"
    )
    result = await db.execute(stmt)
    sessions = result.scalars().all()
    for session in sessions:
        session.status = "INVALIDATED"
    if sessions:
        await db.flush()
    return [session.recommendation_session_id for session in sessions]


# ---------------------------------------------------------------------------
# 방문 세션 (완성도 계산·방문 계획에 사용)
# ---------------------------------------------------------------------------


async def _find_visit_session(
    db: AsyncSession, profile: UserProfile
) -> VisitSession | None:
    stmt = select(VisitSession).where(
        VisitSession.tenant_id == profile.tenant_id,
        VisitSession.event_id == profile.event_id,
    )
    if profile.user_id is not None:
        stmt = stmt.where(VisitSession.user_id == profile.user_id)
    else:
        stmt = stmt.where(VisitSession.guest_session_id == profile.guest_session_id)
    stmt = stmt.order_by(VisitSession.created_at.desc()).limit(1)
    result = await db.execute(stmt)
    return result.scalars().first()


# ---------------------------------------------------------------------------
# 범용 속성 그룹 조작 (concept_type 단위로 PUT=전체교체 / PATCH=add·remove)
# ---------------------------------------------------------------------------


async def _replace_attribute_group(
    db: AsyncSession,
    profile: UserProfile,
    group_concept_types: set[str],
    codes: list[str],
    *,
    requirement_level: str,
    source_type: str,
    priority_map: dict[str, int] | None = None,
) -> None:
    """group_concept_types에 속하는 기존 활성 속성을 모두 비활성화하고 codes로 새로 채운다.

    PUT 엔드포인트(방문목적/취향/바이어조건)는 "이번에 제출한 값이 곧 전체 상태"라는
    전체교체 시맨틱이므로, codes가 비어 있으면 해당 그룹을 선택 해제한 것으로 본다.
    """

    priority_map = priority_map or {}

    existing_result = await db.execute(
        select(ProfileAttribute).where(
            ProfileAttribute.profile_id == profile.profile_id,
            ProfileAttribute.active.is_(True),
        )
    )
    for row in existing_result.scalars().all():
        if _concept_type_of(row.attribute_code) in group_concept_types:
            row.active = False

    for code in codes:
        concept_id, taxonomy_version_id = _resolve_concept(code)
        db.add(
            ProfileAttribute(
                profile_id=profile.profile_id,
                taxonomy_version_id=taxonomy_version_id,
                concept_id=concept_id,
                attribute_code=code,
                value_json={"selected": True},
                requirement_level=requirement_level,
                priority=priority_map.get(code),
                source_type=source_type,
                confidence=1,
                active=True,
            )
        )
    await db.flush()


async def _apply_add_remove(
    db: AsyncSession,
    profile: UserProfile,
    add_remove: AddRemove,
    *,
    requirement_level: str,
    source_type: str,
) -> None:
    """14절 "{"add": [...], "remove": [...]}" 시맨틱."""

    if add_remove.remove:
        result = await db.execute(
            select(ProfileAttribute).where(
                ProfileAttribute.profile_id == profile.profile_id,
                ProfileAttribute.active.is_(True),
                ProfileAttribute.attribute_code.in_(add_remove.remove),
            )
        )
        for row in result.scalars().all():
            row.active = False

    if add_remove.add:
        active_result = await db.execute(
            select(ProfileAttribute.attribute_code).where(
                ProfileAttribute.profile_id == profile.profile_id,
                ProfileAttribute.active.is_(True),
                ProfileAttribute.attribute_code.in_(add_remove.add),
            )
        )
        already_active = {row[0] for row in active_result.all()}
        for code in add_remove.add:
            if code in already_active:
                continue
            concept_id, taxonomy_version_id = _resolve_concept(code)
            db.add(
                ProfileAttribute(
                    profile_id=profile.profile_id,
                    taxonomy_version_id=taxonomy_version_id,
                    concept_id=concept_id,
                    attribute_code=code,
                    value_json={"selected": True},
                    requirement_level=requirement_level,
                    source_type=source_type,
                    confidence=1,
                    active=True,
                )
            )

    if add_remove.add or add_remove.remove:
        await db.flush()


# ---------------------------------------------------------------------------
# 완성도 계산 (07 17.1~17.3절)
# ---------------------------------------------------------------------------


def _weighted_score(weight: float, checks: list[bool]) -> float:
    if not checks:
        return 0.0
    fraction = sum(1 for check in checks if check) / len(checks)
    return round(weight * fraction, 2)


def _completeness_band(score: float) -> str:
    if score >= 80:
        return "PRECISE"
    if score >= 50:
        return "GENERAL"
    if score >= 30:
        return "EXPLORATORY"
    return "NEEDS_MORE_INFO"


async def _active_attribute_concept_types(
    db: AsyncSession, profile: UserProfile
) -> set[str]:
    result = await db.execute(
        select(ProfileAttribute.attribute_code).where(
            ProfileAttribute.profile_id == profile.profile_id,
            ProfileAttribute.active.is_(True),
        )
    )
    types: set[str] = set()
    for (code,) in result.all():
        concept_type = _concept_type_of(code)
        if concept_type:
            types.add(concept_type)
    return types


async def _compute_completeness(
    db: AsyncSession, profile: UserProfile
) -> tuple[float, dict[str, float]]:
    """07 17.1(일반 관람객)/17.2(바이어) 가중치를 기준으로 완성도를 산출한다.

    TODO(6단계 온톨로지·매칭 설계 확정 후 재조정): 07 문서는 카테고리별 총 배점만 정의하고
    카테고리 내부 세부조건 배점은 정의하지 않는다. 여기서는 카테고리 내부를 균등분배하는
    합리적 기본값을 쓴다(_weighted_score).
    """

    active_types = await _active_attribute_concept_types(db, profile)
    snapshot = await _latest_snapshot(db, profile)
    consumer_prefs = snapshot.get("consumer_preferences") or {}
    visit_session = await _find_visit_session(db, profile)

    inferred_count = await db.execute(
        select(func.count()).select_from(InferredPreference).where(
            InferredPreference.profile_id == profile.profile_id
        )
    )
    has_inferred = (inferred_count.scalar_one() or 0) > 0

    behavior_attr_count = await db.execute(
        select(func.count())
        .select_from(ProfileAttribute)
        .where(
            ProfileAttribute.profile_id == profile.profile_id,
            ProfileAttribute.active.is_(True),
            ProfileAttribute.source_type.in_(
                ["FEEDBACK", "BEHAVIOR_SINGLE", "BEHAVIOR_AGGREGATED"]
            ),
        )
    )
    has_behavior_attr = (behavior_attr_count.scalar_one() or 0) > 0

    breakdown: dict[str, float] = {}

    if profile.user_type == "BUYER":
        buyer_need = await db.get(BuyerNeed, profile.profile_id)
        breakdown["조직·채널"] = _weighted_score(
            15,
            [
                bool(buyer_need and buyer_need.organization_type),
                "CHANNEL" in active_types,
            ],
        )
        breakdown["희망 제품군"] = 20.0 if "PRODUCT_CATEGORY" in active_types else 0.0
        breakdown["가격·MOQ"] = _weighted_score(
            20,
            [
                bool(
                    buyer_need
                    and (
                        buyer_need.target_price_min_amount is not None
                        or buyer_need.target_price_max_amount is not None
                    )
                ),
                bool(
                    buyer_need
                    and (
                        buyer_need.monthly_units_min is not None
                        or buyer_need.monthly_units_max is not None
                    )
                ),
            ],
        )
        breakdown["공급지역"] = 15.0 if "REGION" in active_types else 0.0
        breakdown["거래유형"] = _weighted_score(
            15,
            ["TRADE_TYPE" in active_types, bool(buyer_need and buyer_need.decision_timeline)],
        )
        breakdown["상담주제·시점"] = _weighted_score(
            10,
            [
                "MEETING_TOPIC" in active_types,
                bool(buyer_need and buyer_need.decision_timeline),
            ],
        )
        breakdown["검증상태"] = (
            5.0
            if buyer_need
            and (buyer_need.business_email_verified or buyer_need.company_verified)
            else 0.0
        )
    else:
        breakdown["방문목적"] = (
            25.0 if ("VISIT_GOAL" in active_types or "BUSINESS_GOAL" in active_types) else 0.0
        )
        breakdown["관심 주종"] = 20.0 if "PRODUCT_CATEGORY" in active_types else 0.0
        breakdown["맛·도수 선호"] = _weighted_score(
            15,
            [
                "TASTE" in active_types or "AROMA" in active_types,
                bool(consumer_prefs.get("alcohol_percentage")),
            ],
        )
        breakdown["가격·구매조건"] = _weighted_score(
            15,
            [bool(consumer_prefs.get("price")), bool(consumer_prefs.get("purchase_intent"))],
        )
        breakdown["체류시간·이동조건"] = _weighted_score(
            15,
            [
                bool(visit_session and visit_session.available_minutes is not None),
                bool(visit_session and visit_session.route_preference),
            ],
        )
        breakdown["피드백·행동정보"] = 10.0 if (has_inferred or has_behavior_attr) else 0.0

    total = round(sum(breakdown.values()), 2)
    profile.completeness_score = total
    return total, breakdown


# ---------------------------------------------------------------------------
# 커서 페이지네이션 (버전 목록)
# ---------------------------------------------------------------------------


def _encode_version_cursor(version_number: int) -> str:
    return base64.urlsafe_b64encode(str(version_number).encode()).decode()


def _decode_version_cursor(cursor: str) -> int:
    try:
        return int(base64.urlsafe_b64decode(cursor.encode()).decode())
    except (ValueError, UnicodeDecodeError) as exc:
        raise api_error(
            status.HTTP_400_BAD_REQUEST, "VALIDATION_FAILED", "cursor 형식이 올바르지 않습니다."
        ) from exc


# ===========================================================================
# 엔드포인트
# ===========================================================================


@router.patch("/profiles/me/user-type", response_model=Envelope[UserTypeUpdateResponse])
async def update_user_type(
    payload: UserTypeUpdateRequest,
    subject: CurrentSubject = Depends(get_current_subject),
    if_match: str | None = Header(default=None, alias="If-Match"),
    request_id: str = Depends(get_request_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """7.3절: 사용자 유형 전환. 완성도 가중치 표가 달라지므로 재계산하고, 유형이 실제로
    바뀌면 활성 추천 세션을 무효화한다."""

    profile = await _get_or_create_profile(db, subject)
    _check_if_match(if_match, profile.row_version)

    changed = profile.user_type != payload.user_type
    profile.user_type = payload.user_type

    await _bump_version(
        db, profile, "USER_TYPE_CHANGED" if changed else "USER_TYPE_REAFFIRMED"
    )
    await _compute_completeness(db, profile)

    invalidated: list[uuid.UUID] = []
    if changed:
        invalidated = await _invalidate_active_recommendations(db, profile)

    await db.commit()

    data = UserTypeUpdateResponse(
        profile_version=profile.current_version,
        user_type=profile.user_type,
        recommendation_refresh_required=changed,
        invalidated_recommendation_session_ids=invalidated,
    )
    return build_envelope(data, request_id)


@router.put("/profiles/me/goals", response_model=Envelope[GoalsUpdateResponse])
async def update_goals(
    payload: GoalsUpdateRequest,
    subject: CurrentSubject = Depends(get_current_subject),
    if_match: str | None = Header(default=None, alias="If-Match"),
    request_id: str = Depends(get_request_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """8.1절: 방문 목적. 사용자의 명시적 선택만 저장한다."""

    profile = await _get_or_create_profile(db, subject)
    _check_if_match(if_match, profile.row_version)

    priority_map = {item.code: item.priority for item in payload.visit_goals}
    codes = list(priority_map.keys())

    await _replace_attribute_group(
        db,
        profile,
        {"VISIT_GOAL", "BUSINESS_GOAL"},
        codes,
        requirement_level="PREFERRED",
        source_type="USER_SELECTED",
        priority_map=priority_map,
    )

    profile.primary_goal_code = (
        min(payload.visit_goals, key=lambda item: item.priority).code if codes else None
    )

    consumer_patch = (
        {"free_text_goal": payload.free_text_goal}
        if payload.free_text_goal is not None
        else None
    )
    await _bump_version(db, profile, "GOALS_UPDATED", consumer_preferences_patch=consumer_patch)
    await _compute_completeness(db, profile)
    await db.commit()

    data = GoalsUpdateResponse(
        profile_version=profile.current_version,
        selected_goals=[
            SelectedGoalView(
                attribute_code=item.code, priority=item.priority, requirement_level="PREFERRED"
            )
            for item in payload.visit_goals
        ],
        # TODO(AI 내부 인터페이스, 인터페이스 명세 17.1절): free_text_goal을
        # POST /internal/ai/ontology/extract 경계로 보내는 연동은 이 작업 범위 밖이라
        # 아직 연결하지 않았다. 사용자 명시 선택 저장은 완전히 동작한다.
        suggested_attributes=[],
        confirmation_required=False,
    )
    return build_envelope(data, request_id)


@router.put(
    "/profiles/me/consumer-preferences", response_model=Envelope[ConsumerPreferencesResponse]
)
async def update_consumer_preferences(
    payload: ConsumerPreferencesRequest,
    subject: CurrentSubject = Depends(get_current_subject),
    if_match: str | None = Header(default=None, alias="If-Match"),
    request_id: str = Depends(get_request_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """8.2절: 관람객 취향."""

    profile = await _get_or_create_profile(db, subject)
    _check_if_match(if_match, profile.row_version)

    await _replace_attribute_group(
        db,
        profile,
        {"PRODUCT_CATEGORY"},
        payload.product_categories,
        requirement_level="PREFERRED",
        source_type="USER_SELECTED",
    )
    await _replace_attribute_group(
        db,
        profile,
        {"TASTE", "AROMA"},
        payload.taste_preferences,
        requirement_level="PREFERRED",
        source_type="USER_SELECTED",
    )
    await _replace_attribute_group(
        db,
        profile,
        {"USE_CASE", "BOOTH_SERVICE"},
        payload.preferred_activities,
        requirement_level="PREFERRED",
        source_type="USER_SELECTED",
    )

    consumer_patch = {
        "alcohol_percentage": (
            payload.alcohol_percentage.model_dump() if payload.alcohol_percentage else None
        ),
        "price": payload.price.model_dump() if payload.price else None,
        "purchase_intent": payload.purchase_intent,
        "preference_certainty": payload.preference_certainty,
    }
    await _bump_version(
        db, profile, "CONSUMER_PREFERENCES_UPDATED", consumer_preferences_patch=consumer_patch
    )
    score, _breakdown = await _compute_completeness(db, profile)
    await db.commit()

    data = ConsumerPreferencesResponse(profile_version=profile.current_version, completeness_score=score)
    return build_envelope(data, request_id)


@router.put("/profiles/me/buyer-needs", response_model=Envelope[BuyerNeedsResponse])
async def update_buyer_needs(
    payload: BuyerNeedsRequest,
    subject: CurrentSubject = Depends(get_current_subject),
    if_match: str | None = Header(default=None, alias="If-Match"),
    request_id: str = Depends(get_request_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """8.3절: 바이어 조건. 숫자형 필드는 profile.buyer_need 전용 컬럼에, 코드형 필드는
    profile_attribute에 저장한다."""

    profile = await _get_or_create_profile(db, subject)
    _check_if_match(if_match, profile.row_version)

    buyer_need = await db.get(BuyerNeed, profile.profile_id)
    if buyer_need is None:
        buyer_need = BuyerNeed(profile_id=profile.profile_id)
        db.add(buyer_need)

    buyer_need.organization_type = payload.organization_type
    if payload.target_price is not None:
        buyer_need.target_price_min_amount = payload.target_price.min_amount
        buyer_need.target_price_max_amount = payload.target_price.max_amount
        buyer_need.price_basis = payload.target_price.basis
        buyer_need.currency = payload.target_price.currency
    else:
        buyer_need.target_price_min_amount = None
        buyer_need.target_price_max_amount = None
        buyer_need.price_basis = None
    if payload.expected_order_volume is not None:
        buyer_need.monthly_units_min = payload.expected_order_volume.monthly_units_min
        buyer_need.monthly_units_max = payload.expected_order_volume.monthly_units_max
    else:
        buyer_need.monthly_units_min = None
        buyer_need.monthly_units_max = None
    buyer_need.decision_timeline = payload.decision_timeline

    # desired_categories는 관람객 취향의 product_categories와 같은 concept_type(PRODUCT_CATEGORY)
    # 그룹을 공유한다 - 실제로 "관심 있는 주종"이라는 동일 개념을 사용자 유형별로 다른 질문
    # 문구로 물어보는 것뿐이라 의도적으로 공유한다.
    await _replace_attribute_group(
        db,
        profile,
        {"CHANNEL"},
        payload.distribution_channels,
        requirement_level="PREFERRED",
        source_type="USER_SELECTED",
    )
    await _replace_attribute_group(
        db,
        profile,
        {"PRODUCT_CATEGORY"},
        payload.desired_categories,
        requirement_level="REQUIRED",
        source_type="USER_SELECTED",
    )
    await _replace_attribute_group(
        db,
        profile,
        {"REGION"},
        payload.supply_regions,
        requirement_level="PREFERRED",
        source_type="USER_SELECTED",
    )
    await _replace_attribute_group(
        db,
        profile,
        {"TRADE_TYPE"},
        payload.business_interests,
        requirement_level="PREFERRED",
        source_type="USER_SELECTED",
    )

    await db.flush()
    await _bump_version(db, profile, "BUYER_NEEDS_UPDATED")
    score, _breakdown = await _compute_completeness(db, profile)
    await db.commit()

    data = BuyerNeedsResponse(profile_version=profile.current_version, completeness_score=score)
    return build_envelope(data, request_id)


@router.put("/visit-sessions/current/plan", response_model=Envelope[VisitPlanResponse])
async def update_visit_plan(
    payload: VisitPlanRequest,
    subject: CurrentSubject = Depends(get_current_subject),
    request_id: str = Depends(get_request_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """8.4절: 방문 계획. profile.visit_session(체류시간 등)과 profile.context_profile
    (이동조건·상담 가능 슬롯 등 부가 상황)에 나눠 저장한다."""

    profile = await _get_or_create_profile(db, subject)

    visit_session = await _find_visit_session(db, profile)
    if visit_session is None:
        visit_session = VisitSession(
            tenant_id=subject.tenant_id,
            event_id=subject.event_id,
            user_id=subject.user_id,
            guest_session_id=subject.guest_session_id,
            profile_id=profile.profile_id,
            visit_date=payload.visit_date,
            session_status="PLANNED",
        )
        db.add(visit_session)
    elif visit_session.profile_id is None:
        visit_session.profile_id = profile.profile_id

    visit_session.visit_date = payload.visit_date
    if payload.entry_time is not None:
        visit_session.entry_at = _to_utc(payload.entry_time)
    visit_session.available_minutes = payload.available_minutes
    visit_session.route_preference = payload.route_preference
    await db.flush()

    next_schedule_at = (
        _to_utc(min(slot.start for slot in payload.meeting_available_slots))
        if payload.meeting_available_slots
        else None
    )

    context = ContextProfile(
        visit_session_id=visit_session.visit_session_id,
        remaining_minutes=payload.available_minutes,
        avoid_congestion=(payload.route_preference == "LOW_CONGESTION"),
        next_schedule_at=next_schedule_at,
        context_json={
            "walking_constraints": (
                payload.walking_constraints.model_dump()
                if payload.walking_constraints is not None
                else None
            ),
            "meeting_available_slots": [
                {"start": slot.start.isoformat(), "end": slot.end.isoformat()}
                for slot in payload.meeting_available_slots
            ],
        },
    )
    db.add(context)

    await _bump_version(db, profile, "VISIT_PLAN_UPDATED")
    await _compute_completeness(db, profile)
    await db.commit()

    data = VisitPlanResponse(
        visit_session_id=visit_session.visit_session_id,
        visit_date=visit_session.visit_date,
        available_minutes=visit_session.available_minutes,
        route_preference=visit_session.route_preference,
        context_profile_id=context.context_profile_id,
    )
    return build_envelope(data, request_id)


@router.patch("/profiles/me", response_model=Envelope[ProfileGeneralPatchResponse])
async def patch_profile(
    payload: ProfileGeneralPatchRequest,
    subject: CurrentSubject = Depends(get_current_subject),
    if_match: str | None = Header(default=None, alias="If-Match"),
    request_id: str = Depends(get_request_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """14절: 조건 수정 (U-20). add/remove 시맨틱으로 기존 값 위에 증분 적용한다."""

    profile = await _get_or_create_profile(db, subject)
    _check_if_match(if_match, profile.row_version)

    add_remove_fields = (
        payload.taste_preferences,
        payload.product_categories,
        payload.preferred_activities,
        payload.distribution_channels,
        payload.desired_categories,
        payload.business_interests,
        payload.supply_regions,
    )
    for add_remove in add_remove_fields:
        if add_remove is not None:
            await _apply_add_remove(
                db, profile, add_remove, requirement_level="PREFERRED", source_type="USER_EDITED"
            )

    consumer_patch: dict[str, Any] = {}
    if payload.price is not None:
        consumer_patch["price"] = payload.price.model_dump()
    if payload.alcohol_percentage is not None:
        consumer_patch["alcohol_percentage"] = payload.alcohol_percentage.model_dump()

    await _bump_version(
        db, profile, "USER_UPDATE", consumer_preferences_patch=consumer_patch or None
    )
    await _compute_completeness(db, profile)
    invalidated = await _invalidate_active_recommendations(db, profile)
    await db.commit()

    data = ProfileGeneralPatchResponse(
        profile_version=profile.current_version,
        recommendation_refresh_required=True,
        invalidated_recommendation_session_ids=invalidated,
    )
    return build_envelope(data, request_id)


@router.patch("/profiles/me/attributes", response_model=Envelope[AttributesPatchResponse])
async def patch_attributes(
    payload: AttributesPatchRequest,
    subject: CurrentSubject = Depends(get_current_subject),
    if_match: str | None = Header(default=None, alias="If-Match"),
    request_id: str = Depends(get_request_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """07 26.2절: 범용 온톨로지 속성 upsert/remove (특정 화면 전용이 아닌 저수준 API)."""

    profile = await _get_or_create_profile(db, subject)
    _check_if_match(if_match, profile.row_version)

    touched_codes = [item.attribute_code for item in payload.attributes]
    existing_result = await db.execute(
        select(ProfileAttribute).where(
            ProfileAttribute.profile_id == profile.profile_id,
            ProfileAttribute.active.is_(True),
            ProfileAttribute.attribute_code.in_(touched_codes),
        )
    )
    existing_by_code = {row.attribute_code: row for row in existing_result.scalars().all()}

    changed_rows: list[ProfileAttribute] = []
    item: AttributePatchItem
    for item in payload.attributes:
        existing = existing_by_code.get(item.attribute_code)
        if item.action == "REMOVE":
            if existing is not None:
                existing.active = False
                changed_rows.append(existing)
            continue

        if existing is not None:
            existing.value_json = item.value
            existing.requirement_level = item.requirement_level
            existing.priority = item.priority
            existing.source_type = "USER_EDITED"
            changed_rows.append(existing)
        else:
            concept_id, taxonomy_version_id = _resolve_concept(item.attribute_code)
            new_row = ProfileAttribute(
                profile_id=profile.profile_id,
                taxonomy_version_id=taxonomy_version_id,
                concept_id=concept_id,
                attribute_code=item.attribute_code,
                value_json=item.value,
                requirement_level=item.requirement_level,
                priority=item.priority,
                source_type="USER_EDITED",
                confidence=1,
                active=True,
            )
            db.add(new_row)
            changed_rows.append(new_row)

    await db.flush()
    await _bump_version(db, profile, "ATTRIBUTES_PATCHED")
    await _compute_completeness(db, profile)
    await db.commit()

    data = AttributesPatchResponse(
        profile_version=profile.current_version,
        attributes=[
            AttributeView(
                profile_attribute_id=row.profile_attribute_id,
                attribute_code=row.attribute_code,
                value_json=row.value_json,
                requirement_level=row.requirement_level,
                priority=row.priority,
                source_type=row.source_type,
                confidence=float(row.confidence),
                active=row.active,
            )
            for row in changed_rows
        ],
    )
    return build_envelope(data, request_id)


@router.get("/profiles/me", response_model=Envelope[ProfileView])
async def get_my_profile(
    response: Response,
    subject: CurrentSubject = Depends(get_current_subject),
    request_id: str = Depends(get_request_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """07 26.1절 + 27절 형태 참고: 현재 주체의 프로파일 조회."""

    profile = await _get_or_create_profile(db, subject)

    attrs_result = await db.execute(
        select(ProfileAttribute)
        .where(
            ProfileAttribute.profile_id == profile.profile_id,
            ProfileAttribute.active.is_(True),
        )
        .order_by(ProfileAttribute.created_at)
    )
    attribute_rows = attrs_result.scalars().all()

    goal_types = {"VISIT_GOAL", "BUSINESS_GOAL"}
    goals = [
        GoalView(
            attribute_code=row.attribute_code,
            priority=row.priority,
            requirement_level=row.requirement_level,
            confidence=float(row.confidence),
        )
        for row in attribute_rows
        if _concept_type_of(row.attribute_code) in goal_types
    ]
    attributes = [
        AttributeView(
            profile_attribute_id=row.profile_attribute_id,
            attribute_code=row.attribute_code,
            value_json=row.value_json,
            requirement_level=row.requirement_level,
            priority=row.priority,
            source_type=row.source_type,
            confidence=float(row.confidence),
            active=row.active,
        )
        for row in attribute_rows
    ]

    buyer_need = await db.get(BuyerNeed, profile.profile_id)
    buyer_need_view = (
        BuyerNeedView(
            organization_type=buyer_need.organization_type,
            target_price_min_amount=buyer_need.target_price_min_amount,
            target_price_max_amount=buyer_need.target_price_max_amount,
            currency=buyer_need.currency,
            price_basis=buyer_need.price_basis,
            monthly_units_min=buyer_need.monthly_units_min,
            monthly_units_max=buyer_need.monthly_units_max,
            decision_timeline=buyer_need.decision_timeline,
            business_email_verified=buyer_need.business_email_verified,
            company_verified=buyer_need.company_verified,
        )
        if buyer_need is not None
        else None
    )

    snapshot = await _latest_snapshot(db, profile)
    await db.commit()

    response.headers["ETag"] = _etag(profile.row_version)

    data = ProfileView(
        profile_id=profile.profile_id,
        user_type=profile.user_type,
        profile_status=profile.profile_status,
        completeness_score=float(profile.completeness_score),
        current_version=profile.current_version,
        goals=goals,
        attributes=attributes,
        consumer_preferences=snapshot.get("consumer_preferences") or {},
        buyer_need=buyer_need_view,
        updated_at=profile.updated_at,
    )
    return build_envelope(data, request_id)


@router.get("/profiles/me/completeness", response_model=Envelope[CompletenessResponse])
async def get_completeness(
    response: Response,
    subject: CurrentSubject = Depends(get_current_subject),
    request_id: str = Depends(get_request_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """07 26.3절 + 17.3절 구간 매핑."""

    profile = await _get_or_create_profile(db, subject)
    score, breakdown = await _compute_completeness(db, profile)
    await db.commit()

    response.headers["ETag"] = _etag(profile.row_version)

    data = CompletenessResponse(
        profile_id=profile.profile_id,
        completeness_score=score,
        band=_completeness_band(score),
        breakdown=breakdown,
    )
    return build_envelope(data, request_id)


@router.get("/profiles/me/versions", response_model=Envelope[ProfileVersionsResponse])
async def list_versions(
    subject: CurrentSubject = Depends(get_current_subject),
    request_id: str = Depends(get_request_id),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """07 26.4절: 프로파일 변경 이력. 불투명 커서 페이지네이션(인터페이스 명세 4.1절)."""

    profile = await _get_or_create_profile(db, subject)
    await db.commit()

    stmt = (
        select(ProfileVersion)
        .where(ProfileVersion.profile_id == profile.profile_id)
        .order_by(ProfileVersion.version_number.desc())
    )
    if cursor:
        stmt = stmt.where(ProfileVersion.version_number < _decode_version_cursor(cursor))
    stmt = stmt.limit(limit + 1)

    result = await db.execute(stmt)
    rows = result.scalars().all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = _encode_version_cursor(rows[-1].version_number) if has_more and rows else None

    data = ProfileVersionsResponse(
        items=[
            ProfileVersionItem(
                profile_version_id=row.profile_version_id,
                version_number=row.version_number,
                change_reason=row.change_reason,
                created_at=row.created_at,
            )
            for row in rows
        ],
        next_cursor=next_cursor,
    )
    return build_envelope(data, request_id)
