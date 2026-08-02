"""Anonymous kiosk session and signed QR handoff schemas.

There are deliberately no identity, phone, email, profile, or long-lived
preference fields in this contract.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.exhibition_public import PublicBoothDetail
from app.schemas.search import SearchInterpretedQuery, SearchResult

KioskLanguage = Literal["ko", "en", "ja", "zh"]


class KioskTheme(BaseModel):
    logo_url: str = ""
    primary_color: str = "#7A2432"


class KioskFeatureFlags(BaseModel):
    voice_input: bool = False
    map: bool = True
    qr_handoff: bool = True


class KioskConfigResponse(BaseModel):
    kiosk_id: str
    event_id: uuid.UUID
    event_name: str
    default_language: KioskLanguage = "ko"
    supported_languages: list[KioskLanguage]
    zone_id: str | None = None
    session_timeout_seconds: int = Field(ge=60, le=120)
    qr_expiration_minutes: int = Field(ge=1, le=60)
    theme: KioskTheme
    feature_flags: KioskFeatureFlags


class KioskSessionCreateRequest(BaseModel):
    kiosk_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9._-]+$")
    language: KioskLanguage = "ko"


class KioskSessionResponse(BaseModel):
    session_id: uuid.UUID
    event_id: uuid.UUID
    kiosk_id: str
    language: KioskLanguage
    created_at: datetime
    expires_at: datetime
    session_timeout_seconds: int


class KioskSearchRequest(BaseModel):
    query: str = Field(default="", max_length=300)
    category_codes: list[str] = Field(default_factory=list, max_length=8)
    limit: int = Field(default=12, ge=1, le=20)

    @model_validator(mode="after")
    def require_query_or_category(self) -> KioskSearchRequest:
        self.query = " ".join(self.query.split())
        self.category_codes = list(
            dict.fromkeys(code.strip() for code in self.category_codes if code.strip())
        )
        if not self.query and not self.category_codes:
            raise ValueError("query or category_codes is required")
        return self


class KioskSearchResponse(BaseModel):
    search_session_id: uuid.UUID
    interpreted_query: SearchInterpretedQuery
    results: list[SearchResult]
    expires_at: datetime


class KioskHandoffRequest(BaseModel):
    selected_result_ids: list[str] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def deduplicate_selected_results(self) -> KioskHandoffRequest:
        self.selected_result_ids = list(dict.fromkeys(self.selected_result_ids))
        return self


class KioskHandoffResponse(BaseModel):
    handoff_id: uuid.UUID
    token: str
    handoff_url: str
    expires_at: datetime


class KioskHandoffResolveRequest(BaseModel):
    token: str = Field(min_length=20, max_length=4096)


class KioskHandoffResolveResponse(BaseModel):
    handoff_id: uuid.UUID
    event_id: uuid.UUID
    selected_results: list[PublicBoothDetail]
    expires_at: datetime
    claimed_at: datetime


class KioskCloseResponse(BaseModel):
    session_id: uuid.UUID
    closed: Literal[True] = True
