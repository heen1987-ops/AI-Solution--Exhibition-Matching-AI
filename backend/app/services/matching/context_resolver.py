"""③ Context Resolver - docs/05-ai-matching-engine-architecture.md 5.3절.

사용자의 현재 상황(현재 시간, 남은 체류시간, 현재 구역, 이미 방문한 부스, 확정된 상담일정)과
행사 운영상태를 결합한다. 부스 실시간 상태(운영상태·혼잡도·재고)는 이 단계가 아니라 05번
문서 8.3절 "준실시간 처리" 대상이므로 Candidate Generator/Hard Filter/Context Re-ranker가
그때그때 booth/event_product 테이블에서 최신 값을 직접 읽는다 - Context Resolver는 "이
사용자에게 어떤 방문·상담 이력이 있는가"만 담당한다.

``current_time``은 인터페이스 명세 9.1절 규칙대로 항상 서버 시각(``subject.server_time``)을
쓴다. 클라이언트가 보낸 값은 진단 목적으로만 허용되고 여기서는 아예 참조하지 않는다.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import ColumnElement, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.core import EventZone
from app.models.matching import InteractionEvent, Recommendable
from app.models.profile import VisitSession
from app.services.matching.types import (
    ResolvedContext,
    ResolvedProfile,
    SubjectContext,
    ValidatedRequest,
)

#: 05번 문서 5.3절 "이미 방문한 부스" 판단에 쓰는 표준 이벤트명
#: (인터페이스 명세 16.2절 표준 이름 목록에 포함된 실제 이벤트 코드).
_VISITED_EVENT_TYPE = "BOOTH_CHECKED_IN"
_EXCLUDED_EVENT_TYPE = "RECOMMENDATION_DISMISSED"
_CONFIRMED_MEETING_STATUS = "accepted"


async def _meeting_overlay_available(db: AsyncSession) -> bool:
    """Return whether the optional meeting module is installed for this site."""

    return bool(
        (
            await db.execute(
                text("SELECT to_regclass('interaction.meeting') IS NOT NULL")
            )
        ).scalar_one()
    )


def _owner_clause(
    column_user, column_guest, column_visit_session, subject: SubjectContext
) -> ColumnElement[bool]:
    """행동 이벤트 소유자 필터. interaction.interaction_event는 user_id/guest_session_id 중
    최대 하나만 채워지므로(모델 CHECK 제약) 주체 식별자 우선순위대로 하나만 사용한다.
    """

    if subject.user_id is not None:
        return column_user == subject.user_id
    if subject.guest_session_id is not None:
        return column_guest == subject.guest_session_id
    return column_visit_session == subject.visit_session_id


async def resolve_explicit_exclusions(
    db: AsyncSession, *, subject: SubjectContext
) -> set[uuid.UUID]:
    """Resolve the site's interaction overlay before entering the pure filter core."""

    rows = await db.execute(
        select(InteractionEvent.recommendable_id).where(
            InteractionEvent.tenant_id == subject.tenant_id,
            InteractionEvent.event_id == subject.event_id,
            InteractionEvent.event_type == _EXCLUDED_EVENT_TYPE,
            InteractionEvent.recommendable_id.is_not(None),
            _owner_clause(
                InteractionEvent.user_id,
                InteractionEvent.guest_session_id,
                InteractionEvent.visit_session_id,
                subject,
            ),
        )
    )
    return {row.recommendable_id for row in rows}


