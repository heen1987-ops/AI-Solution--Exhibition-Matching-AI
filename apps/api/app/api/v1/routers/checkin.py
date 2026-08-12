"""QR check-in API router - POST /check-ins (BACKEND-016).

Wire contract: docs/frontend-backend-ai-interface-spec.md §13.1 "체크인". Response/request
shapes match ``apps/user-web/lib/types.ts``'s ``CheckInRequest``/``CheckInResponse`` exactly -
see ``app/schemas/checkin.py`` for the field-by-field cross-reference and
``apps/user-web/app/check-in/[qrToken]/page.tsx`` for the screen that already calls this route.

Model reference: ``app/models/checkin.py`` (read its module docstring first - it documents the
scope judgment call this task made: BACKEND-016's ``owned_paths`` list only router+schema
files, unlike CONTRACT-005/BACKEND-009's split, so this task also publishes the model +
migration since nothing else owns it). Service layer: ``app/services/checkin``
(``submit_check_in`` does the full orchestration - QR verification, active visit-session
resolution, the 5-minute advisory-lock dedupe window, and Idempotency-Key replay; read that
module's docstring for the design rationale behind each step before touching this file).

Route registration (integrator responsibility, same convention as
``app/api/v1/routers/notification.py`` / ``favorites.py``)
--------------------------------------------------------------------------------------------
This file does not register itself on a shared app - it only exposes ``build_checkin_router()``.
``app/api/v1/api.py`` must call it and ``include_router(...)`` the result, without an extra
prefix (the route below already spells its full ``/check-ins`` path):

    from app.api.v1.routers.checkin import build_checkin_router
    api_router.include_router(build_checkin_router(), tags=["checkin"])

Authentication - authenticated users AND anonymous guests
--------------------------------------------------------------------------------------------
Exactly ``favorites.py``'s precedent: this endpoint is used by REGISTERED_WEB and GUEST_WEB
visitors mid-visit (not kiosk/staff), so it depends on
``app.api.v1.routers.profile.get_current_subject`` - the anonymous-or-authenticated
``CurrentSubject`` dependency, not the heavier signed-site-context ``resolve_subject_context``
flow ``recommendations.py``/``conversation.py`` use for external site-adapter traffic. No
caller-supplied identity header is ever trusted; the active visit_session is resolved
server-side from the verified subject (see the service module's docstring for why - this
endpoint has no ``X-Visit-Session-Id`` header at all).

No CSRF gate, same precedent as favorites.py: ``app/core/auth.py::require_csrf`` has no guest
branch, which would make this endpoint unreachable for the guest owners it must support.

Error responses use ``profile.py::api_error``'s envelope shape, not a bare string detail
--------------------------------------------------------------------------------------------
Unlike ``favorites.py`` (which uses a bare ``HTTPException(detail="STRING")``),
this router uses ``app/api/v1/routers/profile.py::api_error`` for every error so the response
body's ``detail`` is ``{"code": ..., "message": ..., "field_errors": [], "retryable": ...,
"retry_after_seconds": ...}``. This is not a style preference: the frontend's
``extractErrorBody`` (``apps/user-web/lib/api-client.ts``) only reads ``err.code`` out of a
*structured* `detail` object - a bare string detail always surfaces as ``code: "UNKNOWN_ERROR"``
regardless of its text. The check-in screen explicitly branches on
``err.code === "INVALID_QR"`` (see that screen's ``handleSubmit``), so ``INVALID_QR`` must be
the literal ``code`` field, not embedded in a message string.

Status codes: 201 for a newly-created check-in, 200 for a duplicate
--------------------------------------------------------------------------------------------
``CheckInResponse.duplicate`` already carries the duplicate signal the frontend reads, but the
HTTP status still differs (201 vs 200) as a second, standard-REST-compatible signal for any
caller that only inspects the status code - this also lets Idempotency-Key replay reconstruct
which one the original request got, without adding a new database column (see the service
module's ``response_status`` reuse note).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.routers.profile import CurrentSubject, api_error, get_current_subject
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.models.checkin import CheckIn
from app.schemas.checkin import CheckInRequest, CheckInResponse
from app.services.checkin import (
    BoothClosedError,
    InvalidQrError,
    VisitSessionNotFoundError,
    submit_check_in,
)

Subject = Annotated[CurrentSubject, Depends(get_current_subject)]
DbSession = Annotated[AsyncSession, Depends(get_db)]
CheckinSettings = Annotated[Settings, Depends(get_settings)]


def _to_response(check_in: CheckIn, *, duplicate: bool) -> CheckInResponse:
    return CheckInResponse(
        check_in_id=check_in.check_in_id,
        booth_id=check_in.booth_id,
        checked_in_at=check_in.checked_in_at,
        activities=list(check_in.activities),
        duplicate=duplicate,
    )


def build_checkin_router() -> APIRouter:
    """Builds this track's standalone router. Mounting is the integrator's responsibility."""

    router = APIRouter()

    @router.post("/check-ins", response_model=CheckInResponse)
    async def create_check_in(
        body: CheckInRequest,
        subject: Subject,
        db: DbSession,
        settings: CheckinSettings,
        response: Response,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> CheckInResponse:
        now = datetime.now(UTC)
        try:
            check_in, duplicate = await submit_check_in(
                db,
                tenant_id=subject.tenant_id,
                event_id=subject.event_id,
                user_id=subject.user_id,
                guest_session_id=subject.guest_session_id,
                qr_token=body.qr_token,
                activities=body.activities,
                match_result_id=body.match_result_id,
                client_event_id=body.client_event_id,
                occurred_at=body.occurred_at,
                idempotency_key=idempotency_key,
                settings=settings,
                now=now,
            )
        except VisitSessionNotFoundError as exc:
            raise api_error(
                status.HTTP_404_NOT_FOUND,
                "VISIT_SESSION_NOT_FOUND",
                "진행 중인 방문 세션을 찾을 수 없습니다.",
            ) from exc
        except InvalidQrError as exc:
            raise api_error(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "INVALID_QR",
                "QR 코드가 만료되었거나 유효하지 않습니다.",
            ) from exc
        except BoothClosedError as exc:
            raise api_error(
                status.HTTP_409_CONFLICT,
                "BOOTH_CLOSED",
                "현재 운영 중이 아닌 부스입니다.",
            ) from exc

        response.status_code = (
            status.HTTP_200_OK if duplicate else status.HTTP_201_CREATED
        )
        return _to_response(check_in, duplicate=duplicate)

    return router
