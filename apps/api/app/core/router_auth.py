"""라우터 공용 인증/인가 어댑터.

목적
----
WAVE 2C/2D/2E에서 병렬로 작성된 라우터들은 각자 ``X-Actor-User-Id`` / ``X-Profile-Id`` /
``X-Staff-Id`` 헤더를 그대로 신뢰하는 사설 식별자 헬퍼를 복사해서 들고 있었다. 통합
저장소에서는 그런 헬퍼가 하나도 남아 있으면 안 된다 - 호출자가 보내는 헤더는 절대
행위자 식별에 쓰지 않고, 검증된 서버 세션 또는 서비스 JWT에서 파생한 principal만 쓴다.

이 모듈은 그 단일 진입점이다.

- :func:`get_actor_user_id` - ``app/api/v1/routers/partner.py``가 이미 수행한 재배선
  (검증된 principal에서 ``user_id`` 파생)을 그대로 옮긴 것. 모든 라우터는
  ``Depends(get_actor_user_id)``만 쓴다.
- :func:`require_exhibitor_access` / :func:`require_operator_access` - 인가(authorization)
  규칙. 네 개 라우터에 거의 동일하게 복제돼 있던 ``_require_exhibitor_access``를 하나로
  모았다. 규칙 자체는 바꾸지 않는다: legacy ``identity.user_role`` / ``identity.role``
  테이블을 그대로 조회한다(main의 partner.py가 하는 것과 동일).
- :func:`get_buyer_profile_id` / :func:`get_staff_id` - ``routers/meetings.py``가 이미
  principal에서 파생하도록 재배선한 헬퍼의 정본. meetings.py는 이제 이 두 함수를
  ``_buyer_profile_header`` / ``_staff_header`` 이름으로 re-export만 한다(기존 참조와
  dependency_overrides 호환을 위해 동일 객체를 가리킨다).
- :func:`get_exhibitor_current_event_id` - MERGE STEP 26이 승인(approve)→색인 배선에 쓰는
  읽기 전용 헬퍼. ``app/services/extraction/review.py``는 자신의 모듈 docstring이 못박은
  하드 경계("``app.models.exhibitor``의 어떤 테이블도 import조차 하지 않는다" -
  ``tests/test_extraction_api.py::test_no_router_path_ever_touches_business_tables``가
  정적으로 강제) 때문에 ``ExhibitorParticipation``을 직접 조회할 수 없다. 그 경계를 지키는
  라우터(``app/api/v1/routers/extraction.py``)가 대신 이 함수로 event_id를 미리 구해
  ``review_service.approve_extraction(..., event_id=...)``에 값으로 넘긴다.

인가 의미는 이 단계에서 하나도 바꾸지 않는다(통합 계획 STEP 14).
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import VerifiedPrincipal, get_verified_principal
from app.db.session import get_db
from app.models.exhibitor import ExhibitorParticipation, ExhibitorStaff
from app.models.identity import Role, UserRole
from app.models.profile import UserProfile

__all__ = [
    "get_actor_user_id",
    "get_buyer_profile_id",
    "get_exhibitor_current_event_id",
    "get_staff_id",
    "require_exhibitor_access",
    "require_operator_access",
]


async def get_actor_user_id(
    principal: VerifiedPrincipal = Depends(get_verified_principal),
) -> UUID:
    """검증된 세션/JWT principal에서만 행위자를 파생한다."""

    return principal.user_id


async def require_exhibitor_access(
    db: AsyncSession, *, actor_user_id: UUID, exhibitor_id: UUID
) -> None:
    """actor_user_id가 이 exhibitor_id 소속 EXHIBITOR 역할이거나 OPERATOR/ADMIN인지 검사한다.

    db-erd-table-spec.md 8.2절 "EXHIBITOR 역할은 exhibitor_id 필수"를 이용해, 다른 업체
    소속 담당자가 남의 업체 리소스를 고치지 못하게 막는다(인터페이스 명세 23절 "다른
    업체의 ... 리소스를 조회할 수 없다").
    """

    stmt = (
        select(UserRole.user_role_id)
        .join(Role, Role.role_id == UserRole.role_id)
        .where(
            UserRole.user_id == actor_user_id,
            UserRole.valid_until.is_(None),
            or_(
                and_(Role.role_code == "EXHIBITOR", UserRole.exhibitor_id == exhibitor_id),
                Role.role_code.in_(("OPERATOR", "ADMIN")),
            ),
        )
        .limit(1)
    )
    allowed = (await db.execute(stmt)).scalar_one_or_none()
    if allowed is None:
        raise HTTPException(status_code=403, detail="RESOURCE_FORBIDDEN")


async def require_operator_access(db: AsyncSession, *, actor_user_id: UUID) -> None:
    """운영자 전용 엔드포인트 - OPERATOR/ADMIN 역할만 통과."""

    stmt = (
        select(UserRole.user_role_id)
        .join(Role, Role.role_id == UserRole.role_id)
        .where(
            UserRole.user_id == actor_user_id,
            UserRole.valid_until.is_(None),
            Role.role_code.in_(("OPERATOR", "ADMIN")),
        )
        .limit(1)
    )
    allowed = (await db.execute(stmt)).scalar_one_or_none()
    if allowed is None:
        raise HTTPException(status_code=403, detail="RESOURCE_FORBIDDEN")


async def get_buyer_profile_id(
    principal: Annotated[VerifiedPrincipal, Depends(get_verified_principal)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> UUID | None:
    """검증된 사용자의 현재 행사 프로파일을 파생한다."""

    if principal.principal.event_id is None:
        return None
    return await db.scalar(
        select(UserProfile.profile_id)
        .where(
            UserProfile.user_id == principal.user_id,
            UserProfile.tenant_id == principal.principal.tenant_id,
            UserProfile.event_id == principal.principal.event_id,
            UserProfile.deleted_at.is_(None),
        )
        .order_by(UserProfile.user_type.desc())
        .limit(1)
    )


async def get_staff_id(
    principal: Annotated[VerifiedPrincipal, Depends(get_verified_principal)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> UUID | None:
    """검증된 사용자의 현재 행사 활성 담당자를 파생한다."""

    if principal.principal.event_id is None:
        return None
    return await db.scalar(
        select(ExhibitorStaff.staff_id)
        .join(
            ExhibitorParticipation,
            ExhibitorParticipation.participation_id == ExhibitorStaff.participation_id,
        )
        .where(
            ExhibitorStaff.user_id == principal.user_id,
            ExhibitorStaff.active.is_(True),
            ExhibitorParticipation.tenant_id == principal.principal.tenant_id,
            ExhibitorParticipation.event_id == principal.principal.event_id,
        )
        .limit(1)
    )


async def get_exhibitor_current_event_id(
    db: AsyncSession, *, tenant_id: UUID, exhibitor_id: UUID
) -> UUID | None:
    """이 업체의 "현재" 참가 행사 event_id를 읽기 전용으로 구한다.

    한 업체가 여러 행사에 참가할 수 있어 참가(participation) 자체는 1:N이지만
    (``exhibitor_participation``에는 event_id당 유니크 제약만 있다), 취소되지 않은
    참가 중 가장 최근에 갱신된 한 건을 "현재" 참가로 취급한다 - 같은 모호성을 이미
    ``app/services/exhibitor_preference/service.py::_common_trade_condition_stmt``가
    ``ORDER BY updated_at DESC LIMIT 1``로 푸는 것과 동일한 관례다.
    """

    result = await db.execute(
        select(ExhibitorParticipation.event_id)
        .where(
            ExhibitorParticipation.tenant_id == tenant_id,
            ExhibitorParticipation.exhibitor_id == exhibitor_id,
            ExhibitorParticipation.participation_status != "CANCELLED",
        )
        .order_by(ExhibitorParticipation.updated_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()
