"""Pydantic schemas for BACKEND-009 ``GET/POST/DELETE /me/favorites[/{favorite_id}]``.

object_type/source values are literals, not a lookup against an ontology catalog - this
mirrors ``app/models/favorite.py``'s own ``FAVORITE_SOURCES`` tuple and
``app/models/matching.py::Recommendable``'s ``object_type_allowed`` CHECK, both fixed, small,
schema-level enumerations (unlike the open-ended ontology concept codes elsewhere in this repo
that deliberately avoid hardcoded enums).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

FavoriteObjectType = Literal["EXHIBITOR", "PRODUCT", "BOOTH", "PROGRAM"]
FavoriteSource = Literal["SEARCH", "RECOMMENDATION"]


class FavoriteCreateRequest(BaseModel):
    object_type: FavoriteObjectType
    object_id: uuid.UUID
    source: FavoriteSource = "SEARCH"
    match_result_id: uuid.UUID | None = None


class FavoriteRead(BaseModel):
    favorite_id: uuid.UUID
    object_type: FavoriteObjectType
    object_id: uuid.UUID
    source: FavoriteSource
    match_result_id: uuid.UUID | None
    created_at: datetime


class FavoriteListResponse(BaseModel):
    items: list[FavoriteRead]
    next_cursor: str | None = None
