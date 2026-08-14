"""Public web-entry guest session creation (CR-010)."""

from __future__ import annotations

import secrets
from datetime import UTC, date, datetime, timedelta
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import _fail, digest_secret
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.models.common import new_uuid7
from app.models.core import Event
from app.models.identity import GuestSession
from app.models.profile import UserProfile, VisitSession
from app.schemas.profile import Envelope
from app.schemas.session import SessionCreateRequest, SessionCreateResponse

router = APIRouter()
Database = Annotated[AsyncSession, Depends(get_db)]
SessionSettings = Annotated[Settings, Depends(get_settings)]


def _request_id(request: Request) -> str:
    return request.headers.get("X-Request-ID", "unknown")[:100]


def _event_visit_date(event: Event) -> date:
    try:
        local_today = datetime.now(ZoneInfo(event.timezone)).date()
    except ZoneInfoNotFoundError:
        local_today = datetime.now(UTC).date()
    return min(max(local_today, event.start_date), event.end_date)


@router.post(
    "/sessions",
    response_model=Envelope[SessionCreateResponse],
    status_code=status.HTTP_201_CREATED,
    responses={
        404: {"description": "Event not found"},
        409: {"description": "Principal conflict"},
    },
    summary="Create Web Guest Session",
)
async def create_guest_session(
    payload: SessionCreateRequest,
    request: Request,
    response: Response,
    db: Database,
    settings: SessionSettings,
) -> dict[str, object]:
    if request.cookies.get(settings.AUTH_SESSION_COOKIE_NAME):
        raise _fail(
            request,
            409,
            "PRINCIPAL_CONFLICT",
            "An authenticated session cannot create a guest session.",
        )

    event = await db.scalar(select(Event).where(Event.event_id == payload.event_id))
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")

    now = datetime.now(UTC)
    expires_at = now + timedelta(seconds=settings.AUTH_GUEST_SESSION_TTL_SECONDS)
    raw_token = secrets.token_urlsafe(32)
    guest = GuestSession(
        guest_session_id=new_uuid7(),
        tenant_id=event.tenant_id,
        event_id=event.event_id,
        session_token_hmac=digest_secret(
            raw_token, purpose="guest-session", settings=settings
        ),
        entry_channel=payload.entry_channel,
        entry_code=payload.entry_code,
        device_type=payload.device_type,
        language=payload.language,
        expires_at=expires_at,
    )
    profile = UserProfile(
        profile_id=new_uuid7(),
        tenant_id=event.tenant_id,
        event_id=event.event_id,
        user_id=None,
        guest_session_id=guest.guest_session_id,
        user_type="GENERAL_VISITOR",
        profile_status="DRAFT",
        completeness_score=0,
        current_version=1,
        row_version=1,
    )
    visit = VisitSession(
        visit_session_id=new_uuid7(),
        tenant_id=event.tenant_id,
        event_id=event.event_id,
        user_id=None,
        guest_session_id=guest.guest_session_id,
        profile_id=profile.profile_id,
        visit_date=_event_visit_date(event),
        session_status="ACTIVE" if event.event_status == "OPEN" else "PLANNED",
    )
    db.add_all([guest, profile, visit])
    await db.commit()

    response.set_cookie(
        key="__Host-meet_ai_guest",
        value=raw_token,
        max_age=settings.AUTH_GUEST_SESSION_TTL_SECONDS,
        secure=True,
        httponly=True,
        samesite="lax",
        path="/",
    )
    public_status = (
        "OPEN"
        if event.event_status == "OPEN"
        else ("CLOSED" if event.event_status == "CLOSED" else "PAUSED")
    )
    return {
        "success": True,
        "data": SessionCreateResponse(
            guest_session_id=guest.guest_session_id,
            visit_session_id=visit.visit_session_id,
            profile_id=profile.profile_id,
            event_status=public_status,
            service_available=event.event_status == "OPEN",
            minimum_age=settings.SERVICE_MINIMUM_AGE,
            expires_at=expires_at,
        ),
        "meta": {"request_id": _request_id(request), "server_time": now},
    }
