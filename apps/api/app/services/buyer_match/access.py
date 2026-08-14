"""바이어 자격(VERIFIED/LIMITED) 판정과 매칭 세션 소유권 검사.

VERIFIED/LIMITED 등급 산정 근거
---------------------------------
이 트랙이 처음 작성될 때는 저장소에 바이어 인증 단계를 나타내는 전용 컬럼이 없어
(``profile.user_profile.profile_status``는 DRAFT/COMPLETE/INACTIVE만 정의한다),
``profile.buyer_need``의 두 boolean 컬럼(``business_email_verified``,
``company_verified``)으로부터 등급을 추론하는 임시 휴리스틱을 썼다.

이후 병렬로 실행된 WAVE2C BACKEND-BUYER-PROFILE 트랙이 정식 인증 워크플로우를 가진
``profile.buyer_profile``(``app/models/buyer_profile.py``, 클래스 ``BuyerProfile``)을
게시했다 - ``verification_status``가 정확히 이 트랙이 필요로 하는 두 등급을 포함한
7단계 상태값(UNVERIFIED/PENDING/VERIFIED/LIMITED/REJECTED/SUSPENDED/EXPIRED)이고,
``MEETING_ELIGIBLE_VERIFICATION_STATUSES = {VERIFIED, LIMITED}``가 이 트랙의 "VERIFIED
(전체)/LIMITED(정책상 제한) 버이어만 호출 가능" 요구사항과 정확히 일치한다. 그래서 이
모듈은 이제 그 테이블을 1차 소스로 사용한다:

  - ``profile.buyer_profile`` 행이 있고 verification_status가 VERIFIED/LIMITED ->
    그 값을 그대로 등급으로 쓴다.
  - 그 행이 있지만 UNVERIFIED/PENDING/REJECTED/SUSPENDED/EXPIRED -> 거부(403).
  - 그 행이 아직 없음(바이어가 durable 인증 워크플로우에 아직 진입하지 않음) ->
    ``profile.buyer_need`` 휴리스틱으로 최대 LIMITED까지만 허용한다(과거 동작과 동일,
    VERIFIED로는 절대 승격하지 않는다 - 정식 인증은 운영자만 부여할 수 있으므로).

되돌리기 쉬움: 이 함수 하나만 교체하면 된다(순수 조회 로직, 다른 모듈은 BuyerContext만
소비한다).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.buyer_profile import (
    MEETING_ELIGIBLE_VERIFICATION_STATUSES,
    BuyerProfile,
)
from app.models.profile import BuyerNeed, UserProfile

VERIFIED = "VERIFIED"
LIMITED = "LIMITED"


class BuyerAccessDenied(Exception):
    """접근제어 실패. 라우터가 이 예외를 HTTP 403으로 변환한다."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class BuyerContext:
    profile_id: uuid.UUID
    tenant_id: uuid.UUID
    event_id: uuid.UUID
    profile_version: int
    verification_tier: str  # VERIFIED | LIMITED


async def resolve_buyer_context(db: AsyncSession, profile_id: uuid.UUID) -> BuyerContext:
    """프로파일을 로드하고 BUYER 여부·활성 여부·자격 등급을 판정한다.

    실패 시 항상 ``BuyerAccessDenied``를 던진다 - 존재하지 않는 프로파일과 권한 없는
    프로파일을 구분해서 노출하지 않는다(app/api/v1/routers/recommendations.py의 "존재
    여부를 노출하지 않기 위해 404 대신 403으로 통일한다" 관례를 그대로 따른다).
    """

    row = (
        await db.execute(
            select(UserProfile, BuyerNeed)
            .outerjoin(BuyerNeed, BuyerNeed.profile_id == UserProfile.profile_id)
            .where(
                UserProfile.profile_id == profile_id,
                UserProfile.deleted_at.is_(None),
            )
        )
    ).first()
    if row is None:
        raise BuyerAccessDenied(
            "BUYER_PROFILE_NOT_FOUND", "바이어 프로파일을 찾을 수 없습니다."
        )
    profile, buyer_need = row
    if profile.user_type != "BUYER":
        raise BuyerAccessDenied(
            "NOT_A_BUYER_PROFILE",
            "바이어 매칭 API는 user_type=BUYER 프로파일만 사용할 수 있습니다.",
        )
    if profile.profile_status == "INACTIVE":
        raise BuyerAccessDenied(
            "BUYER_PROFILE_INACTIVE", "비활성화된 프로파일은 매칭을 요청할 수 없습니다."
        )

    durable_profile: BuyerProfile | None = None
    if profile.user_id is not None:
        durable_profile = (
            await db.execute(
                select(BuyerProfile).where(
                    BuyerProfile.tenant_id == profile.tenant_id,
                    BuyerProfile.user_id == profile.user_id,
                )
            )
        ).scalar_one_or_none()

    if durable_profile is not None:
        # 정식 인증 워크플로우(app/models/buyer_profile.py)가 1차 소스다 - 모듈 docstring 참고.
        if durable_profile.verification_status not in MEETING_ELIGIBLE_VERIFICATION_STATUSES:
            raise BuyerAccessDenied(
                "BUYER_NOT_VERIFIED",
                "바이어 인증이 완료되지 않아 매칭 결과를 이용할 수 없습니다"
                f" (verification_status={durable_profile.verification_status}).",
            )
        tier = durable_profile.verification_status
    else:
        # durable 인증 레코드가 아직 없는 바이어 - BuyerNeed 자가신고 여부와 무관하게 최대
        # LIMITED까지만 허용한다(VERIFIED는 운영자만 부여할 수 있으므로 이 경로로는 절대
        # 승격하지 않는다). buyer_need는 이후 스코어링(orchestrator._resolve_criteria)에서
        # 별도로 재조회해 사용하므로, 여기서는 등급 판정에만 관여하지 않는다는 사실만 남긴다.
        del buyer_need
        tier = LIMITED

    return BuyerContext(
        profile_id=profile.profile_id,
        tenant_id=profile.tenant_id,
        event_id=profile.event_id,
        profile_version=profile.current_version,
        verification_tier=tier,
    )
