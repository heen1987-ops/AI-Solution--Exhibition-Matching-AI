"""① Request Validator - docs/05-ai-matching-engine-architecture.md 5.1절.

추천 요청의 유효성을 검증한다. 검증 항목(5.1절 그대로):
    - 행사 운영 여부
    - 사용자 세션 유효 여부 (SubjectContext 해석은 라우터 책임 - 여기서는 프로파일 존재만 확인)
    - 연령확인 여부
    - 개인화 추천 동의 여부
    - 사용자 유형 설정 여부
    - 프로파일 최소 완성도
    - 추천 유형 유효 여부
    - 위치·시간 데이터 형식
    - 요청량 제한

실패 시 app.services.matching.errors.RecommendationError를 던진다. 라우터가 이를
docs/frontend-backend-ai-interface-spec.md 4.4절 오류 봉투로 변환한다.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.consent import ConsentPolicy, UserConsent
from app.models.core import Event
from app.models.profile import UserProfile
from app.services.matching import errors
from app.services.matching.types import (
    RECOMMENDATION_TYPES,
    USER_TYPES,
    SubjectContext,
    ValidatedRequest,
)

#: 05번 문서에 정확한 값이 없어 합리적 기본값으로 둔다.
#: TODO(정책 확정 후 교체): 운영자가 설정 가능한 정책 값으로 옮긴다.
DEFAULT_LIMIT = 10
MAX_LIMIT = 50
MIN_COMPLETENESS_FOR_PERSONALIZATION = 20.0

#: 08/07 문서 모두 "예시"로만 목적 코드를 제공한다 (consent.py 모듈 docstring 참고).
_PURPOSE_AGE_CONFIRMATION = "AGE_CONFIRMATION"
_PURPOSE_PERSONALIZED_RECOMMENDATION = "PERSONALIZED_RECOMMENDATION"


async def _latest_consent_accepted(
    db: AsyncSession, subject: SubjectContext, profile: UserProfile, purpose: str
) -> bool:
    """지정한 purpose에 대한 가장 최근 동의 선택이 accepted=True인지 확인한다.

    profile.user_consent는 append-only이므로(consent.py docstring: "과거 행을 update하여
    철회를 덮어쓰지 않는다") occurred_at 내림차순 최신 한 건만 본다.
    """

    stmt = (
        select(UserConsent.accepted)
        .join(
            ConsentPolicy,
            UserConsent.consent_policy_id == ConsentPolicy.consent_policy_id,
        )
        .where(
            ConsentPolicy.purpose == purpose,
            UserConsent.tenant_id == subject.tenant_id,
        )
        .order_by(UserConsent.occurred_at.desc())
        .limit(1)
    )
    if profile.user_id is not None:
        stmt = stmt.where(UserConsent.user_id == profile.user_id)
    else:
        stmt = stmt.where(UserConsent.guest_session_id == profile.guest_session_id)
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    return bool(row)


def _validate_context_shape(
    context_input: dict[str, Any],
) -> list[errors.FieldErrorDetail]:
    field_errors: list[errors.FieldErrorDetail] = []
    remaining_minutes = context_input.get("remaining_minutes")
    if remaining_minutes is not None and (
        not isinstance(remaining_minutes, int)
        or isinstance(remaining_minutes, bool)
        or remaining_minutes < 0
    ):
        field_errors.append(
            errors.FieldErrorDetail(
                "context.remaining_minutes", "must be a non-negative integer"
            )
        )
    current_zone = context_input.get("current_zone")
    if current_zone is not None and not isinstance(current_zone, str):
        field_errors.append(
            errors.FieldErrorDetail("context.current_zone", "must be a string")
        )
    for flag_name in ("exclude_visited", "include_meetings"):
        value = context_input.get(flag_name)
        if value is not None and not isinstance(value, bool):
            field_errors.append(
                errors.FieldErrorDetail(f"context.{flag_name}", "must be a boolean")
            )
    return field_errors


async def validate_request(
    db: AsyncSession,
    *,
    subject: SubjectContext,
    recommendation_type: str,
    context_input: dict[str, Any] | None,
    limit: int | None,
) -> ValidatedRequest:
    context_input = dict(context_input or {})
    field_errors: list[errors.FieldErrorDetail] = []

    # --- 추천 유형 유효 여부 ---
    if recommendation_type not in RECOMMENDATION_TYPES:
        field_errors.append(
            errors.FieldErrorDetail(
                "recommendation_type",
                f"must be one of {', '.join(RECOMMENDATION_TYPES)}",
            )
        )

    # --- 요청량 제한 ---
    resolved_limit = DEFAULT_LIMIT if limit is None else limit
    if (
        not isinstance(resolved_limit, int)
        or isinstance(resolved_limit, bool)
        or resolved_limit < 1
    ):
        field_errors.append(
            errors.FieldErrorDetail("limit", "must be a positive integer")
        )
        resolved_limit = DEFAULT_LIMIT
    resolved_limit = min(resolved_limit, MAX_LIMIT)

    # --- 위치·시간 데이터 형식 ---
    field_errors.extend(_validate_context_shape(context_input))

    if field_errors:
        raise errors.validation_failed(
            "요청 형식이 올바르지 않습니다.", field_errors=field_errors
        )

    # --- 행사 운영 여부 ---
    event_row = await db.get(Event, subject.event_id)
    if event_row is None or event_row.tenant_id != subject.tenant_id:
        raise errors.validation_failed("존재하지 않는 행사입니다.")
    if event_row.event_status != "OPEN":
        raise errors.service_temporarily_unavailable(
            "행사가 아직 시작되지 않았거나 종료되어 개인화 추천을 제공할 수 없습니다."
        )

    # --- 사용자 세션 유효 여부 / 사용자 유형 설정 여부 / 프로파일 최소 완성도 ---
    profile_stmt = select(UserProfile).where(
        UserProfile.profile_id == subject.profile_id,
        UserProfile.tenant_id == subject.tenant_id,
        UserProfile.event_id == subject.event_id,
        UserProfile.deleted_at.is_(None),
    )
    profile = (await db.execute(profile_stmt)).scalar_one_or_none()
    if profile is None:
        raise errors.profile_incomplete(
            "추천을 생성하려면 먼저 프로파일이 필요합니다.",
            field_errors=[errors.FieldErrorDetail("profile_id", "not_found")],
        )
    if subject.user_id is not None and profile.user_id != subject.user_id:
        raise errors.resource_forbidden(
            "인증 사용자와 프로파일 소유자가 일치하지 않습니다."
        )
    if (
        subject.guest_session_id is not None
        and profile.guest_session_id != subject.guest_session_id
    ):
        raise errors.resource_forbidden(
            "익명 세션과 프로파일 소유자가 일치하지 않습니다."
        )
    if profile.user_type not in USER_TYPES:
        raise errors.profile_incomplete(
            "사용자 유형을 먼저 선택해 주세요.",
            field_errors=[errors.FieldErrorDetail("user_type", "required")],
        )

    # --- 연령확인 여부 ---
    # TODO(비주류 카테고리 세분화): 지금은 이 서비스 전체가 주류 박람회 도메인이라 모든
    # 추천 유형에 연령확인을 요구한다. 향후 비주류 전용 부스/프로그램이 늘어나면
    # recommendation_type·카테고리별로 조건부 적용해야 한다.
    if not await _latest_consent_accepted(
        db, subject, profile, _PURPOSE_AGE_CONFIRMATION
    ):
        raise errors.age_confirmation_required()

    # --- 개인화 추천 동의 여부 ---
    if not await _latest_consent_accepted(
        db, subject, profile, _PURPOSE_PERSONALIZED_RECOMMENDATION
    ):
        raise errors.personalization_disabled()

    missing_fields: list[str] = []
    exploration_mode = False
    if float(profile.completeness_score) < MIN_COMPLETENESS_FOR_PERSONALIZATION:
        # 05번 문서 10.4절 "프로파일 정보 부족": 하드 차단하지 않고 탐색 추천으로 대체한다.
        missing_fields = ["goals", "preferences"]
        exploration_mode = True

    policy_route = f"{profile.user_type}_MATCHING_V1"

    return ValidatedRequest(
        subject=subject,
        request_valid=True,
        user_type=profile.user_type,
        recommendation_type=recommendation_type,
        limit=resolved_limit,
        context_input=context_input,
        missing_fields=missing_fields,
        policy_route=policy_route,
        exploration_mode=exploration_mode,
    )
