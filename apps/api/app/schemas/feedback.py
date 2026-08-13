"""Pydantic schemas for BACKEND-017 ``POST /feedback``.

Wire contract: docs/frontend-backend-ai-interface-spec.md §13.2 "피드백". Field names/shapes
match ``apps/user-web/lib/types.ts``'s ``FeedbackRequest``/``FeedbackResponse`` exactly - see
``app/models/feedback.py`` for the full design-rationale cross-reference (rating closed set,
reason-code partition, comment encryption, append-only).

``rating``/``positive_reasons``/``negative_reasons`` are closed Literals here, even though the
frontend types them as ``OpenEnum`` (``Known | (string & {})``) for its own forward-compat
reasons
--------------------------------------------------------------------------------------------
docs/frontend-backend-ai-interface-spec.md §13.2's processing table enumerates exactly three
ratings and five reason codes with no "등" trailing marker - a genuinely closed, exhaustive
list (contrast ``app/schemas/checkin.py``'s deliberately-open ``activities: list[str]``, whose
db-erd entry does carry "등"). A request with an unknown code fails with a standard Pydantic 422
here; that is the intended fail-closed behavior for a table this API never revises after
insert (see ``Feedback``'s "append-only" docstring section) - a silently-accepted unknown reason
code could never be corrected later.

``object_id`` is typed as ``uuid.UUID``, matching ``app/schemas/favorite.py::
FavoriteCreateRequest.object_id`` exactly (same object_type/object_id target-resolution shape,
reused via ``app.services.favorite.service.resolve_recommendable_id`` - see
``app/services/feedback/service.py``). The frontend's ``FeedbackRequest.object_id: string`` is
satisfied by any UUID-shaped string, exactly as it already is for favorites.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.models.feedback import FEEDBACK_REASON_CODES

#: Mirrors app.services.favorite.service.FavoriteObjectType - the same caller-facing
#: object_type vocabulary every (object_type, object_id) -> recommendable_id resolution in this
#: repo already accepts (BOOTH/PROGRAM direct, PRODUCT/EXHIBITOR indirect - see that module).
FeedbackObjectType = Literal["EXHIBITOR", "PRODUCT", "BOOTH", "PROGRAM"]

FeedbackRating = Literal["VERY_RELEVANT", "RELEVANT", "NOT_RELEVANT"]

#: Derived from app.models.feedback.FEEDBACK_REASON_CODES (itself PREFERENCE_REASON_CODES +
#: SITUATIONAL_REASON_CODES + REVIEW_QUEUE_REASON_CODES) rather than hand-duplicated, so the API
#: boundary's accepted set can never drift from the model's CHECK constraint and the
#: preference/situational partition it documents.
FeedbackReasonCode = Literal[*FEEDBACK_REASON_CODES]


class FeedbackRequest(BaseModel):
    object_type: FeedbackObjectType
    object_id: uuid.UUID
    match_result_id: uuid.UUID | None = None
    rating: FeedbackRating
    positive_reasons: list[FeedbackReasonCode] = []
    negative_reasons: list[FeedbackReasonCode] = []
    comment: str | None = None
    client_event_id: uuid.UUID | None = None


class FeedbackResponse(BaseModel):
    feedback_id: uuid.UUID
    recorded_at: datetime
