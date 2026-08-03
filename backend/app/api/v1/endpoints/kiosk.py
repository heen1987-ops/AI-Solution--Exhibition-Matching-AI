"""Kiosk anonymous session and QR handoff endpoints."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.errors import api_error
from app.db.session import get_db

router = APIRouter()

DEFAULT_KIOSK_IDLE_TIMEOUT_SECONDS = 90
KIOSK_ENTRY_CHANNEL = "KIOSK"
KIOSK_DEVICE_TYPE = "KIOSK"


class StartKioskSessionRequest(BaseModel):
    kiosk_device_id: uuid.UUID
    language: str = Field(default="ko-KR", min_length=2, max_length=10)


class KioskSessionResponse(BaseModel):
    guest_session_id: uuid.UUID
    expires_at: datetime


class CreateQrHandoffRequest(BaseModel):
    guest_session_id: uuid.UUID


class QrHandoffResponse(BaseModel):
    entry_code: str
    expires_at: datetime


def _new_session_hmac() -> bytes:
    return hashlib.sha256(secrets.token_bytes(32)).digest()


def _new_entry_code() -> str:
    # URL-safe enough to embed directly in a QR payload; no personal data included.
    return secrets.token_urlsafe(32)


def _now() -> datetime:
    return datetime.now(UTC)


async def _active_kiosk_device(db: AsyncSession, kiosk_device_id: uuid.UUID):
    from app.models.kiosk import KioskDevice

    device = await db.get(KioskDevice, kiosk_device_id)
    if device is None or device.device_status != "ACTIVE":
        raise api_error(
            "RESOURCE_NOT_FOUND",
            "요청한 대상을 찾을 수 없습니다.",
            status_code=404,
            details={"resource": "kiosk_device"},
        )
    return device


async def _idle_timeout_seconds(
    db: AsyncSession, kiosk_device_id: uuid.UUID
) -> int:
    from app.models.kiosk import KioskConfig

    config = await db.scalar(
        select(KioskConfig)
        .where(KioskConfig.kiosk_device_id == kiosk_device_id)
        .limit(1)
    )
    if config is None:
        return DEFAULT_KIOSK_IDLE_TIMEOUT_SECONDS
    return config.idle_timeout_seconds


@router.post(
    "/sessions",
    response_model=KioskSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def start_kiosk_session(
    payload: StartKioskSessionRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> KioskSessionResponse:
    from app.models.identity import GuestSession

    device = await _active_kiosk_device(db, payload.kiosk_device_id)
    timeout_seconds = await _idle_timeout_seconds(db, payload.kiosk_device_id)
    expires_at = _now() + timedelta(seconds=timeout_seconds)

    guest_session = GuestSession(
        tenant_id=device.tenant_id,
        event_id=device.event_id,
        session_token_hmac=_new_session_hmac(),
        entry_channel=KIOSK_ENTRY_CHANNEL,
        device_type=KIOSK_DEVICE_TYPE,
        language=payload.language,
        expires_at=expires_at,
    )
    db.add(guest_session)
    await db.commit()
    await db.refresh(guest_session)

    return KioskSessionResponse(
        guest_session_id=guest_session.guest_session_id,
        expires_at=guest_session.expires_at,
    )


@router.delete(
    "/sessions/{guest_session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def end_kiosk_session(
    guest_session_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    from app.models.identity import GuestSession

    guest_session = await db.get(GuestSession, guest_session_id)
    if guest_session is not None:
        guest_session.expires_at = _now()
        guest_session.entry_code = None
        await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/qr-sessions",
    response_model=QrHandoffResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_qr_handoff(
    payload: CreateQrHandoffRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> QrHandoffResponse:
    from app.models.identity import GuestSession

    guest_session = await db.get(GuestSession, payload.guest_session_id)
    now = _now()
    if (
        guest_session is None
        or guest_session.entry_channel != KIOSK_ENTRY_CHANNEL
        or guest_session.expires_at <= now
    ):
        raise api_error(
            "QR_HANDOFF_EXPIRED",
            "QR 인계 세션이 만료되었습니다.",
            status_code=410,
            details={"resource": "guest_session"},
        )

    guest_session.entry_code = _new_entry_code()
    await db.commit()
    await db.refresh(guest_session)

    return QrHandoffResponse(
        entry_code=guest_session.entry_code,
        expires_at=guest_session.expires_at,
    )
