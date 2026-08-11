"""Notification API router - GET/POST /me/notifications*, GET/PATCH /me/notification-preferences.

WAVE 2E BACKEND-NOTIFICATION. Model reference: ``app/models/notification.py``. Pipeline
reference: ``app/services/notification/service.py`` (``NotificationService`` +
``SqlAlchemyNotificationRepository``/``InMemoryNotificationRepository``).

Route registration (integrator responsibility, same convention as
``app/api/v1/routers/exhibitor_preference.py``)
-------------------------------------------------------------------------------------------
This file does not register itself on a shared app - it only exposes
``build_notification_router()``. ``app/api/v1/api.py`` must call it and
``include_router(...)`` the result, without an extra prefix (every route below already
spells its full ``/me/...`` path):

    from app.api.v1.routers.notification import build_notification_router
    api_router.include_router(build_notification_router(), tags=["notification"])

Authentication (integration, merge plan STEP 24)
-------------------------------------------------------------------------------------------
The WAVE 2E original read the recipient and the tenant from two client-supplied identity
headers. Both header dependencies are gone, and no header on this router may ever identify
anybody again. Every route depends on ``get_verified_principal`` and derives:

    recipient_user_id = principal.user_id
    tenant_id         = principal.principal.tenant_id

``get_verified_principal`` and NOT ``get_verified_subject``: these are member-only
endpoints. ``get_verified_subject`` also admits an anonymous kiosk ``VerifiedGuest``, which
has no ``user_id`` at all, and ``app/models/notification.py`` is explicit that
``recipient_user_id`` is an ``identity.user`` id and never a guest_session_id. A kiosk guest
therefore has no inbox to read and must be refused at the door (401), not handed someone
else's rows.

Ownership is still enforced where it was: every repository read/write is a WHERE clause on
``(tenant_id, recipient_user_id)`` (``own_notifications_stmt`` / ``own_notification_stmt`` /
``unread_count_stmt`` in ``app/services/notification/service.py``), never a post-filter. A
notification id belonging to another user resolves to "not found" - it can never be read or
marked read, and its existence is not disclosed.

The three mutating routes additionally require ``require_csrf``, matching how the rest of
main protects cookie-session mutations. That also implies a browser session: a service JWT
principal has no session and is refused, which is correct for a personal inbox.

Why the router depends on a ``NotificationService`` factory, not directly on ``db``
-------------------------------------------------------------------------------------------
``get_notification_service`` is itself a FastAPI dependency (not a plain helper) specifically
so tests can override *it* with ``app.dependency_overrides`` and hand the router an
``InMemoryNotificationRepository``-backed service - the same repository/service pair
``app/services/notification/service.py`` already designed to be swappable and DB-free for
tests (see that module's docstring). This avoids needing a hand-rolled fake ``AsyncSession``
that can answer every one of the repository's distinct queries.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.auth import VerifiedPrincipal, get_verified_principal, require_csrf
from app.schemas.notification import (
    MarkAllReadResponse,
    MarkReadResponse,
    NotificationListResponse,
    NotificationPreferenceItem,
    NotificationPreferencesPatchRequest,
    NotificationPreferencesResponse,
    NotificationView,
    UnreadCountResponse,
)
from app.services.notification.service import (
    NotificationService,
    SqlAlchemyNotificationRepository,
    UnknownNotificationTypeError,
)

Principal = Annotated[VerifiedPrincipal, Depends(get_verified_principal)]

#: CSRF gate for the mutating routes. ``require_csrf`` depends on
#: ``require_browser_session``, so it also rejects a non-browser principal.
REQUIRE_CSRF = Depends(require_csrf)


def get_notification_service() -> NotificationService:
    """MERGE STEP 26 fix: ``SqlAlchemyNotificationRepository`` owns its own short-lived
    session per operation (its class docstring) and its ``__init__`` hard-rejects an
    ``AsyncSession`` argument on purpose. The previous body here passed the router's
    request-scoped ``db: AsyncSession = Depends(get_db)`` straight through, which would
    raise ``TypeError`` on every real (non-overridden) call - only test suites that
    override this dependency with an ``InMemoryNotificationRepository``-backed service
    ever exercised the passing path. Omitting the argument lets the repository resolve
    ``app.db.session.get_sessionmaker()`` lazily, exactly as its docstring prescribes.
    """

    return NotificationService(SqlAlchemyNotificationRepository())


def _preferences_response(preferences: dict[str, bool]) -> NotificationPreferencesResponse:
    return NotificationPreferencesResponse(
        items=[
            NotificationPreferenceItem(notification_type=notification_type, email_enabled=enabled)  # type: ignore[arg-type]
            for notification_type, enabled in preferences.items()
        ]
    )


def build_notification_router() -> APIRouter:
    """Builds this track's standalone router. Mounting is the integrator's responsibility."""

    router = APIRouter()

    @router.get("/me/notifications", response_model=NotificationListResponse)
    async def list_my_notifications(
        principal: Principal,
        service: Annotated[NotificationService, Depends(get_notification_service)],
        unread_only: bool = Query(False),
        limit: int = Query(20, ge=1, le=100),
        cursor: str | None = Query(default=None, description="opaque - last created_at ISO8601"),
    ) -> NotificationListResponse:
        before: datetime | None = None
        if cursor:
            try:
                before = datetime.fromisoformat(cursor)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="INVALID_CURSOR") from exc

        records = await service.list_notifications(
            tenant_id=principal.principal.tenant_id,
            recipient_user_id=principal.user_id,
            unread_only=unread_only,
            limit=limit,
            before=before,
        )
        next_cursor = records[-1].created_at.isoformat() if len(records) == limit else None
        return NotificationListResponse(
            items=[NotificationView.model_validate(record) for record in records],
            next_cursor=next_cursor,
        )

    @router.get("/me/notifications/unread-count", response_model=UnreadCountResponse)
    async def get_unread_count(
        principal: Principal,
        service: Annotated[NotificationService, Depends(get_notification_service)],
    ) -> UnreadCountResponse:
        count = await service.unread_count(
            tenant_id=principal.principal.tenant_id,
            recipient_user_id=principal.user_id,
        )
        return UnreadCountResponse(unread_count=count)

    @router.post(
        "/me/notifications/{notification_id}/read",
        response_model=MarkReadResponse,
        dependencies=[REQUIRE_CSRF],
    )
    async def mark_notification_read(
        notification_id: UUID,
        principal: Principal,
        service: Annotated[NotificationService, Depends(get_notification_service)],
    ) -> MarkReadResponse:
        # mark_read only ever queries/updates rows scoped to
        # (tenant_id, recipient_user_id) == the verified principal's own
        # (own_notification_stmt) - a notification_id owned by a different user resolves to
        # None here exactly like "not found", never revealing whether it exists.
        read_at = await service.mark_read(
            tenant_id=principal.principal.tenant_id,
            recipient_user_id=principal.user_id,
            notification_id=notification_id,
        )
        if read_at is None:
            raise HTTPException(status_code=404, detail="NOTIFICATION_NOT_FOUND")
        return MarkReadResponse(notification_id=notification_id, read_at=read_at)

    @router.post(
        "/me/notifications/read-all",
        response_model=MarkAllReadResponse,
        dependencies=[REQUIRE_CSRF],
    )
    async def mark_all_notifications_read(
        principal: Principal,
        service: Annotated[NotificationService, Depends(get_notification_service)],
    ) -> MarkAllReadResponse:
        marked = await service.mark_all_read(
            tenant_id=principal.principal.tenant_id,
            recipient_user_id=principal.user_id,
            now=datetime.now(UTC),
        )
        return MarkAllReadResponse(marked_count=marked)

    @router.get(
        "/me/notification-preferences", response_model=NotificationPreferencesResponse
    )
    async def get_notification_preferences(
        principal: Principal,
        service: Annotated[NotificationService, Depends(get_notification_service)],
    ) -> NotificationPreferencesResponse:
        preferences = await service.get_email_preferences(
            tenant_id=principal.principal.tenant_id, user_id=principal.user_id
        )
        return _preferences_response(preferences)

    @router.patch(
        "/me/notification-preferences",
        response_model=NotificationPreferencesResponse,
        dependencies=[REQUIRE_CSRF],
    )
    async def update_notification_preferences(
        body: NotificationPreferencesPatchRequest,
        principal: Principal,
        service: Annotated[NotificationService, Depends(get_notification_service)],
    ) -> NotificationPreferencesResponse:
        updates = {item.notification_type: item.email_enabled for item in body.items}
        try:
            preferences = await service.update_email_preferences(
                tenant_id=principal.principal.tenant_id,
                user_id=principal.user_id,
                updates=updates,
            )
        except UnknownNotificationTypeError as exc:
            raise HTTPException(
                status_code=422, detail=f"UNKNOWN_NOTIFICATION_TYPE:{exc}"
            ) from exc
        return _preferences_response(preferences)

    return router
