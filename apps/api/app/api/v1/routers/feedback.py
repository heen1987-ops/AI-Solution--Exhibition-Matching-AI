"""Visit feedback API router - POST /feedback (BACKEND-017).

Wire contract: docs/frontend-backend-ai-interface-spec.md §13.2 "피드백". Request/response
shapes match ``apps/user-web/lib/types.ts``'s ``FeedbackRequest``/``FeedbackResponse`` exactly -
see ``app/schemas/feedback.py`` for the field-by-field cross-reference and
``apps/user-web/app/visits/[visitId]/feedback/page.tsx`` for the screen that already calls this
route (via ``postFeedback()`` in ``apps/user-web/lib/api-client.ts``).

Model reference: ``app/models/feedback.py`` (read its module docstring first - it documents the
scope judgment call this task made, mirroring BACKEND-016's checkin.py precedent: BACKEND-017's
``owned_paths`` list only router+schema files, so this task also publishes the model +
migration since nothing else owns it). Service layer: ``app/services/feedback``
(``submit_feedback`` does the full orchestration - visit-session resolution, target resolution,
comment encryption, and Idempotency-Key replay; read that module's docstring for the design
rationale behind each step, and for why it reuses checkin.py's/favorites.py's own helpers rather
than reinventing them).

Route registration (integrator responsibility, same convention as
``app/api/v1/routers/notification.py`` / ``favorites.py`` / ``checkin.py``)
--------------------------------------------------------------------------------------------
This file does not register itself on a shared app - it only exposes ``build_feedback_router()``.
``app/api/v1/api.py`` must call it and ``include_router(...)`` the result, without an extra
prefix (the route below already spells its full ``/feedback`` path):

    from app.api.v1.routers.feedback import build_feedback_router
    api_router.include_router(build_feedback_router(), tags=["feedback"])

Authentication - authenticated users AND anonymous guests
--------------------------------------------------------------------------------------------
Exactly ``checkin.py``'s/``favorites.py``'s precedent: this endpoint is used by
REGISTERED_WEB and GUEST_WEB visitors mid-visit, so it depends on
``app.api.v1.routers.profile.get_current_subject`` - the anonymous-or-authenticated
``CurrentSubject`` dependency - not the heavier signed-site-context flow other routers use for
external site-adapter traffic. No caller-supplied identity header is ever trusted; the active
visit_session is resolved server-side from the verified subject.

No CSRF gate, same precedent as favorites.py/checkin.py: ``app/core/auth.py::require_csrf`` has
no guest branch, which would make this endpoint unreachable for the guest owners it must
support.

Error responses use ``profile.py::api_error``'s envelope shape, not a bare string detail
--------------------------------------------------------------------------------------------
Same convention checkin.py established (unlike favorites.py's bare ``HTTPException(detail=
"STRING")``): every error uses ``app/api/v1/routers/profile.py::api_error`` so the response
body's ``detail`` is ``{"code": ..., "message": ..., "field_errors": [], "retryable": ...,
"retry_after_seconds": ...}``.

Always 201 on success - no ``duplicate`` flag to reconstruct
--------------------------------------------------------------------------------------------
Unlike ``CheckInResponse.duplicate`` (which the check-in screen branches on),
``FeedbackResponse`` (``apps/user-web/lib/types.ts``) has only ``feedback_id``/``recorded_at`` -
no field exists for the frontend to read a duplicate/replay signal from. This router therefore
always returns 201, whether ``submit_feedback`` inserted a new row or replayed a prior
Idempotency-Key/``client_event_id`` match - see ``app/services/feedback/service.py``'s
``SubmittedFeedback.replayed`` for where that information is still available server-side, e.g.
for future observability, even though this router does not surface it today.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.routers.profile import CurrentSubject, api_error, get_current_subject
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.models.feedback import Feedback
from app.schemas.feedback import FeedbackRequest, FeedbackResponse
from app.services.feedback import (
    FeedbackTargetNotFoundError,
    VisitSessionNotFoundError,
    submit_feedback,
)

Subject = Annotated[CurrentSubject, Depends(get_current_subject)]
DbSession = Annotated[AsyncSession, Depends(get_db)]
FeedbackSettings = Annotated[Settings, Depends(get_settings)]


def _to_response(feedback: Feedback) -> FeedbackResponse:
    return FeedbackResponse(
        feedback_id=feedback.feedback_id,
        recorded_at=feedback.created_at,
    )


def build_feedback_router() -> APIRouter:
    """Builds this track's standalone router. Mounting is the integrator's responsibility."""

    router = APIRouter()

    @router.post("/feedback", response_model=FeedbackResponse, status_code=201)
    async def create_feedback(
        body: FeedbackRequest,
        subject: Subject,
        db: DbSession,
        settings: FeedbackSettings,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> FeedbackResponse:
        now = datetime.now(UTC)
        try:
            submitted = await submit_feedback(
                db,
                tenant_id=subject.tenant_id,
                event_id=subject.event_id,
                user_id=subject.user_id,
                guest_session_id=subject.guest_session_id,
                object_type=body.object_type,
                object_id=body.object_id,
                match_result_id=body.match_result_id,
                rating=body.rating,
                positive_reasons=list(body.positive_reasons),
                negative_reasons=list(body.negative_reasons),
                comment=body.comment,
                client_event_id=body.client_event_id,
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
        except FeedbackTargetNotFoundError as exc:
            raise api_error(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "FEEDBACK_TARGET_NOT_FOUND",
                "피드백 대상을 찾을 수 없습니다.",
            ) from exc

        return _to_response(submitted.feedback)

    return router
