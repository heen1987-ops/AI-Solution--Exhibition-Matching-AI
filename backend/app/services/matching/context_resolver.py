"""Context Resolver: 방문 세션의 최신 상황 스냅샷을 추천용 컨텍스트로 만든다.

근거 문서: docs/05-ai-matching-engine-architecture.md 5.3절 Context Resolver.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.profile import ContextProfile, VisitSession


@dataclass(frozen=True)
class ContextResolution:
    visit_session: VisitSession | None
    latest_context: ContextProfile | None

    def to_snapshot(self) -> dict[str, Any]:
        """matching.recommendation_session.context_snapshot에 그대로 저장할 dict.

        05단계 5.3절 출력 예시(current_zone/remaining_minutes/...)와 같은 모양을 따르되,
        방문세션·상황 스냅샷이 아직 없는(비회원 최초 방문 등) 경우도 유효한 상태로 다룬다 -
        9단계 상세설계는 정보 부족을 넓은 상위 카테고리 검색으로 대응하라고 하지, 요청을
        거부하라고 하지 않는다.
        """

        if self.latest_context is None:
            return {
                "current_zone_id": None,
                "remaining_minutes": None,
                "avoid_congestion": False,
                "captured_at": None,
            }
        return {
            "current_zone_id": (
                str(self.latest_context.current_zone_id)
                if self.latest_context.current_zone_id
                else None
            ),
            "remaining_minutes": self.latest_context.remaining_minutes,
            "max_walk_minutes": self.latest_context.max_walk_minutes,
            "avoid_congestion": self.latest_context.avoid_congestion,
            "next_schedule_at": (
                self.latest_context.next_schedule_at.isoformat()
                if self.latest_context.next_schedule_at
                else None
            ),
            "captured_at": self.latest_context.captured_at.isoformat(),
        }


async def resolve_context(
    session: AsyncSession, visit_session_id: uuid.UUID | None
) -> ContextResolution:
    if visit_session_id is None:
        return ContextResolution(visit_session=None, latest_context=None)

    visit_session = await session.get(VisitSession, visit_session_id)

    context_stmt = (
        select(ContextProfile)
        .where(ContextProfile.visit_session_id == visit_session_id)
        .order_by(ContextProfile.captured_at.desc())
        .limit(1)
    )
    latest_context = (await session.execute(context_stmt)).scalar_one_or_none()

    return ContextResolution(visit_session=visit_session, latest_context=latest_context)
