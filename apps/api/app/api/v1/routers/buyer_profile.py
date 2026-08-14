"""Verified-buyer trade profile API - WAVE2C BACKEND-BUYER-PROFILE.

    GET   /me/buyer-profile                 - read (creates an empty UNVERIFIED row on first
                                                access, matching app/api/v1/routers/profile.py's
                                                "GET /profiles/me" idiom)
    PATCH /me/buyer-profile                  - partial update, optimistic-locked by ``version``
    GET   /buyer-profile/{buyer_profile_id}  - lookup by id, ownership-enforced (403 for another
                                                user's profile) - see "Why a by-id endpoint" below

See ``app/models/buyer_profile.py``'s module docstring for the full design rationale (why this
is a new table distinct from ``profile.buyer_need``, why it's scoped to (tenant_id, user_id)
rather than per-event, why the ontology-code fields are normalized).

Authentication (merge STEP 21)
--------------------------------
The original WAVE2C file read the acting subject straight off ``X-Tenant-Id``/``X-User-Id``
request headers (``_tenant_header``/``_user_header``). Those helpers are gone. The subject is
now derived exclusively from a verified session or service JWT via
``app.core.auth.get_verified_principal``.

``get_verified_principal`` - not ``get_verified_subject`` - is deliberate: a verified-buyer
trade profile is keyed to an authenticated ``profile.user_account``, and ``VerifiedGuest`` has
no ``user_id`` at all (PROJECT_SCOPE's kiosk exclusions mean an anonymous kiosk visitor must
never be able to own one).

``X-Tenant-Id``/``X-User-Id`` survive only as an optional *cross-check*: if a legacy site
adapter still sends them and they disagree with the server-derived principal, the request is
rejected with 403 RESOURCE_FORBIDDEN rather than silently trusted. This mirrors
``app/api/v1/routers/recommendations.py``'s ``resolve_subject_context`` (lines 269-278).

The by-id ownership check below compares the stored profile against the *principal-derived*
tenant/user, so it can no longer be satisfied by editing a request header.

Why a by-id endpoint
----------------------
The task spec only names ``/me/buyer-profile``, but its own acceptance test list requires
"cross-user 403" coverage, which is unobservable through a "me"-only endpoint (a caller can never
address another user's profile through it to begin with - there is nothing to reject). Exposing
``GET /buyer-profile/{id}`` with an explicit ownership check gives that scenario something to
actually test, and doubles as the lookup other tracks (e.g. BACKEND-MEETING showing buyer context
to an exhibitor) will eventually need. It intentionally does not expose a partner/staff-facing
"read someone else's profile" variant - that is a distinct, larger review-surface decision
(what fields are safe to reveal to an exhibitor) left to whichever track needs it.

Response envelope
--------------------
Builds ``{"success": bool, "data"/"error": ..., "meta": ...}`` JSON responses locally
(``_ok``/``_fail`` below) rather than depending on a shared exception handler registered in
``app/main.py`` - other routers in this repo (``app/api/v1/routers/meetings.py``) follow the
same self-contained pattern.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import VerifiedPrincipal, get_verified_principal
from app.db.session import get_db
from app.models.buyer_profile import BUYER_PROFILE_CODE_GROUPS, BuyerProfile
from app.schemas.buyer_profile import BuyerProfilePatchRequest, BuyerProfileView
from app.services.buyer_profile import service
from app.services.buyer_profile.errors import (
    UnknownOntologyCodeError,
    VersionConflictError,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Response envelope (module docstring "Response envelope")
# ---------------------------------------------------------------------------


def _meta(request_id: str | None) -> dict[str, str]:
    return {
        "request_id": request_id or f"req_{uuid.uuid4().hex}",
        "server_time": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def _ok(data: Any, *, request_id: str | None, status_code: int = 200) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"success": True, "data": jsonable_encoder(data), "meta": _meta(request_id)},
    )


def _fail(
    status_code: int,
    code: str,
    message: str,
    *,
    field_errors: list[dict[str, str]] | None = None,
    retryable: bool = False,
    request_id: str | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "success": False,
            "error": {
                "code": code,
                "message": message,
                "field_errors": field_errors or [],
                "retryable": retryable,
            },
            "meta": _meta(request_id),
        },
    )


# ---------------------------------------------------------------------------
# Subject resolution (module docstring "Authentication")
# ---------------------------------------------------------------------------


class BuyerSubject:
    """The (tenant_id, user_id) pair this request may act as, derived from the principal."""

    __slots__ = ("tenant_id", "user_id")

    def __init__(self, tenant_id: uuid.UUID, user_id: uuid.UUID) -> None:
        self.tenant_id = tenant_id
        self.user_id = user_id


async def resolve_buyer_subject(
    principal: Annotated[VerifiedPrincipal, Depends(get_verified_principal)],
    x_tenant_id: Annotated[uuid.UUID | None, Header(alias="X-Tenant-Id")] = None,
    x_user_id: Annotated[uuid.UUID | None, Header(alias="X-User-Id")] = None,
) -> BuyerSubject | None:
    """Derive the acting buyer from the verified principal only.

    Any ``X-Tenant-Id``/``X-User-Id`` a legacy site adapter still sends is treated as a
    claim to be *checked*, never as identity: on mismatch this returns ``None`` and every
    handler answers 403 RESOURCE_FORBIDDEN in this router's own envelope shape (same
    discipline as recommendations.py's ``resolve_subject_context``, expressed without an
    app-level exception handler so the router stays self-contained).

    An unauthenticated caller never reaches this function at all -
    ``get_verified_principal`` already raises 401 AUTH_REQUIRED.
    """

    tenant_id = principal.principal.tenant_id
    user_id = principal.user_id
    for supplied, expected in ((x_tenant_id, tenant_id), (x_user_id, user_id)):
        if supplied is not None and supplied != expected:
            return None
    return BuyerSubject(tenant_id, user_id)


def _forbidden_context(request_id: str | None) -> JSONResponse:
    return _fail(
        403,
        "RESOURCE_FORBIDDEN",
        "서버 세션 경계와 요청 컨텍스트가 다릅니다.",
        request_id=request_id,
    )


# ---------------------------------------------------------------------------
# View assembly
# ---------------------------------------------------------------------------


def _codes_for_group(profile: BuyerProfile, group: str) -> list[str]:
    assert group in BUYER_PROFILE_CODE_GROUPS  # pragma: no cover - defensive, dev-time only
    return [row.attribute_code for row in profile.codes if row.code_group == group]


def _to_view(profile: BuyerProfile) -> BuyerProfileView:
    return BuyerProfileView(
        buyer_profile_id=profile.buyer_profile_id,
        buyer_type=profile.buyer_type,
        industry_codes=_codes_for_group(profile, "INDUSTRY"),
        interest_codes=_codes_for_group(profile, "INTEREST"),
        channel_codes=_codes_for_group(profile, "CHANNEL"),
        preferred_region_codes=_codes_for_group(profile, "PREFERRED_REGION"),
        cooperation_codes=_codes_for_group(profile, "COOPERATION"),
        order_scale_code=profile.order_scale_code,
        decision_timeline=profile.decision_timeline,
        verification_status=profile.verification_status,
        version=profile.version,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/me/buyer-profile")
async def get_my_buyer_profile(
    db: AsyncSession = Depends(get_db),
    subject: BuyerSubject | None = Depends(resolve_buyer_subject),
    x_request_id: Annotated[str | None, Header(alias="X-Request-ID")] = None,
) -> JSONResponse:
    if subject is None:
        return _forbidden_context(x_request_id)

    profile = await service.get_or_create_buyer_profile(
        db, tenant_id=subject.tenant_id, user_id=subject.user_id
    )
    await db.commit()
    return _ok(_to_view(profile), request_id=x_request_id)


@router.patch("/me/buyer-profile")
async def patch_my_buyer_profile(
    payload: BuyerProfilePatchRequest,
    db: AsyncSession = Depends(get_db),
    subject: BuyerSubject | None = Depends(resolve_buyer_subject),
    x_request_id: Annotated[str | None, Header(alias="X-Request-ID")] = None,
) -> JSONResponse:
    if subject is None:
        return _forbidden_context(x_request_id)

    profile = await service.get_or_create_buyer_profile(
        db, tenant_id=subject.tenant_id, user_id=subject.user_id
    )

    try:
        profile = await service.apply_patch(db, profile, payload)
    except VersionConflictError:
        await db.rollback()
        return _fail(
            409,
            "BUYER_PROFILE_VERSION_CONFLICT",
            "바이어 프로파일이 이미 다른 요청으로 변경되었습니다. 최신 값을 다시 조회해 주세요.",
            retryable=True,
            request_id=x_request_id,
        )
    except UnknownOntologyCodeError as error:
        await db.rollback()
        return _fail(
            422,
            "VALIDATION_FAILED",
            f"알 수 없는 온톨로지 코드입니다: {error.code}",
            field_errors=[{"field": error.field, "reason": "unknown_ontology_code"}],
            request_id=x_request_id,
        )

    await db.commit()
    return _ok(_to_view(profile), request_id=x_request_id)


@router.get("/buyer-profile/{buyer_profile_id}")
async def get_buyer_profile_by_id(
    buyer_profile_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    subject: BuyerSubject | None = Depends(resolve_buyer_subject),
    x_request_id: Annotated[str | None, Header(alias="X-Request-ID")] = None,
) -> JSONResponse:
    """See module docstring "Why a by-id endpoint" - ownership-enforced, no operator override.

    The comparison is against the principal-derived subject (merge STEP 21). Before the
    merge it compared the row against the very ``X-Tenant-Id``/``X-User-Id`` headers the
    caller supplied, which made it tautologically satisfiable.
    """

    if subject is None:
        return _forbidden_context(x_request_id)

    profile = await service.get_buyer_profile_by_id(db, buyer_profile_id)
    if (
        profile is None
        or profile.tenant_id != subject.tenant_id
        or profile.user_id != subject.user_id
    ):
        # 존재 여부를 노출하지 않기 위해 404 대신 403으로 통일한다
        # (app/api/v1/routers/recommendations.py의 동일한 선례를 따른다).
        return _fail(
            403,
            "RESOURCE_FORBIDDEN",
            "본인 소유의 바이어 프로파일만 조회할 수 있습니다.",
            request_id=x_request_id,
        )

    return _ok(_to_view(profile), request_id=x_request_id)


def build_buyer_profile_router() -> APIRouter:
    """Integration point for this track's owned worker prompt.

    The integrator wires this in without a prefix (all routes already spell out their full
    ``/api/v1``-relative path)::

        from app.api.v1.routers.buyer_profile import build_buyer_profile_router
        api_router.include_router(build_buyer_profile_router(), tags=["buyer-profile"])

    The owning app must also register ``app.core.auth.auth_exception_handler`` for
    ``AuthException`` (``app/main.py`` already does) so that an unauthenticated call to any
    of these routes renders as 401 AUTH_REQUIRED rather than a 500.
    """

    return router
