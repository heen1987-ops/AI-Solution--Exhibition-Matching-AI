"""Favorites API router - GET/POST /me/favorites, DELETE /me/favorites/{favorite_id}.

BACKEND-009. Model reference: ``app/models/favorite.py`` (read its module docstring first -
it is the source of truth for the ownership/dedup/soft-delete contract this router honors).
Service layer: ``app/services/favorite`` (``resolve_recommendable_id`` / ``create_favorite`` /
``list_favorites`` / ``soft_delete_favorite``).

Route path (backlog note, 2026-08-13)
--------------------------------------------------------------------------------------------
``.harness/backlog.yaml``'s BACKEND-009 entry confirms the contract path is ``/me/favorites``
(USERWEB-005's audit). ``apps/user-web/lib/api-client.ts`` currently calls ``/favorites``
(missing the ``/me`` prefix) - that is a frontend bug, out of this task's owned_paths
(apps/api only). This router intentionally does NOT bend to match it; fixing the frontend
client is a separate follow-up.

Route registration (integrator responsibility, same convention as
``app/api/v1/routers/notification.py``)
--------------------------------------------------------------------------------------------
This file does not register itself on a shared app - it only exposes
``build_favorites_router()``. ``app/api/v1/api.py`` must call it and ``include_router(...)``
the result, without an extra prefix (every route below already spells its full ``/me/...``
path):

    from app.api.v1.routers.favorites import build_favorites_router
    api_router.include_router(build_favorites_router(), tags=["favorites"])

Authentication - authenticated users AND anonymous guests
--------------------------------------------------------------------------------------------
Unlike ``notification.py`` (member-only, ``get_verified_principal`` only),
``app/models/favorite.py``'s ``subject_exactly_one`` CHECK explicitly allows a
``guest_session_id`` owner. This router therefore depends on
``app.api.v1.routers.profile.get_current_subject`` - the anonymous-or-authenticated
``CurrentSubject`` (tenant_id, event_id, user_id | guest_session_id) dependency
``app/api/v1/routers/profile.py`` already built and ``consent.py`` already reuses across
routers (see that dependency's own module comment for why this repo's convention is to reuse
it rather than invent a second one). No caller-supplied identity header is ever trusted.

No CSRF gate on the mutating routes: ``app/core/auth.py::require_csrf`` depends on
``require_browser_session`` -> ``get_verified_principal``, which has no guest branch at all -
using it here would make POST/DELETE unreachable for the guest owners this table is required
to support. ``profile.py``'s own guest-and-auth mutating routes (``PUT /profiles/me/goals`` and
siblings) establish the same precedent: no CSRF gate on a ``get_current_subject``-scoped
mutation in this codebase yet. This router follows that precedent rather than inventing a
hybrid scheme.

Ownership enforcement
--------------------------------------------------------------------------------------------
Every read/write is a WHERE clause on ``(tenant_id, event_id, user_id OR guest_session_id)``
(``active_favorite_for_target_stmt`` / ``own_favorite_stmt`` / ``list_favorites_stmt`` in
``app/services/favorite/service.py``), never a post-filter. A ``favorite_id`` belonging to a
different owner resolves to 404 ``FAVORITE_NOT_FOUND`` - the same "not found, not forbidden"
convention ``notification.py``'s ``mark_notification_read`` already established for a personal,
owner-scoped resource in this repo (its existence is not disclosed to a non-owner).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.routers.profile import CurrentSubject, get_current_subject
from app.db.session import get_db
from app.schemas.favorite import (
    FavoriteCreateRequest,
    FavoriteListResponse,
    FavoriteRead,
)
from app.services.favorite import (
    FavoriteWithTarget,
    InvalidMatchResultError,
    create_favorite,
    list_favorites,
    resolve_recommendable_id,
    soft_delete_favorite,
)

Subject = Annotated[CurrentSubject, Depends(get_current_subject)]
DbSession = Annotated[AsyncSession, Depends(get_db)]

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


def _to_read(item: FavoriteWithTarget) -> FavoriteRead:
    favorite = item.favorite
    return FavoriteRead(
        favorite_id=favorite.favorite_id,
        object_type=item.object_type,
        object_id=item.object_id,
        source=favorite.source,  # type: ignore[arg-type]
        match_result_id=favorite.match_result_id,
        created_at=favorite.created_at,
    )


def build_favorites_router() -> APIRouter:
    """Builds this track's standalone router. Mounting is the integrator's responsibility."""

    router = APIRouter()

    @router.post("/me/favorites", response_model=FavoriteRead, status_code=201)
    async def add_favorite(
        body: FavoriteCreateRequest,
        subject: Subject,
        db: DbSession,
    ) -> FavoriteRead:
        recommendable_id = await resolve_recommendable_id(
            db,
            tenant_id=subject.tenant_id,
            event_id=subject.event_id,
            object_type=body.object_type,
            object_id=body.object_id,
        )
        if recommendable_id is None:
            raise HTTPException(status_code=422, detail="FAVORITE_TARGET_NOT_FOUND")

        try:
            favorite, _created = await create_favorite(
                db,
                tenant_id=subject.tenant_id,
                event_id=subject.event_id,
                user_id=subject.user_id,
                guest_session_id=subject.guest_session_id,
                recommendable_id=recommendable_id,
                source=body.source,
                match_result_id=body.match_result_id,
            )
        except InvalidMatchResultError as exc:
            raise HTTPException(
                status_code=422, detail="INVALID_MATCH_RESULT_ID"
            ) from exc

        return _to_read(
            FavoriteWithTarget(
                favorite=favorite, object_type=body.object_type, object_id=body.object_id
            )
        )

    @router.get("/me/favorites", response_model=FavoriteListResponse)
    async def list_my_favorites(
        subject: Subject,
        db: DbSession,
        limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
        cursor: str | None = Query(
            default=None,
            description="opaque - last created_at ISO8601, '|', last favorite_id",
        ),
    ) -> FavoriteListResponse:
        before: datetime | None = None
        before_favorite_id: UUID | None = None
        if cursor:
            # '|'-tie-broken form (current) or a bare timestamp (older clients / cached links) -
            # the bare form still works, just without the tie-break guarantee for that one page.
            raw_timestamp, _, raw_favorite_id = cursor.partition("|")
            try:
                before = datetime.fromisoformat(raw_timestamp)
                if raw_favorite_id:
                    before_favorite_id = UUID(raw_favorite_id)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="INVALID_CURSOR") from exc

        items = await list_favorites(
            db,
            tenant_id=subject.tenant_id,
            event_id=subject.event_id,
            user_id=subject.user_id,
            guest_session_id=subject.guest_session_id,
            limit=limit,
            before=before,
            before_favorite_id=before_favorite_id,
        )
        next_cursor = (
            f"{items[-1].favorite.created_at.isoformat()}|{items[-1].favorite.favorite_id}"
            if len(items) == limit
            else None
        )
        return FavoriteListResponse(
            items=[_to_read(item) for item in items], next_cursor=next_cursor
        )

    @router.delete("/me/favorites/{favorite_id}", status_code=204)
    async def remove_favorite(
        favorite_id: UUID,
        subject: Subject,
        db: DbSession,
    ) -> None:
        deleted = await soft_delete_favorite(
            db,
            tenant_id=subject.tenant_id,
            event_id=subject.event_id,
            user_id=subject.user_id,
            guest_session_id=subject.guest_session_id,
            favorite_id=favorite_id,
            now=datetime.now(UTC),
        )
        if not deleted:
            raise HTTPException(status_code=404, detail="FAVORITE_NOT_FOUND")

    return router
