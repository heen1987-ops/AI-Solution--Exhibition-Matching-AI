"""Operator-authored "event message" campaign API router - WAVE 2E ADMIN-NOTIFICATION.

Not owned by any other track's router file in this batch. The task instructions for this track
explicitly note that ``apps/api/app/api/v1/routers/`` is nominally BACKEND-owned
(``.harness/locks.yaml``) but call out this one filename as available: "you may create that
router file yourself since it is not explicitly owned by another track in this batch". Following
the same reasoning already applied elsewhere in this wave for a track's own net-new domain (see
e.g. ``app/models/notification.py``/``app/db/base.py``'s ``SCHEMA_NOTIFICATION`` addition, done
by that track despite ``app/db/base.py`` being nominally BACKEND-owned too), this track also
built the full vertical this router depends on
(``app/models/event_message.py``, ``app/schemas/event_message.py``,
``app/services/event_message/**``) rather than a router with nothing to call - a router with no
model/schema/service behind it would not satisfy this track's stated acceptance criteria
("workflow-state transitions, targeting restricted to the safe segment list ... preview
computation, small-audience warning, content rejection" - none of that exists without them).
Flagged explicitly in this track's final report for integrator review, per repo convention (see
e.g. ``app/api/v1/routers/exhibitor_preference.py``'s own docstring for the same kind of
disclosure).

This module exposes ``build_event_message_router()`` (not a bare ``router`` - repo convention
for a router file whose registration into ``app/api/v1/api.py`` is the integrator's job, see
``app/api/v1/routers/buyer_match.py``/``exhibitor_preference.py`` for the identical pattern) so
the integrator can mount it under an ``/admin`` prefix::

    from app.api.v1.routers.event_message import build_event_message_router
    api_router.include_router(
        build_event_message_router(), prefix="/admin", tags=["admin-event-messages"]
    )

Exposed paths (relative - integrator picks the final prefix, see above):
    POST   /event-messages                          - create (DRAFT)
    GET    /event-messages                           - list (event_id required, status optional)
    GET    /event-messages/{id}                       - read one
    PATCH  /event-messages/{id}                        - edit (row_version required in body)
    POST   /event-messages/{id}/preview                - compute/refresh preview, DRAFT->PREVIEWED
    POST   /event-messages/{id}/approve                 - PREVIEWED->APPROVED
    POST   /event-messages/{id}/schedule                - APPROVED->SCHEDULED
    POST   /event-messages/{id}/publish                 - APPROVED/SCHEDULED->PUBLISHED
    POST   /event-messages/{id}/cancel                   - APPROVED/SCHEDULED->CANCELLED (reason required)
    POST   /event-messages/{id}/complete                  - PUBLISHED->COMPLETED

Authentication and authorization (integration, merge plan STEP 23)
-------------------------------------------------------------------
The WAVE 2E original took the actor from a client-supplied actor-id header and then resolved
a tenant from that actor's own role rows. Both are gone:

* identity comes from ``app/core/router_auth.py``'s ``get_actor_user_id``, i.e. from a
  verified session/JWT principal only;
* ``tenant_id`` comes from ``principal.principal.tenant_id`` - the tenant the session was
  established against - never from a client-supplied header and no longer from a
  first-matching-role lookup (an actor holding operator rows in two tenants used to get a
  non-deterministic one);
* ``_require_operator_role`` is kept unchanged. It is the legacy-vocabulary authorization
  half and is genuinely correct: it re-checks OPERATOR/ADMIN in ``profile.user_role``
  scoped to *that* tenant, so an authenticated caller from another tenant gets 403;
* the three irreversible transitions (approve / schedule / publish) additionally carry
  ``require_roles("EVENT_ADMIN", fresh_mfa=True)``, matching how main already treats bulk
  import. Broadcasting to an entire event is not undoable, so it demands a recent MFA.

Targeting stays restricted to the coarse legitimate segments enumerated in
``app/services/event_message/targeting.py`` (no sensitive-attribute and no fine-grained
behavioural targeting - a disallowed segment is a 422 TARGET_SEGMENT_NOT_ALLOWED), and the
preview step returns the small-audience warning that must be seen before publish.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import VerifiedPrincipal, get_verified_principal, require_roles
from app.core.router_auth import get_actor_user_id
from app.db.session import get_db
from app.models.event_message import EventMessage
from app.models.identity import Role, UserRole
from app.schemas.event_message import (
    EventMessageApproveRequest,
    EventMessageCancelRequest,
    EventMessageCompleteRequest,
    EventMessageCreateRequest,
    EventMessageListResponse,
    EventMessagePreview,
    EventMessagePublishRequest,
    EventMessageRead,
    EventMessageScheduleRequest,
    EventMessageUpdateRequest,
    PublishResult,
)
from app.services.event_message import service
from app.services.event_message.content import ContentValidationError
from app.services.event_message.service import VersionConflictError
from app.services.event_message.targeting import TargetSegmentNotAllowedError
from app.services.event_message.workflow import InvalidTransitionError, NotEditableError

ActorUserId = Annotated[uuid.UUID, Depends(get_actor_user_id)]
Principal = Annotated[VerifiedPrincipal, Depends(get_verified_principal)]
DbSession = Annotated[AsyncSession, Depends(get_db)]

#: approve / schedule / publish are irreversible event-wide broadcasts - see the module
#: docstring. ``require_roles`` resolves the same cached principal the handlers use.
REQUIRE_FRESH_EVENT_ADMIN = Depends(require_roles("EVENT_ADMIN", fresh_mfa=True))


async def _require_operator_role(
    db: AsyncSession, *, actor_user_id: uuid.UUID, tenant_id: uuid.UUID
) -> None:
    """Only OPERATOR/ADMIN may author/approve/publish event messages - this is an operator
    authoring tool, not a general-purpose notification API (task spec: "operator authoring
    tool")."""

    stmt = (
        select(UserRole.user_role_id)
        .join(Role, Role.role_id == UserRole.role_id)
        .where(
            UserRole.tenant_id == tenant_id,
            UserRole.user_id == actor_user_id,
            UserRole.valid_until.is_(None),
            Role.role_code.in_(("OPERATOR", "ADMIN")),
        )
        .limit(1)
    )
    allowed = (await db.execute(stmt)).scalar_one_or_none()
    if allowed is None:
        raise HTTPException(status_code=403, detail="RESOURCE_FORBIDDEN")


async def _get_or_404(
    db: AsyncSession, *, tenant_id: uuid.UUID, event_message_id: uuid.UUID
) -> EventMessage:
    event_message = await service.get_event_message(
        db, tenant_id=tenant_id, event_message_id=event_message_id
    )
    if event_message is None:
        raise HTTPException(status_code=404, detail="EVENT_MESSAGE_NOT_FOUND")
    return event_message


def _handle_service_errors(exc: Exception) -> HTTPException:
    if isinstance(exc, VersionConflictError):
        return HTTPException(status_code=409, detail=f"EVENT_MESSAGE_VERSION_CONFLICT:{exc}")
    if isinstance(exc, (InvalidTransitionError, NotEditableError)):
        return HTTPException(status_code=409, detail=f"EVENT_MESSAGE_INVALID_TRANSITION:{exc}")
    if isinstance(exc, ContentValidationError):
        return HTTPException(status_code=422, detail=f"CONTENT_REJECTED:{exc.reason_code}:{exc}")
    if isinstance(exc, TargetSegmentNotAllowedError):
        return HTTPException(status_code=422, detail=f"TARGET_SEGMENT_NOT_ALLOWED:{exc}")
    return HTTPException(status_code=400, detail=str(exc))


def build_event_message_router() -> APIRouter:
    """Independent router carrying this track's endpoints. Mounting is the integrator's
    responsibility (module docstring)."""

    router = APIRouter()

    @router.post("/event-messages", response_model=EventMessageRead, status_code=201)
    async def create_event_message(
        body: EventMessageCreateRequest,
        actor_user_id: ActorUserId,
        principal: Principal,
        db: DbSession,
    ) -> EventMessage:
        # tenant_id is the tenant this session/JWT was established against - never a
        # client-supplied value, and no longer a first-matching-role lookup.
        tenant_id = principal.principal.tenant_id
        await _require_operator_role(db, actor_user_id=actor_user_id, tenant_id=tenant_id)
        try:
            return await service.create_event_message(
                db, tenant_id=tenant_id, actor_user_id=actor_user_id, payload=body
            )
        except (ContentValidationError, TargetSegmentNotAllowedError) as exc:
            raise _handle_service_errors(exc) from exc

    @router.get("/event-messages", response_model=EventMessageListResponse)
    async def list_event_messages(
        event_id: uuid.UUID,
        actor_user_id: ActorUserId,
        principal: Principal,
        db: DbSession,
        status: str | None = None,
    ) -> EventMessageListResponse:
        tenant_id = principal.principal.tenant_id
        await _require_operator_role(db, actor_user_id=actor_user_id, tenant_id=tenant_id)
        items = await service.list_event_messages(
            db, tenant_id=tenant_id, event_id=event_id, status=status
        )
        return EventMessageListResponse(
            items=[EventMessageRead.model_validate(item) for item in items]
        )

    @router.get("/event-messages/{event_message_id}", response_model=EventMessageRead)
    async def get_event_message(
        event_message_id: uuid.UUID,
        actor_user_id: ActorUserId,
        principal: Principal,
        db: DbSession,
    ) -> EventMessage:
        tenant_id = principal.principal.tenant_id
        await _require_operator_role(db, actor_user_id=actor_user_id, tenant_id=tenant_id)
        return await _get_or_404(db, tenant_id=tenant_id, event_message_id=event_message_id)

    @router.patch("/event-messages/{event_message_id}", response_model=EventMessageRead)
    async def update_event_message(
        event_message_id: uuid.UUID,
        body: EventMessageUpdateRequest,
        actor_user_id: ActorUserId,
        principal: Principal,
        db: DbSession,
    ) -> EventMessage:
        tenant_id = principal.principal.tenant_id
        await _require_operator_role(db, actor_user_id=actor_user_id, tenant_id=tenant_id)
        event_message = await _get_or_404(
            db, tenant_id=tenant_id, event_message_id=event_message_id
        )
        try:
            return await service.update_event_message(db, event_message, body)
        except (
            VersionConflictError,
            NotEditableError,
            ContentValidationError,
            TargetSegmentNotAllowedError,
        ) as exc:
            raise _handle_service_errors(exc) from exc

    @router.post(
        "/event-messages/{event_message_id}/preview", response_model=EventMessagePreview
    )
    async def preview_event_message(
        event_message_id: uuid.UUID,
        actor_user_id: ActorUserId,
        principal: Principal,
        db: DbSession,
    ) -> EventMessagePreview:
        tenant_id = principal.principal.tenant_id
        await _require_operator_role(db, actor_user_id=actor_user_id, tenant_id=tenant_id)
        event_message = await _get_or_404(
            db, tenant_id=tenant_id, event_message_id=event_message_id
        )
        try:
            return await service.preview_event_message(db, event_message)
        except InvalidTransitionError as exc:
            raise _handle_service_errors(exc) from exc

    @router.post(
        "/event-messages/{event_message_id}/approve",
        response_model=EventMessageRead,
        dependencies=[REQUIRE_FRESH_EVENT_ADMIN],
    )
    async def approve_event_message(
        event_message_id: uuid.UUID,
        body: EventMessageApproveRequest,
        actor_user_id: ActorUserId,
        principal: Principal,
        db: DbSession,
    ) -> EventMessage:
        tenant_id = principal.principal.tenant_id
        await _require_operator_role(db, actor_user_id=actor_user_id, tenant_id=tenant_id)
        event_message = await _get_or_404(
            db, tenant_id=tenant_id, event_message_id=event_message_id
        )
        try:
            return await service.approve_event_message(
                db,
                event_message,
                actor_user_id=actor_user_id,
                row_version=body.row_version,
            )
        except (VersionConflictError, InvalidTransitionError) as exc:
            raise _handle_service_errors(exc) from exc

    @router.post(
        "/event-messages/{event_message_id}/schedule",
        response_model=EventMessageRead,
        dependencies=[REQUIRE_FRESH_EVENT_ADMIN],
    )
    async def schedule_event_message(
        event_message_id: uuid.UUID,
        body: EventMessageScheduleRequest,
        actor_user_id: ActorUserId,
        principal: Principal,
        db: DbSession,
    ) -> EventMessage:
        tenant_id = principal.principal.tenant_id
        await _require_operator_role(db, actor_user_id=actor_user_id, tenant_id=tenant_id)
        event_message = await _get_or_404(
            db, tenant_id=tenant_id, event_message_id=event_message_id
        )
        try:
            return await service.schedule_event_message(
                db,
                event_message,
                row_version=body.row_version,
                scheduled_at=body.scheduled_at,
            )
        except (VersionConflictError, InvalidTransitionError) as exc:
            raise _handle_service_errors(exc) from exc

    @router.post(
        "/event-messages/{event_message_id}/publish",
        response_model=PublishResult,
        dependencies=[REQUIRE_FRESH_EVENT_ADMIN],
    )
    async def publish_event_message(
        event_message_id: uuid.UUID,
        body: EventMessagePublishRequest,
        actor_user_id: ActorUserId,
        principal: Principal,
        db: DbSession,
    ) -> PublishResult:
        tenant_id = principal.principal.tenant_id
        await _require_operator_role(db, actor_user_id=actor_user_id, tenant_id=tenant_id)
        event_message = await _get_or_404(
            db, tenant_id=tenant_id, event_message_id=event_message_id
        )
        try:
            updated, recipient_count, excluded_count = await service.publish_event_message(
                db, event_message, row_version=body.row_version
            )
        except (VersionConflictError, InvalidTransitionError) as exc:
            raise _handle_service_errors(exc) from exc
        return PublishResult(
            event_message=EventMessageRead.model_validate(updated),
            resolved_recipient_count=recipient_count,
            email_consent_excluded_count=excluded_count,
        )

    @router.post("/event-messages/{event_message_id}/cancel", response_model=EventMessageRead)
    async def cancel_event_message(
        event_message_id: uuid.UUID,
        body: EventMessageCancelRequest,
        actor_user_id: ActorUserId,
        principal: Principal,
        db: DbSession,
    ) -> EventMessage:
        tenant_id = principal.principal.tenant_id
        await _require_operator_role(db, actor_user_id=actor_user_id, tenant_id=tenant_id)
        event_message = await _get_or_404(
            db, tenant_id=tenant_id, event_message_id=event_message_id
        )
        try:
            return await service.cancel_event_message(
                db, event_message, row_version=body.row_version, reason=body.reason
            )
        except (VersionConflictError, InvalidTransitionError) as exc:
            raise _handle_service_errors(exc) from exc

    @router.post("/event-messages/{event_message_id}/complete", response_model=EventMessageRead)
    async def complete_event_message(
        event_message_id: uuid.UUID,
        body: EventMessageCompleteRequest,
        actor_user_id: ActorUserId,
        principal: Principal,
        db: DbSession,
    ) -> EventMessage:
        tenant_id = principal.principal.tenant_id
        await _require_operator_role(db, actor_user_id=actor_user_id, tenant_id=tenant_id)
        event_message = await _get_or_404(
            db, tenant_id=tenant_id, event_message_id=event_message_id
        )
        try:
            return await service.complete_event_message(
                db, event_message, row_version=body.row_version
            )
        except (VersionConflictError, InvalidTransitionError) as exc:
            raise _handle_service_errors(exc) from exc

    return router
