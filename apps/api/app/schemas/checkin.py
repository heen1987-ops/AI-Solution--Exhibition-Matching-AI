"""Pydantic schemas for BACKEND-016 ``POST /check-ins``.

Wire contract: docs/frontend-backend-ai-interface-spec.md §13.1 "체크인". Field names/shapes
match ``apps/user-web/lib/types.ts``'s ``CheckInRequest``/``CheckInResponse`` exactly (that
file is the frontend's already-shipped source of truth - see that module for the full
docstring cross-reference).

``activities`` is an open string list, not a Literal
--------------------------------------------------------------------------------------------
``apps/user-web/lib/types.ts::CheckInActivity`` is declared ``OpenEnum<"TASTING" | "PURCHASE" |
"MEETING" | "INFO_CHECK" | "LEFT_WAITING">`` - i.e. ``Known | (string & {})``, deliberately not
closed, because ``docs/db-erd-table-spec.md`` §16.2 lists the column as
``activities | JSONB | TASTING, PURCHASE 등`` ("등" = "etc.", an illustrative not exhaustive
list). A strict ``Literal`` here would reject a legitimate future activity code the frontend
already knows how to send before this schema is updated. This mirrors
``app/models/favorite.py``'s deliberate choice to use a fixed ``Literal`` only for genuinely
closed, small enumerations (contrast that module's own docstring) - activities is the open
case, not the closed one.

``client_event_id`` is typed as a UUID, not a bare string
--------------------------------------------------------------------------------------------
``docs/db-erd-table-spec.md`` §16.2 types the column ``client_event_id | UUID``.
``docs/frontend-backend-ai-interface-spec.md`` §13.1's illustrative JSON example
(``"client_evt_001"``) is prose formatting, not a literal contract - the frontend's actual
``generateClientId()`` (``apps/user-web/lib/api-client.ts``) always emits a real
``crypto.randomUUID()``-shaped string (with a non-crypto fallback that still produces the same
``xxxxxxxx-xxxx-...`` shape), and that same value is reused as both the request body's
``client_event_id`` and the ``Idempotency-Key`` header. A malformed value here fails Pydantic
validation with a standard 422, which is correct: a caller that cannot produce a real UUID
cannot participate in offline-dedupe or Idempotency-Key replay correctly anyway.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class CheckInRequest(BaseModel):
    qr_token: str = Field(min_length=1)
    activities: list[str] = Field(min_length=1)
    match_result_id: uuid.UUID | None = None
    client_event_id: uuid.UUID | None = None
    occurred_at: datetime


class CheckInResponse(BaseModel):
    check_in_id: uuid.UUID
    booth_id: uuid.UUID | None
    checked_in_at: datetime
    activities: list[str]
    #: 13.1절: 중복이면 오류 대신 기존 체크인 정보를 반환한다.
    duplicate: bool
