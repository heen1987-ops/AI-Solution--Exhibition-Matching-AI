"""Public exhibitor, booth, map, and anonymous search API schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

SearchChannel = Literal["WEB", "KIOSK"]


class SearchRequest(BaseModel):
    event_id: uuid.UUID
    query: str = Field(default="", max_length=300)
    category_codes: list[str] = Field(default_factory=list, max_length=8)
    channel: SearchChannel = "WEB"
    limit: int = Field(default=12, ge=1, le=20)

    @model_validator(mode="after")
    def normalize_and_validate(self) -> SearchRequest:
        self.query = " ".join(self.query.split())
        self.category_codes = list(
            dict.fromkeys(code.strip() for code in self.category_codes if code.strip())
        )
        if not self.query and not self.category_codes:
            raise ValueError("query or category_codes is required")
        return self


class SearchInterpretedQuery(BaseModel):
    intent: Literal["SEARCH_EXHIBITOR"] = "SEARCH_EXHIBITOR"
    concepts: list[str] = Field(default_factory=list)
    fallback_mode: Literal["KEYWORD"] = "KEYWORD"


class SearchResult(BaseModel):
    result_id: str
    rank: int = Field(ge=1)
    object_type: Literal["EXHIBITOR"] = "EXHIBITOR"
    exhibitor_id: uuid.UUID
    booth_id: uuid.UUID
    name: str
    booth_number: str
    zone_name: str | None = None
    summary: str | None = None
    product_names: list[str] = Field(default_factory=list)
    reason: str
    concepts: list[str] = Field(default_factory=list)
    operating_status: Literal["OPEN", "PAUSED"]
    estimated_wait_minutes: int | None = Field(default=None, ge=0)
    map_x: float | None = None
    map_y: float | None = None


class SearchClarification(BaseModel):
    question: str
    options: list[str]


class SearchResponse(BaseModel):
    search_session_id: uuid.UUID
    channel: SearchChannel
    interpreted_query: SearchInterpretedQuery
    results: list[SearchResult]
    clarification: SearchClarification | None = None
    created_at: datetime
    expires_at: datetime
