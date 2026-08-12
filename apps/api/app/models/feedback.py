"""interaction.feedback - visit feedback persistence model (BACKEND-017).

Scope note (BACKEND-017), same judgment pattern as BACKEND-016
--------------------------------------------------------------------------------------------
``.harness/backlog.yaml``'s BACKEND-017 entry owns only ``owned_paths`` for the router+schema
(``apps/api/app/api/v1/routers/feedback.py``, ``apps/api/app/schemas/feedback.py``) and lists no
prior CONTRACTS-track task that published a feedback model - unlike CONTRACT-005/BACKEND-009's
split (a CONTRACTS task publishes the model first, a separate downstream task builds the
router). This file, its Alembic migration, the schema, and the router are therefore built
together in the same task, mirroring BACKEND-016's ``app/models/checkin.py`` precedent exactly
(a deliberate, low-risk, reversible judgment call - nothing else owns the model and the feature
is meaningless without persistence).

Authoritative schema: docs/db-erd-table-spec.md §16.3 "interaction.feedback".
Authoritative wire contract: docs/frontend-backend-ai-interface-spec.md §13.2 "피드백".

Ownership is derived from visit_session, never duplicated here
--------------------------------------------------------------------------------------------
db-erd §16.3 lists only ``visit_session_id`` as the subject link (no ``user_id``/
``guest_session_id`` columns), exactly ``app/models/checkin.py::CheckIn``'s precedent -
"주체는 visit_session에서 파생하므로 user_id와 guest_session_id를 중복 저장하지 않는다". A
caller resolves "whose feedback is this" by joining through ``visit_session``, never by reading
an owner column directly on this table.

recommendable_id FK shape follows the established repo convention
--------------------------------------------------------------------------------------------
Same three-column composite ``ForeignKeyConstraint(["tenant_id", "event_id",
"recommendable_id"], [...])`` into ``exhibition.recommendable``'s own boundary that
``app/models/favorite.py::Favorite`` already uses. visit_session_id uses the same composite-FK
shape into ``profile.visit_session`` that ``CheckIn`` uses.

``match_result_id`` is optional, and only soft-validated (never blocks the write)
--------------------------------------------------------------------------------------------
Not every feedback event traces back to a specific recommendation slate (a visitor can leave
feedback about something reached through search or a QR scan). Where it is supplied but does
not resolve, the service layer drops it rather than rejecting the whole request - identical
rationale to ``app/services/checkin/service.py::submit_check_in``'s treatment of its own
``match_result_id``: the feedback record itself is the important side effect, an unresolvable
lineage pointer must never block it.

Rating is a closed set, positive/negative reason codes are validated at the schema layer
--------------------------------------------------------------------------------------------
docs/frontend-backend-ai-interface-spec.md §13.2's processing table enumerates exactly five
reason codes (TASTE, PRICE, CONGESTION, SOLD_OUT_OR_CLOSED, EXPLANATION_ERROR) with no "등"
trailing marker - unlike ``CheckIn.activities`` (db-erd §16.2: "TASTING, PURCHASE 등",
deliberately open), this is a genuinely closed, exhaustive list, so ``rating`` gets the same
DB-level ``CHECK ... IN (...)`` treatment ``CheckIn.check_in_method``/``Favorite.source`` already
use. The two reason-code JSONB list columns are NOT given a DB-level CHECK (no established
precedent in this codebase for validating individual elements of a JSONB array via CHECK/
function - see ``CheckIn.activities``, which is unconstrained JSONB at the DB layer for the same
reason); the closed set is instead enforced at the Pydantic schema layer
(``app/schemas/feedback.py::FeedbackReasonCode``), matching this repo's existing practice of
layering stricter validation at the API boundary than at the DDL boundary where a DB-level
mechanism doesn't already exist.

Preference-vs-situational reason-code split is structural, not consumed here
--------------------------------------------------------------------------------------------
docs/frontend-backend-ai-interface-spec.md §13.2's table and db-erd §16.3 ("프로파일 보정은
preference_adjustment에 별도로 저장하고 상황 원인은 취향 가중치에 적용하지 않는다") require that
TASTE/PRICE (genuine preference signals) and CONGESTION/SOLD_OUT_OR_CLOSED (situational/
operational signals) are NEVER blurred into one score, and that EXPLANATION_ERROR is a distinct
data-quality-review signal. No ``preference_adjustment`` table or consumer exists anywhere in
this codebase yet (grep confirms - it is only prose in docs/db-erd-table-spec.md), and building
that consumption pipeline is explicitly out of this task's scope: this module does not compute,
aggregate, or average any of these codes into a score. It only needs to store the two reason-code
lists as separate columns (already true of the wire contract's own
``positive_reasons``/``negative_reasons`` split) so a future ``preference_adjustment`` writer
could filter ``positive_reasons``/``negative_reasons`` by category without this table needing to
change shape. :data:`PREFERENCE_REASON_CODES`, :data:`SITUATIONAL_REASON_CODES`, and
:data:`REVIEW_QUEUE_REASON_CODES` below document (and, via
``tests/test_feedback_model.py``, prove) that partition explicitly, so a future maintainer never
has to rediscover it from prose.

``comment`` is stored encrypted, reusing the existing envelope-encryption mechanism
--------------------------------------------------------------------------------------------
db-erd §16.3: "암호화 또는 민감도 검토된 comment". This repo already has one established
AEAD-envelope mechanism for exactly this need - ``app/core/auth.py::encrypt_secret``/
``decrypt_secret`` (AES-GCM, a purpose-tagged AAD, checked in ``app/models/meeting.py``'s
``message_enc``/``memo_enc``/``note_enc`` columns, all ``LargeBinary``) - reused here as
``comment_enc`` with a new, distinct ``purpose="feedback-comment"`` tag (a distinct purpose tag
always derives non-interchangeable ciphertext - see that module's docstring) rather than
inventing new crypto or storing plaintext. See ``app/services/feedback/service.py`` for the
encrypt/decrypt wrappers, mirroring ``app/services/meeting/buyer_matching.py::
encrypt_meeting_text``/``decrypt_meeting_text``'s thin-wrapper shape.

No update/delete endpoint - append-only, matching this repo's audit-shaped tables
--------------------------------------------------------------------------------------------
db-erd §16.3: "원본 피드백은 수정하지 않는다" (the original feedback row is never edited once
created). This table has no ``updated_at``/``deleted_at`` columns at all (contrast
``Favorite.deleted_at``'s soft-delete) - there is structurally nothing to mutate. See
``app/api/v1/routers/feedback.py`` (only a POST route is exposed) and
``tests/test_feedback_api.py`` for a router-level assertion that no PATCH/PUT/DELETE exists.

``client_event_id`` belt-and-suspenders partial-unique index, Idempotency-Key is the primary
mechanism
--------------------------------------------------------------------------------------------
docs/frontend-backend-ai-interface-spec.md §11 lists check-in and feedback together as
supporting offline-queue resend ("체크인·피드백은 오프라인 큐 재전송을 허용한다"). This mirrors
``CheckIn``'s exact two-layer approach: the primary de-dupe mechanism is an
``Idempotency-Key`` header replayed against ``integration.idempotency_record`` (see
``app/services/feedback/service.py``), and this partial-unique index on ``client_event_id`` is a
second, independent safety net against the same offline-resend edge case ``CheckIn``'s own
docstring documents (a client bug that regenerates the Idempotency-Key on retry but keeps the
same ``client_event_id``) - not a replacement for the idempotency_record path.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    LargeBinary,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import SCHEMA_EXHIBITION, SCHEMA_INTERACTION, SCHEMA_MATCHING, Base
from app.models.common import new_uuid7

#: docs/frontend-backend-ai-interface-spec.md §13.2 JSON example + FeedbackRating.
FEEDBACK_RATINGS: tuple[str, ...] = ("VERY_RELEVANT", "RELEVANT", "NOT_RELEVANT")

#: §13.2's processing table, in table order. Exhaustive (no "등") - see module docstring.
PREFERENCE_REASON_CODES: tuple[str, ...] = ("TASTE", "PRICE")
SITUATIONAL_REASON_CODES: tuple[str, ...] = ("CONGESTION", "SOLD_OUT_OR_CLOSED")
REVIEW_QUEUE_REASON_CODES: tuple[str, ...] = ("EXPLANATION_ERROR",)
FEEDBACK_REASON_CODES: tuple[str, ...] = (
    PREFERENCE_REASON_CODES + SITUATIONAL_REASON_CODES + REVIEW_QUEUE_REASON_CODES
)


def _in_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


class Feedback(Base):
    """interaction.feedback - db-erd-table-spec.md §16.3.

    See the module docstring for the ownership-via-visit_session, reason-code-partition, and
    comment-encryption design rationale this table's constraints and columns encode.
    """

    __tablename__ = "feedback"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            [
                f"{SCHEMA_EXHIBITION}.event.tenant_id",
                f"{SCHEMA_EXHIBITION}.event.event_id",
            ],
            name="fk_feedback_event_boundary",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "event_id", "visit_session_id"],
            [
                "profile.visit_session.tenant_id",
                "profile.visit_session.event_id",
                "profile.visit_session.visit_session_id",
            ],
            name="fk_feedback_visit_session_boundary",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "event_id", "recommendable_id"],
            [
                f"{SCHEMA_EXHIBITION}.recommendable.tenant_id",
                f"{SCHEMA_EXHIBITION}.recommendable.event_id",
                f"{SCHEMA_EXHIBITION}.recommendable.recommendable_id",
            ],
            name="fk_feedback_recommendable_boundary",
        ),
        CheckConstraint(
            f"rating IN ({_in_list(FEEDBACK_RATINGS)})",
            name="feedback_rating_allowed",
        ),
        # Lookup indexes for eventual "feedback history" / "feedback per target" queries -
        # mirrors app/models/favorite.py's ix_favorite_user_created precedent.
        Index(
            "ix_feedback_visit_session_created",
            "tenant_id",
            "event_id",
            "visit_session_id",
            "created_at",
        ),
        Index(
            "ix_feedback_recommendable_created",
            "tenant_id",
            "event_id",
            "recommendable_id",
            "created_at",
        ),
        # Belt-and-suspenders offline-dedupe safety net - see module docstring.
        Index(
            "uq_feedback_active_client_event",
            "tenant_id",
            "event_id",
            "client_event_id",
            unique=True,
            postgresql_where=text("client_event_id IS NOT NULL"),
        ),
        {"schema": SCHEMA_INTERACTION},
    )

    feedback_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=new_uuid7
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    event_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    visit_session_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False
    )
    recommendable_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False
    )
    match_result_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_MATCHING}.match_result.match_result_id"),
        nullable=True,
    )
    rating: Mapped[str] = mapped_column(String(20), nullable=False)
    positive_reasons: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    negative_reasons: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    #: AES-GCM envelope ciphertext (app/core/auth.py::encrypt_secret,
    #: purpose="feedback-comment") - never plaintext. NULL when no comment was given.
    comment_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    client_event_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
