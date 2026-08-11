"""WAVE 2E BACKEND-EVENT-COLLECTION request/response schemas.

``POST /events/interaction`` and ``POST /events/interaction/batch`` (see
``app/api/v1/routers/interaction_event.py``) collect CLIENT-reported UI events (impressions,
clicks, dwell, search submissions) that the server cannot otherwise observe. This is
deliberately a *different, narrower* contract than ``app/schemas/recommendation.py``'s
``InteractionEventIn``/``/api/v1/interactions/batch``:

  - that endpoint validates each event strictly against the interface-spec's fixed
    ``CANONICAL_EVENTS`` catalog and against real, already-persisted recommendation-session/
    slate state (it is the sink for the *recommendation* domain's own lifecycle events).
  - this endpoint additionally has to support anonymous kiosk traffic (no profile/session
    machinery to check against), enforce a hard batch-size/payload-size/rate-limit ceiling
    suited to unauthenticated beacons, and mask free-text search queries before anything
    touches storage - none of which the existing endpoint does or needs to do.

Both ultimately write into the *same* underlying ``interaction.interaction_event`` /
``interaction.client_event_dedupe`` tables (``app/models/matching.py`` - see
``app/models/interaction_event.py`` module docstring), so a ``client_event_id`` claimed via
either endpoint is honoured by both.

Envelope/Meta/ErrorBody are intentionally re-declared here rather than imported from another
track's schema file - see the identical rationale in ``app/schemas/buyer_match.py``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

T = TypeVar("T")


class Meta(BaseModel):
    request_id: str
    server_time: datetime


class FieldError(BaseModel):
    field: str
    reason: str


class ErrorBody(BaseModel):
    code: str
    message: str
    field_errors: list[FieldError] = Field(default_factory=list)


class ErrorEnvelope(BaseModel):
    success: Literal[False] = False
    error: ErrorBody
    meta: Meta


class Envelope(BaseModel, Generic[T]):
    success: Literal[True] = True
    data: T
    meta: Meta


# ---------------------------------------------------------------------------
# Limits (task spec: "Batch max 50 items, max payload 256KB")
# ---------------------------------------------------------------------------

MAX_BATCH_EVENTS = 50
MAX_BATCH_PAYLOAD_BYTES = 256 * 1024
MAX_SEARCH_QUERY_INPUT_LENGTH = 500
MAX_CONTEXT_STRING_LENGTH = 200

EventSource = Literal["WEB", "KIOSK"]

#: Identity/contact-shaped keys that must never appear in a KIOSK-sourced event's ``context``
#: (PROJECT_SCOPE.md kiosk exclusions; this track's explicit "kiosk events must never accept a
#: user identifier, contact info, or long-term device fingerprint" requirement). Matched
#: case-insensitively against context keys by
#: ``app/services/interaction_event/validation.py:find_forbidden_kiosk_keys``.
KIOSK_FORBIDDEN_CONTEXT_KEYS = frozenset(
    {
        "user_id",
        "user_id_hash",
        "profile_id",
        "guest_session_id",
        "visit_session_id",
        "email",
        "phone",
        "phone_number",
        "name",
        "full_name",
        "device_id",
        "device_fingerprint",
        "fingerprint",
        "advertising_id",
        "idfa",
        "gaid",
        "ip",
        "ip_address",
        "mac_address",
        "imei",
        "ssn",
        "resident_registration_number",
    }
)

try:  # pragma: no cover - mirrors recommendations.py's identical defensive import.
    from meet_ai.ontology.catalog import CANONICAL_EVENTS as _INTERFACE_CANONICAL_EVENTS
except ImportError:  # pragma: no cover
    _INTERFACE_CANONICAL_EVENTS = frozenset()

#: WAVE2E supplementary UI-telemetry event types - raw client-observed signals (impressions,
#: clicks, dwell, search, map, QR) that predate/exceed the interface-spec's fixed event
#: catalog. Unioned with that catalog (rather than replacing it) so this endpoint can also
#: accept the same canonical names recommendations.py accepts without inventing a competing
#: synonym for them.
_CLIENT_UI_EVENT_TYPES = frozenset(
    {
        "UI_VIEW_IMPRESSION",
        "UI_VIEW_CLICK",
        "UI_VIEW_DETAIL",
        "UI_VIEW_DISMISS",
        "UI_VIEW_LONG_READ",
        "UI_COMPARE_VIEW",
        "UI_SEARCH_SUBMIT",
        "UI_MAP_INTERACTION",
        "UI_QR_SCAN",
        "UI_ERROR",
    }
)

CLIENT_INTERACTION_EVENT_TYPES = frozenset(_INTERFACE_CANONICAL_EVENTS) | _CLIENT_UI_EVENT_TYPES


class ClientInteractionEventIn(BaseModel):
    """A single client-observed UI event within a batch.

    ``model_config(extra="forbid")``: any field the client sends that this contract does not
    know about is a hard per-item schema error rather than being silently ignored (defense in
    depth against a client build smuggling an identity-shaped field as a stray top-level key
    instead of inside ``context``).
    """

    model_config = ConfigDict(extra="forbid")

    client_event_id: uuid.UUID
    event_type: str = Field(min_length=1, max_length=60)
    occurred_at: datetime
    object_type: Literal["BOOTH", "PRODUCT", "EXHIBITOR", "PROGRAM", "SEARCH_RESULT"] | None = (
        None
    )
    object_id: str | None = Field(default=None, max_length=100)
    screen: str | None = Field(default=None, max_length=40)
    #: Raw client free text (e.g. a kiosk/web search box submission). Masked server-side
    #: (phone/email/RRN/account-number-shaped substrings) before anything is persisted - see
    #: ``app/services/interaction_event/masking.py``. Never stored verbatim.
    search_query: str | None = Field(default=None, max_length=MAX_SEARCH_QUERY_INPUT_LENGTH)
    #: Allow-listed at persistence time (app/services/interaction_event/masking.py -
    #: ALLOWED_CONTEXT_KEYS); unknown keys are dropped, not rejected, mirroring
    #: recommendations.py's ``_sanitize_context`` convention for this same free-form field.
    context: dict[str, Any] | None = None

    @field_validator("event_type")
    @classmethod
    def _normalize_event_type(cls, value: str) -> str:
        return value.strip().upper()


class ClientInteractionBatchRequest(BaseModel):
    """Batch envelope. ``events`` is deliberately ``list[dict]`` (not
    ``list[ClientInteractionEventIn]``): the task requires partial-success semantics where one
    malformed item in a batch must not fail the whole request. A typed nested-list field would
    make Pydantic reject the *entire* request on the first invalid item; keeping the raw dicts
    here lets ``app/services/interaction_event/ingestion.py`` validate each item independently
    and report only that item as ``REJECTED`` / ``SCHEMA_ERROR``.
    """

    tenant_id: uuid.UUID
    event_id: uuid.UUID
    source: EventSource
    #: WEB-only subject fields (must be absent when source == KIOSK).
    profile_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None
    guest_session_id: uuid.UUID | None = None
    visit_session_id: uuid.UUID | None = None
    #: KIOSK-only subject fields (must be absent when source == WEB). Deliberately just the
    #: anonymous kiosk device code + session id - never an identity.
    kiosk_id: str | None = Field(default=None, max_length=80)
    kiosk_session_id: uuid.UUID | None = None
    events: list[dict[str, Any]] = Field(min_length=1, max_length=MAX_BATCH_EVENTS)

    @model_validator(mode="after")
    def _validate_source_scoped_fields(self) -> ClientInteractionBatchRequest:
        if self.source == "KIOSK":
            if any(
                value is not None
                for value in (
                    self.profile_id,
                    self.user_id,
                    self.guest_session_id,
                    self.visit_session_id,
                )
            ):
                raise ValueError(
                    "KIOSK-sourced batches must not carry a profile/user/guest/visit "
                    "session identifier"
                )
        elif self.kiosk_id is not None or self.kiosk_session_id is not None:
            raise ValueError("kiosk_id/kiosk_session_id are only valid when source == KIOSK")
        return self


class ClientInteractionSingleRequest(BaseModel):
    """``POST /events/interaction`` body: the batch envelope fields plus exactly one event."""

    tenant_id: uuid.UUID
    event_id: uuid.UUID
    source: EventSource
    profile_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None
    guest_session_id: uuid.UUID | None = None
    visit_session_id: uuid.UUID | None = None
    kiosk_id: str | None = Field(default=None, max_length=80)
    kiosk_session_id: uuid.UUID | None = None
    event: dict[str, Any]

    def to_batch_request(self) -> ClientInteractionBatchRequest:
        return ClientInteractionBatchRequest(
            tenant_id=self.tenant_id,
            event_id=self.event_id,
            source=self.source,
            profile_id=self.profile_id,
            user_id=self.user_id,
            guest_session_id=self.guest_session_id,
            visit_session_id=self.visit_session_id,
            kiosk_id=self.kiosk_id,
            kiosk_session_id=self.kiosk_session_id,
            events=[self.event],
        )


EventResultStatus = Literal["ACCEPTED", "DUPLICATED", "REJECTED"]


class ClientInteractionEventResult(BaseModel):
    #: ``None`` only when the raw item was so malformed that even ``client_event_id`` could not
    #: be recovered from it.
    client_event_id: uuid.UUID | None
    interaction_event_id: uuid.UUID | None
    status: EventResultStatus
    reason_code: str | None = None


class ClientInteractionEventError(BaseModel):
    client_event_id: uuid.UUID | None
    reason_code: str
    #: Safe, application-constructed message only - never raw exception text or raw client
    #: input (which could echo back an unmasked free-text query). See
    #: ``app/services/interaction_event/ingestion.py:_safe_validation_summary``.
    message: str


class ClientInteractionBatchResponse(BaseModel):
    accepted: int
    duplicated: int
    rejected: int
    results: list[ClientInteractionEventResult]
    errors: list[ClientInteractionEventError]
