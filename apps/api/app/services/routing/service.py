"""Route creation/recalculation orchestration for the AI-recommended visit route feature (U-13).

Ties together the pure math (``pathfinding``), the position seam (``positioning``), and
persistence (``app.models.route``, ``app.models.indoor_positioning``) with the rest of the
domain model (booths, products, exhibitors, meetings, programs).

Approval/visibility filter
---------------------------
A route must never surface an unapproved/unpublished booth, product, or exhibitor - the same
invariant every other public-facing endpoint already enforces. Rather than re-deriving that
predicate, this module reuses
``app.services.exhibition_public_repository._approved_participation_stmt`` (see that module's
docstring, "Approval/visibility filters (applied everywhere in this module, never left to
callers)", for the exact enumerated list: ``Exhibitor.master_approval_status == 'APPROVED'``,
``Exhibitor.deleted_at IS NULL``, ``ExhibitorParticipation.participation_status == 'APPROVED'``,
``Event.event_status == 'OPEN'``). PRODUCT targets add ``EventProduct.approval_status ==
'APPROVED'`` on top (that predicate is not part of the reused helper because it needs an extra
join the booth/exhibitor path doesn't). MEETING targets are never "public" at all - they use a
narrower ownership check (the meeting must belong to the caller's own buyer profile) instead of
the approval predicate.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.auth import digest_secret
from app.core.config import Settings
from app.models.core import Event
from app.models.exhibitor import (
    Booth,
    BoothQr,
    EventProduct,
    Exhibitor,
    ExhibitorParticipation,
    Program,
)
from app.models.indoor_positioning import IndoorCheckpointScan
from app.models.matching import Recommendable
from app.models.meeting import MeetingRequest
from app.models.profile import VisitSession
from app.models.route import Route, RouteItem
from app.schemas.route import (
    RouteConstraints,
    RouteCreateRequest,
    RouteItemView,
    RouteResponse,
    RouteStartLocation,
    RouteTargetInput,
)
from app.services import exhibition_public_repository as repo
from app.services.routing import pathfinding
from app.services.routing.positioning import (
    PositionObservation,
    PositionQuery,
    resolve_current_position,
)

# app/services/exhibition_public_repository.py deliberately keeps this helper private
# (leading underscore) because that module's own public surface is the four ``fetch_*``
# functions. Reusing it directly here - rather than copying its WHERE clause - is intentional:
# the task instructions require this router to match the existing approval filter exactly, and a
# copy would silently drift the moment that predicate changes.
_approved_participation_stmt = repo._approved_participation_stmt

#: recommendations.py's internal/public object_type vocabulary mismatch, reused verbatim here so
#: route items expose the same public vocabulary every other endpoint already uses.
_INTERNAL_TO_PUBLIC_OBJECT_TYPE = {"EVENT_PRODUCT": "PRODUCT"}


class RouteServiceError(Exception):
    """User-facing routing error; the router maps this to an HTTP status/JSON body."""

    def __init__(self, code: str, message: str, *, http_status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


def target_not_found(object_type: str, object_id: str) -> RouteServiceError:
    return RouteServiceError(
        "ROUTE_TARGET_NOT_FOUND",
        f"{object_type} {object_id}를 방문 동선에 추가할 수 없습니다"
        "(승인되지 않았거나 존재하지 않습니다).",
        http_status=422,
    )


def route_forbidden() -> RouteServiceError:
    # Deliberately used for both "no such route" and "not your route" - recommendations.py's
    # list_recommendation_session_items follows the same "don't leak existence" convention
    # (인터페이스 명세 5절, see that router's inline comment) and this endpoint mirrors it.
    return RouteServiceError(
        "RESOURCE_FORBIDDEN", "본인 소유의 경로만 사용할 수 있습니다.", http_status=403
    )


def item_not_found() -> RouteServiceError:
    return RouteServiceError(
        "ROUTE_ITEM_NOT_FOUND", "경로 항목을 찾을 수 없습니다.", http_status=404
    )


def invalid_qr(message: str = "유효하지 않은 QR입니다.") -> RouteServiceError:
    return RouteServiceError("INVALID_QR", message, http_status=400)


# ---------------------------------------------------------------------------
# Target resolution
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ResolvedTarget:
    target_key: str
    recommendable_id: uuid.UUID | None
    meeting_id: uuid.UUID | None
    point: pathfinding.Point | None
    congested: bool
    priority: int
    expected_duration_minutes: int


def _booth_point(booth: Booth) -> pathfinding.Point | None:
    if booth.map_x is None or booth.map_y is None:
        return None
    return (float(booth.map_x), float(booth.map_y))


def _is_congested(booth: Booth, *, avoid_congestion: bool) -> bool:
    # See app/services/routing/pathfinding.py module docstring: this repo's actual congestion
    # levels are LOW/MEDIUM/HIGH/UNKNOWN (app/models/exhibitor.py BOOTH_CONGESTION_LEVELS), so
    # HIGH is treated as the "avoid this if possible" tier.
    return avoid_congestion and booth.congestion_level == "HIGH"


async def _primary_booth_for_participation(
    db: AsyncSession, *, participation_id: uuid.UUID, event_id: uuid.UUID
) -> Booth | None:
    return (
        await db.execute(
            select(Booth)
            .where(Booth.participation_id == participation_id, Booth.event_id == event_id)
            .order_by(Booth.booth_number, Booth.booth_id)
            .limit(1)
        )
    ).scalars().first()


async def _resolve_booth_target(
    db: AsyncSession, *, tenant_id: uuid.UUID, event_id: uuid.UUID, object_id: str
) -> tuple[uuid.UUID, Booth] | None:
    try:
        booth_id = uuid.UUID(object_id)
    except ValueError:
        return None
    row = (
        await db.execute(_approved_participation_stmt(event_id=event_id, booth_id=booth_id).limit(1))
    ).first()
    if row is None:
        return None
    _exhibitor, _participation, booth, _zone = row
    recommendable_id = await db.scalar(
        select(Recommendable.recommendable_id).where(
            Recommendable.booth_id == booth.booth_id,
            Recommendable.tenant_id == tenant_id,
            Recommendable.event_id == event_id,
        )
    )
    if recommendable_id is None:
        return None
    return recommendable_id, booth


async def _resolve_exhibitor_target(
    db: AsyncSession, *, tenant_id: uuid.UUID, event_id: uuid.UUID, object_id: str
) -> tuple[uuid.UUID, Booth | None] | None:
    try:
        exhibitor_id = uuid.UUID(object_id)
    except ValueError:
        return None
    row = (
        await db.execute(
            _approved_participation_stmt(event_id=event_id, exhibitor_id=exhibitor_id)
            .order_by(Booth.booth_number, Booth.booth_id)
            .limit(1)
        )
    ).first()
    if row is None:
        return None
    _exhibitor, participation, booth, _zone = row
    recommendable_id = await db.scalar(
        select(Recommendable.recommendable_id).where(
            Recommendable.participation_id == participation.participation_id,
            Recommendable.tenant_id == tenant_id,
            Recommendable.event_id == event_id,
        )
    )
    if recommendable_id is None:
        return None
    return recommendable_id, booth


async def _resolve_product_target(
    db: AsyncSession, *, tenant_id: uuid.UUID, event_id: uuid.UUID, object_id: str
) -> tuple[uuid.UUID, Booth | None] | None:
    try:
        product_id = uuid.UUID(object_id)
    except ValueError:
        return None
    # Same predicate as _approved_participation_stmt plus the EventProduct-level approval check
    # that path doesn't need (products join through EventProduct, booths/exhibitors don't).
    row = (
        await db.execute(
            select(Exhibitor, ExhibitorParticipation, EventProduct, Booth)
            .join(
                ExhibitorParticipation,
                ExhibitorParticipation.exhibitor_id == Exhibitor.exhibitor_id,
            )
            .join(
                EventProduct,
                EventProduct.participation_id == ExhibitorParticipation.participation_id,
            )
            .join(Event, Event.event_id == ExhibitorParticipation.event_id)
            .outerjoin(
                Booth,
                and_(
                    Booth.participation_id == ExhibitorParticipation.participation_id,
                    Booth.event_id == ExhibitorParticipation.event_id,
                ),
            )
            .where(
                Exhibitor.master_approval_status == "APPROVED",
                Exhibitor.deleted_at.is_(None),
                ExhibitorParticipation.participation_status == "APPROVED",
                Event.event_status == "OPEN",
                EventProduct.product_id == product_id,
                EventProduct.event_id == event_id,
                EventProduct.approval_status == "APPROVED",
            )
            .order_by(Booth.booth_number, Booth.booth_id)
            .limit(1)
        )
    ).first()
    if row is None:
        return None
    _exhibitor, _participation, event_product, booth = row
    recommendable_id = await db.scalar(
        select(Recommendable.recommendable_id).where(
            Recommendable.event_product_id == event_product.event_product_id,
            Recommendable.tenant_id == tenant_id,
            Recommendable.event_id == event_id,
        )
    )
    if recommendable_id is None:
        return None
    return recommendable_id, booth


async def _resolve_program_target(
    db: AsyncSession, *, tenant_id: uuid.UUID, event_id: uuid.UUID, object_id: str
) -> uuid.UUID | None:
    try:
        program_id = uuid.UUID(object_id)
    except ValueError:
        return None
    program = await db.get(Program, program_id)
    if (
        program is None
        or program.tenant_id != tenant_id
        or program.event_id != event_id
        or program.status == "CANCELLED"
    ):
        return None
    return await db.scalar(
        select(Recommendable.recommendable_id).where(
            Recommendable.program_id == program.program_id,
            Recommendable.tenant_id == tenant_id,
            Recommendable.event_id == event_id,
        )
    )


async def _resolve_meeting_target(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    event_id: uuid.UUID,
    profile_id: uuid.UUID | None,
    object_id: str,
) -> tuple[uuid.UUID, Booth | None] | None:
    try:
        meeting_id = uuid.UUID(object_id)
    except ValueError:
        return None
    meeting = await db.get(MeetingRequest, meeting_id)
    if (
        meeting is None
        or meeting.tenant_id != tenant_id
        or meeting.event_id != event_id
        or profile_id is None
        or meeting.buyer_profile_id != profile_id
    ):
        # A route can never carry another buyer's meeting - meetings are never "public".
        return None
    booth: Booth | None = None
    participation = await db.get(ExhibitorParticipation, meeting.participation_id)
    if participation is not None and participation.participation_status == "APPROVED":
        booth = await _primary_booth_for_participation(
            db, participation_id=participation.participation_id, event_id=event_id
        )
    return meeting_id, booth


async def _resolve_target(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    event_id: uuid.UUID,
    profile_id: uuid.UUID | None,
    target: RouteTargetInput,
    avoid_congestion: bool,
    index: int,
) -> ResolvedTarget | None:
    key = f"{index}:{target.object_type}:{target.object_id}"
    priority = target.priority if target.priority is not None else index + 1
    duration = (
        target.expected_duration_minutes
        if target.expected_duration_minutes is not None
        else 15
    )

    if target.object_type == "BOOTH":
        resolved = await _resolve_booth_target(
            db, tenant_id=tenant_id, event_id=event_id, object_id=target.object_id
        )
        if resolved is None:
            return None
        recommendable_id, booth = resolved
        return ResolvedTarget(
            key, recommendable_id, None, _booth_point(booth),
            _is_congested(booth, avoid_congestion=avoid_congestion), priority, duration,
        )

    if target.object_type == "EXHIBITOR":
        resolved = await _resolve_exhibitor_target(
            db, tenant_id=tenant_id, event_id=event_id, object_id=target.object_id
        )
        if resolved is None:
            return None
        recommendable_id, booth = resolved
        point = _booth_point(booth) if booth is not None else None
        congested = _is_congested(booth, avoid_congestion=avoid_congestion) if booth else False
        return ResolvedTarget(key, recommendable_id, None, point, congested, priority, duration)

    if target.object_type == "PRODUCT":
        resolved = await _resolve_product_target(
            db, tenant_id=tenant_id, event_id=event_id, object_id=target.object_id
        )
        if resolved is None:
            return None
        recommendable_id, booth = resolved
        point = _booth_point(booth) if booth is not None else None
        congested = _is_congested(booth, avoid_congestion=avoid_congestion) if booth else False
        return ResolvedTarget(key, recommendable_id, None, point, congested, priority, duration)

    if target.object_type == "PROGRAM":
        # exhibition.program has no map_x/map_y (only a zone_id) - there is no coordinate to
        # resolve today. The target is still valid and still counted toward the visit's total
        # time; it just cannot participate in geometric ordering (see
        # pathfinding.nearest_neighbor_order's handling of point=None).
        recommendable_id = await _resolve_program_target(
            db, tenant_id=tenant_id, event_id=event_id, object_id=target.object_id
        )
        if recommendable_id is None:
            return None
        return ResolvedTarget(key, recommendable_id, None, None, False, priority, duration)

    if target.object_type == "MEETING":
        resolved = await _resolve_meeting_target(
            db,
            tenant_id=tenant_id,
            event_id=event_id,
            profile_id=profile_id,
            object_id=target.object_id,
        )
        if resolved is None:
            return None
        meeting_id, booth = resolved
        point = _booth_point(booth) if booth is not None else None
        congested = _is_congested(booth, avoid_congestion=avoid_congestion) if booth else False
        return ResolvedTarget(key, None, meeting_id, point, congested, priority, duration)

    return None


def _fallback_point(objs) -> pathfinding.Point:
    """When no current-position signal resolves at all, degrade to "start at the nearest
    resolvable stop" (distance 0 to itself) instead of fabricating a coordinate. Only reached
    when every provider in services/routing/positioning.py returned None *and* no target has a
    resolvable point either, in which case (0.0, 0.0) is an arbitrary-but-deterministic origin.
    """

    for obj in objs:
        if obj.point is not None:
            return obj.point
    return (0.0, 0.0)


def _derive_route_preference(constraints: RouteConstraints) -> str:
    """db-erd 16.4절 "최적화 유형" is not a separate field the client sends for /routes - it is
    derived here from the constraints actually supplied, using the same candidate vocabulary
    07 문서's VisitPlanRequest.route_preference already established (LOW_CONGESTION/SHORTEST/
    RECOMMENDED_FIRST).
    """

    if constraints.avoid_congestion:
        return "LOW_CONGESTION"
    if constraints.minimize_walking:
        return "SHORTEST"
    return "RECOMMENDED_FIRST"


# ---------------------------------------------------------------------------
# Route creation
# ---------------------------------------------------------------------------


async def resolve_or_create_visit_session(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    event_id: uuid.UUID,
    user_id: uuid.UUID,
    profile_id: uuid.UUID | None,
) -> VisitSession:
    existing = (
        await db.execute(
            select(VisitSession)
            .where(
                VisitSession.tenant_id == tenant_id,
                VisitSession.event_id == event_id,
                VisitSession.user_id == user_id,
            )
            .order_by(VisitSession.created_at.desc())
            .limit(1)
        )
    ).scalars().first()
    if existing is not None:
        return existing
    visit = VisitSession(
        tenant_id=tenant_id,
        event_id=event_id,
        user_id=user_id,
        profile_id=profile_id,
        visit_date=datetime.now(UTC).date(),
        session_status="ACTIVE",
    )
    db.add(visit)
    await db.flush()
    return visit


async def create_route(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    event_id: uuid.UUID,
    profile_id: uuid.UUID | None,
    visit_session_id: uuid.UUID,
    payload: RouteCreateRequest,
) -> Route:
    now = datetime.now(UTC)

    resolved: list[ResolvedTarget] = []
    for index, target in enumerate(payload.targets):
        item = await _resolve_target(
            db,
            tenant_id=tenant_id,
            event_id=event_id,
            profile_id=profile_id,
            target=target,
            avoid_congestion=payload.constraints.avoid_congestion,
            index=index,
        )
        if item is None:
            raise target_not_found(target.object_type, target.object_id)
        resolved.append(item)

    position = await resolve_current_position(
        db,
        PositionQuery(
            tenant_id=tenant_id,
            event_id=event_id,
            visit_session_id=visit_session_id,
            start_location=payload.start_location,
            now=now,
        ),
    )
    start_point = (
        (position.map_x, position.map_y) if position is not None else _fallback_point(resolved)
    )

    candidates = [
        pathfinding.RouteCandidate(
            key=r.target_key,
            point=r.point,
            priority=r.priority,
            expected_duration_minutes=r.expected_duration_minutes,
            congested=r.congested,
        )
        for r in resolved
    ]
    ordered = pathfinding.fit_to_budget(
        start_point,
        candidates,
        available_minutes=payload.constraints.available_minutes,
        avoid_congestion=payload.constraints.avoid_congestion,
    )
    walking_minutes = pathfinding.estimate_walking_minutes(start_point, ordered)
    total_minutes = pathfinding.estimate_total_minutes(walking_minutes, ordered)

    route = Route(
        tenant_id=tenant_id,
        event_id=event_id,
        visit_session_id=visit_session_id,
        route_preference=_derive_route_preference(payload.constraints),
        total_minutes=round(total_minutes),
        walking_minutes=round(walking_minutes),
        status="ACTIVE",
        context_snapshot={
            "start_location": payload.start_location.model_dump(mode="json"),
            "constraints": payload.constraints.model_dump(mode="json"),
            "targets": [t.model_dump(mode="json") for t in payload.targets],
            "positioning_source": position.source if position is not None else None,
            "generated_at": now.isoformat(),
        },
    )
    db.add(route)
    await db.flush()

    by_key = {r.target_key: r for r in resolved}
    cursor_time = now
    cursor_point = start_point
    for sequence, candidate in enumerate(ordered):
        target_data = by_key[candidate.key]
        if candidate.point is not None:
            walk_minutes = (
                pathfinding.euclidean_distance(cursor_point, candidate.point)
                / pathfinding.WALKING_SPEED_PLAN_UNITS_PER_MINUTE
            )
            cursor_time = cursor_time + timedelta(minutes=walk_minutes)
            cursor_point = candidate.point
        db.add(
            RouteItem(
                route_id=route.route_id,
                sequence=sequence,
                recommendable_id=target_data.recommendable_id,
                meeting_id=target_data.meeting_id,
                expected_arrival_at=cursor_time,
                expected_stay_minutes=target_data.expected_duration_minutes,
                status="PENDING",
            )
        )
        cursor_time = cursor_time + timedelta(minutes=target_data.expected_duration_minutes)

    await db.commit()
    await db.refresh(route, attribute_names=["items"])
    return route


# ---------------------------------------------------------------------------
# Recalculation
# ---------------------------------------------------------------------------


async def _public_object_ref(
    db: AsyncSession, *, recommendable_id: uuid.UUID | None, meeting_id: uuid.UUID | None
) -> tuple[str | None, str | None]:
    if meeting_id is not None:
        return "MEETING", str(meeting_id)
    if recommendable_id is None:
        return None, None
    recommendable = await db.get(Recommendable, recommendable_id)
    if recommendable is None:
        return None, None
    if recommendable.object_type == "BOOTH":
        return "BOOTH", str(recommendable.booth_id)
    if recommendable.object_type == "EVENT_PRODUCT":
        product_id = await db.scalar(
            select(EventProduct.product_id).where(
                EventProduct.event_product_id == recommendable.event_product_id
            )
        )
        return "PRODUCT", str(product_id or recommendable.event_product_id)
    if recommendable.object_type == "PROGRAM":
        return "PROGRAM", str(recommendable.program_id)
    if recommendable.object_type == "EXHIBITOR":
        exhibitor_id = await db.scalar(
            select(ExhibitorParticipation.exhibitor_id).where(
                ExhibitorParticipation.participation_id == recommendable.participation_id
            )
        )
        return "EXHIBITOR", str(exhibitor_id or recommendable.participation_id)
    return None, None


async def _hydrate_pending_candidate(
    db: AsyncSession,
    *,
    item: RouteItem,
    event_id: uuid.UUID,
    avoid_congestion: bool,
    priority_lookup: dict[tuple[str | None, str | None], int],
) -> pathfinding.RouteCandidate:
    """Re-derive a pending item's current coordinate/congestion (booth state may have changed
    since the route was created - that is the entire point of "recalculate") plus its original
    priority (recovered from the route's stored ``context_snapshot.targets`` by object identity,
    since ``interaction.route_item`` intentionally does not persist priority - db-erd 16.4절 only
    lists sequence/recommendable_id/meeting_id/arrival/stay/status).
    """

    object_type, object_id = await _public_object_ref(
        db, recommendable_id=item.recommendable_id, meeting_id=item.meeting_id
    )
    booth: Booth | None = None
    if item.recommendable_id is not None:
        recommendable = await db.get(Recommendable, item.recommendable_id)
        if recommendable is not None:
            if recommendable.object_type == "BOOTH":
                booth = await db.get(Booth, recommendable.booth_id)
            elif recommendable.object_type == "EVENT_PRODUCT":
                event_product = await db.get(EventProduct, recommendable.event_product_id)
                if event_product is not None:
                    booth = await _primary_booth_for_participation(
                        db,
                        participation_id=event_product.participation_id,
                        event_id=event_id,
                    )
            elif recommendable.object_type == "EXHIBITOR":
                booth = await _primary_booth_for_participation(
                    db, participation_id=recommendable.participation_id, event_id=event_id
                )
    elif item.meeting_id is not None:
        meeting = await db.get(MeetingRequest, item.meeting_id)
        if meeting is not None:
            booth = await _primary_booth_for_participation(
                db, participation_id=meeting.participation_id, event_id=event_id
            )

    point = _booth_point(booth) if booth is not None else None
    congested = _is_congested(booth, avoid_congestion=avoid_congestion) if booth else False
    priority = priority_lookup.get((object_type, object_id), 999)
    duration = item.expected_stay_minutes if item.expected_stay_minutes is not None else 15
    return pathfinding.RouteCandidate(
        key=str(item.route_item_id),
        point=point,
        priority=priority,
        expected_duration_minutes=duration,
        congested=congested,
    )


async def recalculate_route(db: AsyncSession, *, route: Route) -> Route:
    """Recompute the ordering/timing of a route's still-``PENDING`` stops from the visitor's
    current position. Stops already marked ARRIVED/SKIPPED/COMPLETED keep their existing
    ``sequence`` untouched - only pending stops are re-ordered and re-numbered after them.
    """

    now = datetime.now(UTC)
    items = sorted(route.items, key=lambda i: i.sequence)
    locked_items = [i for i in items if i.status != "PENDING"]
    pending_items = [i for i in items if i.status == "PENDING"]

    walking_minutes = 0.0
    ordered: list[pathfinding.RouteCandidate] = []
    position: PositionObservation | None = None

    if pending_items:
        snapshot = route.context_snapshot or {}
        start_location = (
            RouteStartLocation.model_validate(snapshot["start_location"])
            if snapshot.get("start_location")
            else None
        )
        constraints = RouteConstraints.model_validate(snapshot.get("constraints") or {})
        priority_lookup: dict[tuple[str | None, str | None], int] = {}
        for index, raw in enumerate(snapshot.get("targets") or []):
            obj_type, obj_id = raw.get("object_type"), raw.get("object_id")
            if obj_type is None or obj_id is None:
                continue
            priority_lookup[(obj_type, obj_id)] = raw.get("priority") or index + 1

        position = await resolve_current_position(
            db,
            PositionQuery(
                tenant_id=route.tenant_id,
                event_id=route.event_id,
                visit_session_id=route.visit_session_id,
                start_location=start_location,
                now=now,
            ),
        )

        candidates = [
            await _hydrate_pending_candidate(
                db,
                item=item,
                event_id=route.event_id,
                avoid_congestion=constraints.avoid_congestion,
                priority_lookup=priority_lookup,
            )
            for item in pending_items
        ]
        start_point = (
            (position.map_x, position.map_y)
            if position is not None
            else _fallback_point(candidates)
        )
        ordered = pathfinding.fit_to_budget(
            start_point,
            candidates,
            available_minutes=constraints.available_minutes,
            avoid_congestion=constraints.avoid_congestion,
        )

        by_key = {str(item.route_item_id): item for item in pending_items}
        kept_keys = {candidate.key for candidate in ordered}
        for item in pending_items:
            if str(item.route_item_id) not in kept_keys:
                await db.delete(item)

        next_sequence = (max((i.sequence for i in locked_items), default=-1)) + 1
        cursor_time = now
        cursor_point = start_point
        for candidate in ordered:
            item = by_key[candidate.key]
            if candidate.point is not None:
                walk_minutes = (
                    pathfinding.euclidean_distance(cursor_point, candidate.point)
                    / pathfinding.WALKING_SPEED_PLAN_UNITS_PER_MINUTE
                )
                cursor_time = cursor_time + timedelta(minutes=walk_minutes)
                cursor_point = candidate.point
            item.sequence = next_sequence
            item.expected_arrival_at = cursor_time
            next_sequence += 1
            cursor_time = cursor_time + timedelta(minutes=candidate.expected_duration_minutes)

        walking_minutes = pathfinding.estimate_walking_minutes(start_point, ordered)

        if snapshot:
            snapshot = dict(snapshot)
            snapshot["positioning_source"] = position.source if position is not None else None
            snapshot["recalculated_at"] = now.isoformat()
            route.context_snapshot = snapshot

    # Total time = time remaining for pending stops + stay time already logged for completed/
    # arrived/skipped ones (their walking time already happened and isn't re-estimated).
    locked_stay_minutes = sum(i.expected_stay_minutes or 0 for i in locked_items)
    total_minutes = pathfinding.estimate_total_minutes(walking_minutes, ordered) + locked_stay_minutes
    route.walking_minutes = round(walking_minutes)
    route.total_minutes = round(total_minutes)
    route.row_version += 1

    await db.commit()
    await db.refresh(route, attribute_names=["items"])
    return route


# ---------------------------------------------------------------------------
# Access control + reads
# ---------------------------------------------------------------------------


async def get_owned_route(
    db: AsyncSession, *, route_id: uuid.UUID, tenant_id: uuid.UUID, event_id: uuid.UUID, user_id: uuid.UUID
) -> Route:
    route = (
        await db.execute(
            select(Route)
            .where(Route.route_id == route_id)
            .options(selectinload(Route.items))
        )
    ).scalar_one_or_none()
    if route is None or route.tenant_id != tenant_id or route.event_id != event_id:
        raise route_forbidden()
    owner_user_id = await db.scalar(
        select(VisitSession.user_id).where(
            VisitSession.visit_session_id == route.visit_session_id
        )
    )
    if owner_user_id is None or owner_user_id != user_id:
        raise route_forbidden()
    return route


def get_owned_item(route: Route, item_id: uuid.UUID) -> RouteItem:
    for item in route.items:
        if item.route_item_id == item_id:
            return item
    raise item_not_found()


async def update_item_status(
    db: AsyncSession,
    *,
    route: Route,
    item: RouteItem,
    new_status: str,
    occurred_at: datetime | None,
) -> RouteItem:
    item.status = new_status
    if new_status in ("ARRIVED", "COMPLETED") and item.actual_arrival_at is None:
        item.actual_arrival_at = occurred_at or datetime.now(UTC)
    route.row_version += 1
    await db.commit()
    await db.refresh(route, attribute_names=["items"])
    return get_owned_item(route, item.route_item_id)


async def to_route_response(db: AsyncSession, route: Route) -> RouteResponse:
    items = sorted(route.items, key=lambda i: i.sequence)
    views: list[RouteItemView] = []
    for item in items:
        object_type, object_id = await _public_object_ref(
            db, recommendable_id=item.recommendable_id, meeting_id=item.meeting_id
        )
        views.append(
            RouteItemView(
                sequence=item.sequence,
                object_type=object_type,
                object_id=object_id,
                expected_arrival_at=item.expected_arrival_at,
                expected_stay_minutes=item.expected_stay_minutes,
                actual_arrival_at=item.actual_arrival_at,
                status=item.status,
            )
        )
    return RouteResponse(
        route_id=route.route_id,
        visit_session_id=route.visit_session_id,
        route_preference=route.route_preference,
        total_minutes=route.total_minutes,
        walking_minutes=route.walking_minutes,
        status=route.status,
        items=views,
    )


# ---------------------------------------------------------------------------
# Checkpoint QR scan-in
# ---------------------------------------------------------------------------

#: HMAC "purpose" label for booth-QR checkpoint verification, reusing
#: app.core.auth.digest_secret - the same helper every other token in this codebase (browser
#: session, guest session, personal link) is verified with. There is no pre-existing "verify a
#: booth_qr token" endpoint anywhere in this repository to reuse wholesale (grepped
#: app/api/v1/routers/kiosk.py and app/services/kiosk.py - their QR flow is an unrelated kiosk
#: search-result handoff token, not exhibition.booth_qr), so this is the closest honest reuse:
#: same digesting primitive, same pepper/settings, distinct purpose string so a token minted for
#: one purpose can never verify against another.
_BOOTH_QR_CHECKPOINT_PURPOSE = "booth-qr-checkpoint"


async def record_checkpoint_scan(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    event_id: uuid.UUID,
    visit_session_id: uuid.UUID,
    qr_token: str,
    settings: Settings,
) -> tuple[IndoorCheckpointScan, Route | None]:
    now = datetime.now(UTC)
    token_hmac = digest_secret(qr_token, purpose=_BOOTH_QR_CHECKPOINT_PURPOSE, settings=settings)
    row = (
        await db.execute(
            select(BoothQr, Booth)
            .join(Booth, Booth.booth_id == BoothQr.booth_id)
            .where(
                BoothQr.token_hmac == token_hmac,
                BoothQr.status == "ACTIVE",
                Booth.tenant_id == tenant_id,
                Booth.event_id == event_id,
            )
            .limit(1)
        )
    ).first()
    if row is None:
        raise invalid_qr()
    booth_qr, booth = row
    if booth_qr.valid_from is not None and now < booth_qr.valid_from:
        raise invalid_qr("아직 사용할 수 없는 QR입니다.")
    if booth_qr.valid_until is not None and now > booth_qr.valid_until:
        raise invalid_qr("만료된 QR입니다.")

    scan = IndoorCheckpointScan(
        tenant_id=tenant_id,
        event_id=event_id,
        visit_session_id=visit_session_id,
        booth_id=booth.booth_id,
        booth_qr_id=booth_qr.booth_qr_id,
        scanned_at=now,
    )
    db.add(scan)
    await db.flush()

    active_route = (
        await db.execute(
            select(Route)
            .where(
                Route.tenant_id == tenant_id,
                Route.event_id == event_id,
                Route.visit_session_id == visit_session_id,
                Route.status == "ACTIVE",
            )
            .options(selectinload(Route.items))
            .order_by(Route.created_at.desc())
            .limit(1)
        )
    ).scalars().first()

    if active_route is None:
        await db.commit()
        await db.refresh(scan)
        return scan, None

    active_route = await recalculate_route(db, route=active_route)
    await db.refresh(scan)
    return scan, active_route


__all__ = [
    "RouteServiceError",
    "create_route",
    "get_owned_item",
    "get_owned_route",
    "invalid_qr",
    "item_not_found",
    "recalculate_route",
    "record_checkpoint_scan",
    "resolve_or_create_visit_session",
    "route_forbidden",
    "target_not_found",
    "to_route_response",
    "update_item_status",
]
