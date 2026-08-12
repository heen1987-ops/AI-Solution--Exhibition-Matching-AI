"""Operator admin API - exhibitor master-approval decision + booth operating-status change.

Track: BACKEND-007 (re-scoped 2026-08-13, see ``.harness/backlog.yaml`` BACKEND-007 note).
Search statistics and no-result-query endpoints were already built by an earlier WAVE2E track
at ``GET /admin/analytics/{searches,no-results,data-quality}``
(``app/api/v1/routers/analytics.py``) - this file does not rebuild or duplicate them. The
genuinely missing scope, per that re-scoping note, is exactly two operator actions:

    POST  /admin/exhibitors/{exhibitor_id}/approve  - master_approval_status -> APPROVED
    POST  /admin/exhibitors/{exhibitor_id}/reject    - master_approval_status -> REJECTED (reason required)
    PATCH /admin/booths/{booth_id}/status            - operating_status (+ congestion/wait), row_version-guarded

Transition rules, concurrency technique, and audit-trail mechanism all live in
``app/services/admin/exhibitor_approval.py`` and ``app/services/admin/booth_status.py`` (see
those modules' docstrings) - this router only does auth, tenant-scoped 404 lookup, and typed
error -> HTTP status mapping.

This module exposes ``build_admin_router()`` (not a bare module-level ``router`` meant for
direct import) so the integrator can mount it without this file touching
``app/api/v1/api.py`` (out of this task's owned scope)::

    from app.api.v1.routers.admin import build_admin_router
    api_router.include_router(build_admin_router(), tags=["admin"])

The router bakes its own ``/admin`` prefix in (matching ``app/api/v1/routers/analytics.py``'s
``prefix="/admin/analytics"`` convention, not ``event_message.py``'s "integrator supplies the
prefix" variant) - the integrator does not need to guess or repeat one.

Authentication and authorization
---------------------------------
``require_roles("EVENT_ADMIN", "DATA_REVIEWER")`` (task's explicit RBAC role list) is a
router-level dependency, so an unauthenticated call fails 401 before any handler body runs, and
an authenticated caller holding neither role fails 403. Both roles are members of
``PRIVILEGED_ADMIN_ROLES`` (``app/core/auth.py``), so every route here additionally demands
AAL2 (fresh MFA) automatically through that same ``require_roles`` call - this router does not
separately request ``fresh_mfa=True`` on top of that, since the task's RBAC section names only
the plain ``require_roles(...)`` call and AAL2 is already the floor for these two roles.

The actor id comes from ``app/core/router_auth.py``'s ``get_actor_user_id`` - derived from a
verified session/JWT principal only, never a client-supplied header. Every resource lookup is
additionally scoped to ``principal.principal.tenant_id`` (the tenant the session was established
against, never a client-supplied value) so an authenticated operator belonging to a different
tenant gets a 404 on someone else's exhibitor/booth, not a cross-tenant mutation.

Public-surface note
--------------------
This file only adds admin-side mutation endpoints; it does not read or modify any public query
path (``app/services/exhibition_public_repository.py`` and friends are untouched), so unapproved
or unpublished exhibitor/booth data cannot leak into a public-facing response as a side effect
of this work.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import VerifiedPrincipal, get_verified_principal, require_roles
from app.core.router_auth import get_actor_user_id
from app.db.session import get_db
from app.models.exhibitor import Booth, Exhibitor
from app.schemas.admin import (
    BoothStatusResponse,
    BoothStatusUpdateRequest,
    ExhibitorApprovalDecisionResponse,
    ExhibitorApproveRequest,
    ExhibitorRejectRequest,
)
from app.services.admin import booth_status, exhibitor_approval

ActorUserId = Annotated[uuid.UUID, Depends(get_actor_user_id)]
Principal = Annotated[VerifiedPrincipal, Depends(get_verified_principal)]
DbSession = Annotated[AsyncSession, Depends(get_db)]

#: Router-level authentication/authorization gate - see the module docstring. Declared once
#: here so no route can be added later without it.
ADMIN_ROLE_DEPENDENCY = Depends(require_roles("EVENT_ADMIN", "DATA_REVIEWER"))

router = APIRouter(prefix="/admin", dependencies=[ADMIN_ROLE_DEPENDENCY])


def build_admin_router() -> APIRouter:
    """Exposed for the integrator - see module docstring."""

    return router


async def _get_exhibitor_or_404(
    db: AsyncSession, *, tenant_id: uuid.UUID, exhibitor_id: uuid.UUID
) -> Exhibitor:
    stmt = select(Exhibitor).where(
        Exhibitor.exhibitor_id == exhibitor_id,
        Exhibitor.tenant_id == tenant_id,
        Exhibitor.deleted_at.is_(None),
    )
    exhibitor = (await db.execute(stmt)).scalar_one_or_none()
    if exhibitor is None:
        raise HTTPException(status_code=404, detail="EXHIBITOR_NOT_FOUND")
    return exhibitor


async def _get_booth_or_404(
    db: AsyncSession, *, tenant_id: uuid.UUID, booth_id: uuid.UUID
) -> Booth:
    stmt = select(Booth).where(Booth.booth_id == booth_id, Booth.tenant_id == tenant_id)
    booth = (await db.execute(stmt)).scalar_one_or_none()
    if booth is None:
        raise HTTPException(status_code=404, detail="BOOTH_NOT_FOUND")
    return booth


def _approval_response(
    exhibitor: Exhibitor, *, previous_status: str, actor_user_id: uuid.UUID
) -> ExhibitorApprovalDecisionResponse:
    return ExhibitorApprovalDecisionResponse(
        exhibitor_id=exhibitor.exhibitor_id,
        previous_status=previous_status,  # type: ignore[arg-type]
        master_approval_status=exhibitor.master_approval_status,  # type: ignore[arg-type]
        decided_by_user_id=actor_user_id,
        decided_at=datetime.now(UTC),
    )


# ---------------------------------------------------------------------------
# POST /admin/exhibitors/{exhibitor_id}/approve
# ---------------------------------------------------------------------------


@router.post(
    "/exhibitors/{exhibitor_id}/approve",
    response_model=ExhibitorApprovalDecisionResponse,
)
async def approve_exhibitor(
    exhibitor_id: uuid.UUID,
    body: ExhibitorApproveRequest,
    actor_user_id: ActorUserId,
    principal: Principal,
    db: DbSession,
) -> ExhibitorApprovalDecisionResponse:
    exhibitor = await _get_exhibitor_or_404(
        db, tenant_id=principal.principal.tenant_id, exhibitor_id=exhibitor_id
    )
    previous_status = exhibitor.master_approval_status
    try:
        updated = await exhibitor_approval.approve_exhibitor(
            db, exhibitor, actor_user_id=actor_user_id, reason_code=body.reason_code
        )
    except exhibitor_approval.InvalidApprovalTransitionError as exc:
        raise HTTPException(
            status_code=409,
            detail=f"EXHIBITOR_APPROVAL_INVALID_TRANSITION:{exc.current_status}",
        ) from exc
    except exhibitor_approval.ApprovalRaceLostError as exc:
        raise HTTPException(
            status_code=409, detail="EXHIBITOR_APPROVAL_VERSION_CONFLICT"
        ) from exc
    await db.commit()
    return _approval_response(updated, previous_status=previous_status, actor_user_id=actor_user_id)


# ---------------------------------------------------------------------------
# POST /admin/exhibitors/{exhibitor_id}/reject
# ---------------------------------------------------------------------------


@router.post(
    "/exhibitors/{exhibitor_id}/reject",
    response_model=ExhibitorApprovalDecisionResponse,
)
async def reject_exhibitor(
    exhibitor_id: uuid.UUID,
    body: ExhibitorRejectRequest,
    actor_user_id: ActorUserId,
    principal: Principal,
    db: DbSession,
) -> ExhibitorApprovalDecisionResponse:
    exhibitor = await _get_exhibitor_or_404(
        db, tenant_id=principal.principal.tenant_id, exhibitor_id=exhibitor_id
    )
    previous_status = exhibitor.master_approval_status
    try:
        updated = await exhibitor_approval.reject_exhibitor(
            db, exhibitor, actor_user_id=actor_user_id, reason_code=body.reason_code
        )
    except exhibitor_approval.InvalidApprovalTransitionError as exc:
        raise HTTPException(
            status_code=409,
            detail=f"EXHIBITOR_APPROVAL_INVALID_TRANSITION:{exc.current_status}",
        ) from exc
    except exhibitor_approval.ApprovalRaceLostError as exc:
        raise HTTPException(
            status_code=409, detail="EXHIBITOR_APPROVAL_VERSION_CONFLICT"
        ) from exc
    await db.commit()
    return _approval_response(updated, previous_status=previous_status, actor_user_id=actor_user_id)


# ---------------------------------------------------------------------------
# PATCH /admin/booths/{booth_id}/status
# ---------------------------------------------------------------------------


@router.patch("/booths/{booth_id}/status", response_model=BoothStatusResponse)
async def patch_booth_status(
    booth_id: uuid.UUID,
    body: BoothStatusUpdateRequest,
    actor_user_id: ActorUserId,
    principal: Principal,
    db: DbSession,
) -> BoothStatusResponse:
    booth = await _get_booth_or_404(
        db, tenant_id=principal.principal.tenant_id, booth_id=booth_id
    )
    try:
        updated = await booth_status.update_booth_status(
            db,
            booth,
            operating_status=body.operating_status,
            congestion_level=body.congestion_level,
            estimated_wait_minutes=body.estimated_wait_minutes,
            expected_row_version=body.row_version,
            actor_user_id=actor_user_id,
            reason_code=body.reason_code,
        )
    except booth_status.BoothVersionConflictError as exc:
        raise HTTPException(status_code=409, detail="BOOTH_VERSION_CONFLICT") from exc
    await db.commit()
    return BoothStatusResponse.model_validate(updated)