async def resolve_context(
    db: AsyncSession,
    *,
    subject: SubjectContext,
    validated: ValidatedRequest,
    profile: ResolvedProfile,
) -> ResolvedContext:
    context_input = validated.context_input
    server_time = subject.server_time

    visit_session: VisitSession | None = None
    if subject.visit_session_id is not None:
        visit_session = await db.get(VisitSession, subject.visit_session_id)
        if visit_session is not None and (
            visit_session.tenant_id != subject.tenant_id
            or visit_session.event_id != subject.event_id
            or visit_session.profile_id != subject.profile_id
        ):
            visit_session = None
    if visit_session is None:
        visit_session = (
            await db.execute(
                select(VisitSession)
                .where(
                    VisitSession.tenant_id == subject.tenant_id,
                    VisitSession.event_id == subject.event_id,
                    VisitSession.profile_id == subject.profile_id,
                )
                .order_by(VisitSession.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    current_zone: str | None = context_input.get("current_zone")
    current_zone_id: uuid.UUID | None = None
    if current_zone:
        current_zone_id = (
            await db.execute(
                select(EventZone.event_zone_id).where(
                    EventZone.tenant_id == subject.tenant_id,
                    EventZone.event_id == subject.event_id,
                    EventZone.zone_code == current_zone,
                )
            )
        ).scalar_one_or_none()
    elif visit_session is not None and visit_session.current_zone_id is not None:
        current_zone_id = visit_session.current_zone_id
        current_zone = (
            await db.execute(
                select(EventZone.zone_code).where(
                    EventZone.event_zone_id == current_zone_id
                )
            )
        ).scalar_one_or_none()

    remaining_minutes = context_input.get("remaining_minutes")
    if remaining_minutes is None and visit_session is not None:
        remaining_minutes = visit_session.available_minutes
    if remaining_minutes is None:
        remaining_minutes = profile.raw_context.get("remaining_minutes")

    exclude_visited = bool(context_input.get("exclude_visited", True))
    include_meetings = bool(context_input.get("include_meetings", True))
    avoid_congestion = bool(profile.raw_context.get("avoid_congestion", False))

    visited_booth_ids: set[uuid.UUID] = set()
    recommendable_rows = await db.execute(
        select(InteractionEvent.recommendable_id).where(
            InteractionEvent.tenant_id == subject.tenant_id,
            InteractionEvent.event_id == subject.event_id,
            InteractionEvent.event_type == _VISITED_EVENT_TYPE,
            InteractionEvent.recommendable_id.is_not(None),
            _owner_clause(
                InteractionEvent.user_id,
                InteractionEvent.guest_session_id,
                InteractionEvent.visit_session_id,
                subject,
            ),
        )
    )
    visited_recommendable_ids = {row.recommendable_id for row in recommendable_rows}
    if visited_recommendable_ids:
        booth_rows = await db.execute(
            select(Recommendable.booth_id).where(
                Recommendable.recommendable_id.in_(visited_recommendable_ids),
                Recommendable.booth_id.is_not(None),
            )
        )
        visited_booth_ids = {row.booth_id for row in booth_rows}

    upcoming_meetings: list[dict[str, Any]] = []
    upcoming_meeting_booth_ids: set[uuid.UUID] = set()
    if include_meetings and await _meeting_overlay_available(db):
        meeting_rows = await db.execute(
            text(
                "SELECT booth_id, confirmed_start "
                "FROM interaction.meeting "
                "WHERE tenant_id = :tenant_id AND event_id = :event_id "
                "AND buyer_profile_id = :profile_id AND status = :status "
                "AND confirmed_start IS NOT NULL AND confirmed_start >= :server_time "
                "ORDER BY confirmed_start ASC"
            ).bindparams(
                tenant_id=subject.tenant_id,
                event_id=subject.event_id,
                profile_id=subject.profile_id,
                status=_CONFIRMED_MEETING_STATUS,
                server_time=server_time,
            )
        )
        for booth_id, start_at in meeting_rows:
            upcoming_meetings.append({"start_at": start_at, "booth_id": booth_id})
            if booth_id is not None:
                upcoming_meeting_booth_ids.add(booth_id)

    # TODO(운영 스냅샷 버전 테이블 확정 후 교체): db-erd에 "operational_snapshot_version"
    # 전용 카운터 테이블이 아직 없어, 분 단위로 증가하는 시각 기반 근사값을 쓴다. 05번 문서
    # 8.3절 "준실시간 처리" 대상(부스 혼잡도·재고·상담가능시간)이 실제로 갱신되는 주기와
    # 맞춰 재현 가능한 버전 번호를 매기려면 전용 시퀀스/버전 테이블이 필요하다.
    operational_snapshot_version = int(server_time.timestamp() // 60)

    return ResolvedContext(
        current_zone=current_zone,
        current_zone_id=current_zone_id,
        remaining_minutes=remaining_minutes,
        visited_booth_ids=visited_booth_ids,
        upcoming_meetings=upcoming_meetings,
        upcoming_meeting_booth_ids=upcoming_meeting_booth_ids,
        operational_snapshot_version=operational_snapshot_version,
        exclude_visited=exclude_visited,
        include_meetings=include_meetings,
        avoid_congestion=avoid_congestion,
        server_time=server_time,
    )
