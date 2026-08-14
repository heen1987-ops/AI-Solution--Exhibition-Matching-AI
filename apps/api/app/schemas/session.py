"""CR-010 public web guest-session entry schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SessionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    entry_channel: Literal["QR", "WEB"]
    entry_code: str | None = Field(default=None, max_length=100)
    device_type: Literal["MOBILE_WEB", "DESKTOP_WEB"] | None = None
    language: str = Field(
        default="ko-KR",
        min_length=2,
        max_length=10,
        pattern=r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})?$",
    )


class SessionCreateResponse(BaseModel):
    guest_session_id: UUID
    visit_session_id: UUID
    profile_id: UUID
    event_status: Literal["OPEN", "PAUSED", "CLOSED"]
    service_available: bool
    minimum_age: int = Field(ge=0, le=120)
    expires_at: datetime
