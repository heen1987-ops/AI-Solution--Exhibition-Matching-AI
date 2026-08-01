"""Profile Resolver: 프로파일·버전·바이어 요구조건을 하나의 조회 단위로 통합한다.

근거 문서: docs/05-ai-matching-engine-architecture.md 5.2절 Profile Resolver.
docs/11-13-scoring-implementation.md은 이 조회 계층을 "클로드가 작성 중인
backend/app/services/matching"의 책임으로 명시한다.

구현 범위
----------
UserProfile + 최신 ProfileVersion + (바이어인 경우) BuyerNeed + 활성 ProfileAttribute
목록을 함께 가져온다. 어떤 ProfileAttribute가 "제품군 요구조건"인지 같은 의미 해석은
하지 않는다 - concept_type을 알아야 하는 판단이라 ontology 조회 계층과 함께 다음 커밋에서
연결한다(feature_builder.py 모듈 docstring의 "구현 범위" 참고). 이 모듈은 있는 그대로의
활성 속성 행을 돌려주는 데까지만 책임진다.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.profile import BuyerNeed, ProfileAttribute, ProfileVersion, UserProfile


class ProfileNotFoundError(Exception):
    def __init__(self, profile_id: uuid.UUID) -> None:
        super().__init__(f"profile not found: {profile_id}")
        self.profile_id = profile_id


class ProfileVersionMissingError(Exception):
    """05단계 5.2절: 추천 생성은 반드시 profile_version_id를 참조해야 한다(07 22.5절
    스냅샷 원칙). 버전이 하나도 없는 프로파일로는 추천을 생성할 수 없다."""

    def __init__(self, profile_id: uuid.UUID) -> None:
        super().__init__(f"profile has no version snapshot yet: {profile_id}")
        self.profile_id = profile_id


@dataclass(frozen=True)
class ProfileResolution:
    profile: UserProfile
    latest_version: ProfileVersion
    buyer_need: BuyerNeed | None
    active_attributes: tuple[ProfileAttribute, ...]


async def resolve_profile(
    session: AsyncSession, profile_id: uuid.UUID
) -> ProfileResolution:
    profile = await session.get(UserProfile, profile_id)
    if profile is None or profile.deleted_at is not None:
        raise ProfileNotFoundError(profile_id)

    version_stmt = (
        select(ProfileVersion)
        .where(ProfileVersion.profile_id == profile_id)
        .order_by(ProfileVersion.version_number.desc())
        .limit(1)
    )
    latest_version = (await session.execute(version_stmt)).scalar_one_or_none()
    if latest_version is None:
        raise ProfileVersionMissingError(profile_id)

    buyer_need: BuyerNeed | None = None
    if profile.user_type == "BUYER":
        buyer_need = await session.get(BuyerNeed, profile_id)

    attributes_stmt = select(ProfileAttribute).where(
        ProfileAttribute.profile_id == profile_id,
        ProfileAttribute.active.is_(True),
    )
    active_attributes = tuple((await session.execute(attributes_stmt)).scalars().all())

    return ProfileResolution(
        profile=profile,
        latest_version=latest_version,
        buyer_need=buyer_need,
        active_attributes=active_attributes,
    )
