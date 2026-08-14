# Interaction-event collection, in-app notifications, and admin analytics/operations contract

> Track: CONTRACTS-OPERATIONS (WAVE 2E). Defines the contract for (1) the interaction-event
> envelope and event-name catalog, (2) in-app notifications and channel policy, (3) admin
> analytics and the "event-message" operations tool — adapted to the real repo layout
> (`apps/api/app/**`, flat `router/model/schema/service` convention — see
> `.harness/assumptions.md` ASSUMPTION-003), not the external prompt's assumed
> `apps/api/src/modules/**` layout.
>
> Precedence, per ASSUMPTION-002/DECISION-005: where an already-shipped, tested implementation
> differs from the WAVE2E prompt's assumed shape, the shipped implementation is canonical and the
> prompt's shape is recorded as a naming/structure variant to be layered on top of it — not
> reimplemented as a second parallel surface. This is contracts-only; no app code, no migration,
> was written or run by this task.

## 0. TL;DR — what already exists vs. what is a genuine gap

| Area | Status | Where |
|---|---|---|
| Event envelope table (partitioned, append-only, tenant/event/subject-scoped) | **Exists** | `interaction.interaction_event` (`apps/api/app/models/matching.py::InteractionEvent`) |
| Client-side offline-resend dedup | **Exists** | `interaction.client_event_dedupe` (`InteractionClientEventDedupe`) |
| Event ingestion endpoint (batch) | **Exists** | `POST /api/v1/interactions/batch` (`apps/api/app/api/v1/routers/recommendations.py`) |
| Closed event-name catalog (enforced) | **Exists, but only 20 flat names, no domain grouping, several domains entirely absent** | `CANONICAL_EVENTS` in `src/meet_ai/ontology/catalog.py` (AI_SEARCH-owned path) |
| Recommendation delivery/fan-out record (per channel, per result) | **Exists, but scoped only to recommendations** | `matching.recommendation_delivery` |
| General-purpose in-app notification inbox (`GET /me/notifications`, read/unread, preferences) | **Does not exist** | genuine gap — this contract defines it |
| Durable, queryable search history for admin analytics (`/admin/analytics/searches`, `/no-results`) | **Does not exist — current search-session state is Redis, TTL-bound, not a mart source** | `apps/api/app/services/search_sessions.py::SearchSessionStore`; genuine gap |
| Admin router at all | **Does not exist** (`BACKEND-007` is `READY`, not started) | genuine gap, this contract is what it should build against |
| `analytics` / `quality` Postgres schemas | **Reserved in `db/base.py`, zero tables registered yet** | genuine gap |
| `notification` Postgres schema | **Does not exist** | this contract proposes adding it, additive, mirroring how `SCHEMA_KIOSK`/`SCHEMA_DOCUMENT` were added when no existing schema fit |

## 1. Event envelope

### 1.1 Decision: extend `interaction.interaction_event`, do not create a parallel envelope table

The WAVE2E prompt's envelope shape (`event_id, event_name, event_version, occurred_at, received_at,
source, event_context{event_instance_id, session_id, user_id_hash, kiosk_id, request_id}, payload`)
is **not a new table** — it is a restatement, with different field names, of the table that already
exists, is already partitioned, already has FK-verified tenant/event/session/result boundaries, and
is already wired to a live ingestion endpoint and 147 passing tests' worth of surrounding matching
code. Building a second table would violate the "check for prior art" rule and would fork the
append-only event log the rest of the matching/learning pipeline (`behavior_signal`,
`attribute_evidence` in `learning.py`) already FKs into.

Field-by-field mapping:

| Spec field | Existing column (`interaction.interaction_event` unless noted) | Notes |
|---|---|---|
| `event_id` | `(event_date, interaction_event_id)` composite PK | Partition key + UUIDv7 id. External API surfaces `interaction_event_id` as the opaque event id; `event_date` is derivable from `occurred_at` (UTC date), never a client-supplied field. |
| `event_name` | `event_type` (`String(60)`, free string, catalog-enforced — see §2) | **Naming variant, not a gap.** Recommend keeping the existing column/field name `event_type` (renaming a shipped, tested, client-facing Pydantic field is a breaking API change for zero functional gain) but treat "event name" and "event_type" as the same concept everywhere in this doc and in any client SDK docstrings written from this contract. |
| `event_version` | **Missing — genuine gap** | No column exists. Recommend a new nullable `event_version: Mapped[str \| None] = mapped_column(String(10))` on `interaction_event`, default `"1"` at the application layer (not a DB server-default, so a bumped catalog schema version is always an explicit choice, not silently inherited). Needed before any consumer needs to distinguish "old vs. new payload shape for the same `event_type`". Not yet load-bearing — no consumer needs it today — so this is a additive, low-risk migration whenever BACKEND next touches this table. |
| `occurred_at` | `occurred_at` (`DateTime(timezone=True)`, required, tz-aware — enforced today by `InteractionEventIn._occurred_at_must_include_timezone`) | No change. |
| `received_at` | `received_at` (`DateTime(timezone=True)`, `server_default=func.now()`) | No change. Already BRIN-indexed (`ix_interaction_event_received_brin`) for time-range analytics scans — reuse this index for the admin analytics mart's incremental refresh queries rather than adding a redundant one. |
| `source` (client/device origin) | **Missing — genuine gap, distinct from `event_type`** | No column exists today; nothing currently distinguishes "this event came from the user-web app" vs. "from the kiosk app" vs. "from an admin/operator action" vs. "from an async worker replaying a job" at the envelope level (only `screen_code`, a free string, hints at UI origin). Recommend a new nullable `source: Mapped[str \| None] = mapped_column(String(20))` with candidate values `WEB \| KIOSK \| ADMIN \| SYSTEM`. **Deliberately not merged with `profile.user_consent.source_channel`'s existing `WEB \| QR \| KIOSK` enum** — that column answers "which channel captured this consent", a narrower and semantically different question (no `ADMIN`/`SYSTEM` origin makes sense for a consent capture) than "which app emitted this interaction event". Record this as a deliberate exception per AGENTS.md's "record any deliberate exception before implementing it" — two similarly-named-but-different-domain enums are intentional here, not oversight. |
| `event_context.event_instance_id` | `client_event_id` (`UUID`, nullable) | Already exists, already the dedup key against `interaction.client_event_dedupe`. No change — this is the same field under a different name in the prompt. |
| `event_context.session_id` | **Do not collapse — keep the existing typed FKs** | The table already carries three separate, FK-verified session-shaped columns: `visit_session_id` (→ `profile.visit_session`), `recommendation_session_id` (→ `matching.recommendation_session`), and (see next row) a proposed `kiosk_session_id`. Replacing these with one untyped `event_context.session_id` string would delete referential integrity the schema already has. Recommend clients populate whichever of the three actually applies; a generic client library MAY still expose one `sessionId` field and let the server route it into the right column server-side, but the **stored** shape keeps the three typed FKs. |
| `event_context.kiosk_id` | **Missing — genuine gap** | `kiosk.kiosk_session.kiosk_id` (device/config code, `String(80)`, not a UUID — see `apps/api/app/models/kiosk.py`) exists, but `interaction_event` has no FK to `kiosk.kiosk_session` at all today. Kiosk-originated interaction events currently have no structured link back to which kiosk session (and therefore which physical kiosk device) produced them — only the generic, nullable `guest_session_id` (→ `profile.guest_session`, a **different** table from `kiosk.kiosk_session` — do not conflate the two; `profile.guest_session` is the QR-handoff guest-web session, `kiosk.kiosk_session` is the anonymous on-site device session). Recommend a new nullable `kiosk_session_id: Mapped[uuid.UUID \| None]` FK to `kiosk.kiosk_session.kiosk_session_id`, with the same `num_nonnulls(...) <= 1`-style guard extended to keep `user_id`/`guest_session_id`/`kiosk_session_id` mutually exclusive (a kiosk event has no user or guest-web subject). This is the one gap in this table most worth prioritizing — without it, `/admin/analytics/kiosk` (§4) has no reliable way to attribute events to a kiosk device. |
| `event_context.request_id` | **Not stored on the row — already available via `Meta.request_id`/`X-Request-ID`, do not duplicate** | Every response envelope (`app/schemas/recommendation.py::Meta`, mirrored in `profile.py`/`buyer_match.py`) already carries `request_id`, generated from the inbound `X-Request-ID` header if present (see `recommendation_exception_handler`). Recommend correlating via application logs (which already log `request_id`), not by adding another column to a partitioned, high-volume table for a value that has no analytical use once the request completes. If a future audit need requires it stored, add it then — do not pre-add unused columns to a partitioned table. |
| `payload` | `context_json` (`JSONB`, nullable) | No change. **Binding invariant already documented in the model's own docstring and restated here**: never place direct identifiers, free-text notes verbatim, OTPs, tokens, or full URL query strings into `context_json`/`payload`. The router is responsible for allow-listing keys before persisting — this is application-layer enforcement, the schema cannot enforce it. |
| — | `tenant_id`, `event_id` (FK to `exhibition.event`), `recommendable_id`, `match_result_id`, `rank_at_event`, `screen_code`, `consent_snapshot_id` | Existing columns with no equivalent named in the WAVE2E prompt's envelope — kept as-is; they are strictly additive context the matching pipeline already depends on. Do not remove. |

### 1.2 Subject identity: no `user_id_hash` field — reuse the existing FK-based subject columns

The prompt's `event_context.user_id_hash` implies hashing the user id into the event row. **Do not
do this.** The existing table already resolves the subject via `user_id` (nullable FK to
`profile.user_account`) XOR `guest_session_id` (nullable FK to `profile.guest_session`), enforced by
`CheckConstraint("num_nonnulls(user_id, guest_session_id) <= 1", name="subject_at_most_one")`, which
also explicitly permits both being NULL for system/operational events. This is stronger than a hash
(a hash is still a stable pseudonymous re-identification key sitting in a hot analytics table; a
proper FK is the pattern the domain-model doc's "PII separation" convention already established —
identifiers live in `identity.user_identity`, encrypted, everything else references the surrogate
`user_id`). Adding `kiosk_session_id` per §1.1 extends the same XOR pattern rather than introducing a
parallel hashed-identifier concept. Treat `user_id_hash` in the WAVE2E prompt as an artifact of a
generic multi-tenant SaaS event-schema template, not a requirement for this domain — same category
of resolved discrepancy as DECISION-004's `INDUSTRY.MANUFACTURING` ontology example codes.

### 1.3 Ingestion endpoints

| Prompt path | Resolution |
|---|---|
| `POST /events/interaction/batch` | **Already exists**: `POST /api/v1/interactions/batch` (`InteractionBatchRequest` → `InteractionBatchResponse`, 1–100 events per call, per-event accept/reject results, idempotent via `client_event_id`). Do not build a second batch endpoint. |
| `POST /events/interaction` (single-event) | **Genuine, small gap** — no singular convenience endpoint exists. Recommend, if a client team needs it, a thin wrapper `POST /api/v1/interactions` that constructs a one-element `InteractionBatchRequest` and returns the single `InteractionEventResult` unwrapped from `InteractionBatchResponse.results[0]` — not a second ingestion code path. Not required for MVP; the batch endpoint already accepts `min_length=1`. |

## 2. Event-name catalog

### 2.1 Decision: extend the existing flat `CANONICAL_EVENTS`, do not introduce a dot-namespaced parallel vocabulary

`src/meet_ai/ontology/catalog.py::CANONICAL_EVENTS` is a **live, enforced, 20-member closed set**
(`SERVICE_STARTED`, `USER_TYPE_SELECTED`, `CONSENT_CHOICE_RECORDED`, `PROFILE_QUESTION_VIEWED`,
`PROFILE_ANSWER_SELECTED`, `PROFILE_QUESTION_SKIPPED`, `MINIMUM_PROFILE_COMPLETED`,
`RECOMMENDATION_IMPRESSION`, `RECOMMENDATION_OPENED`, `RECOMMENDATION_SAVED`,
`RECOMMENDATION_DISMISSED`, `ROUTE_ITEM_ADDED`, `ROUTE_STARTED`, `BOOTH_CHECKED_IN`,
`VISIT_OUTCOME_SELECTED`, `FEEDBACK_SUBMITTED`, `MEETING_REQUEST_STARTED`,
`MEETING_REQUEST_SUBMITTED`, `MEETING_REQUEST_DECIDED`, `MEETING_COMPLETED`). It is checked on every
`POST /interactions/batch` call (`event.event_type not in CANONICAL_EVENTS` → rejected with
`UNKNOWN_EVENT_TYPE`) and cross-validated against `catalog.v1.json`'s `event_mappings` by
`Catalog._validate_events`. This file is owned by the **AI_SEARCH** track
(`src/meet_ai/ontology/**`, per `.harness/locks.yaml`), not CONTRACTS — this task does not, and
must not, edit it.

The WAVE2E prompt's requested catalog groups (`PROFILE.*`, `SEARCH.*`, `RECOMMENDATION.*`,
`FAVORITE.*`, `KIOSK.*`, `BUYER.*`, `MEETING.*`, `DOCUMENT.*`, `CONTENT.*`, `NOTIFICATION.*`) use a
dot-namespaced `DOMAIN.ACTION` style. **Decision (Blocker Score < 7 — a naming-convention choice
with no privacy/security dimension, fully reversible, and no evidence any client already depends on
a dot-namespaced string): keep the shipped flat `SCREAMING_SNAKE_CASE` convention. Do not rename
existing members, do not introduce a second, differently-styled vocabulary.** The domain groupings
below are a **documentation-only grouping** of the same flat names — a way to read/organize the
catalog, not a wire-format change.

### 2.2 Existing catalog, grouped by domain (informative — values are unchanged)

| Domain | Existing `event_type` values |
|---|---|
| `PROFILE` | `SERVICE_STARTED`, `USER_TYPE_SELECTED`, `CONSENT_CHOICE_RECORDED`, `PROFILE_QUESTION_VIEWED`, `PROFILE_ANSWER_SELECTED`, `PROFILE_QUESTION_SKIPPED`, `MINIMUM_PROFILE_COMPLETED` |
| `RECOMMENDATION` | `RECOMMENDATION_IMPRESSION`, `RECOMMENDATION_OPENED`, `RECOMMENDATION_SAVED`, `RECOMMENDATION_DISMISSED` |
| `KIOSK` / route / visit | `ROUTE_ITEM_ADDED`, `ROUTE_STARTED`, `BOOTH_CHECKED_IN`, `VISIT_OUTCOME_SELECTED` |
| — | `FEEDBACK_SUBMITTED` |
| `MEETING` | `MEETING_REQUEST_STARTED`, `MEETING_REQUEST_SUBMITTED`, `MEETING_REQUEST_DECIDED`, `MEETING_COMPLETED` |

### 2.3 Genuine gaps — domains with zero existing catalog coverage

None of these exist today. Each is a **proposed addition** to `CANONICAL_EVENTS` (and, where noted,
to `catalog.v1.json::event_mappings`) for the AI_SEARCH track to make when it next touches that
file — not something this contract can add itself.

| Domain | Proposed new `event_type` values | Why it's missing today |
|---|---|---|
| `SEARCH` | `SEARCH_EXECUTED`, `SEARCH_RESULT_SELECTED`, `SEARCH_ZERO_RESULT` | `BACKEND-008` (public NL/category search, `POST /search`) shipped after `CANONICAL_EVENTS` was last populated (that set predates the web/kiosk split's search feature entirely — every existing member reads as pre-search-feature UX). `SEARCH_ZERO_RESULT` in particular is the direct data source `/admin/analytics/no-results` (§4) needs and does not have today (see §4.1). |
| `FAVORITE` | `FAVORITE_ADDED`, `FAVORITE_REMOVED` | `RECOMMENDATION_SAVED`/`RECOMMENDATION_DISMISSED` cover save/dismiss *from a recommendation slate specifically* (both require `match_result_id`/`recommendation_session_id` per `InteractionEventIn`'s validator). `BACKEND-009` (favorites CRUD, currently `READY`) will let a user favorite something reached via search or a booth detail page with no recommendation context at all — that path has no event to emit into today. |
| `KIOSK` (session-lifecycle, distinct from the existing route/visit events) | `KIOSK_SESSION_STARTED`, `KIOSK_SESSION_RESET`, `KIOSK_HANDOFF_ISSUED` | Kiosk session lifecycle (`apps/api/app/api/v1/routers/kiosk.py`) currently manages its own state machine (`kiosk.kiosk_session`, `kiosk.kiosk_qr_handoff`) without emitting anything into `interaction_event` — the two systems don't talk to each other yet, which is exactly why `/admin/analytics/kiosk` has no event-level source to aggregate from beyond raw `kiosk_session` row counts. |
| `BUYER` | `BUYER_COMPARE_VIEWED` (pairs with `buyer-matching.md`'s proposed, also-not-yet-built `POST /buyer/compare` from WAVE2C) | No buyer-specific interaction event exists; buyer actions today reuse the generic `RECOMMENDATION_*` events since `/recommendations` already serves buyers via `user_type=BUYER` (per WAVE2C's finding). Only needed once `/buyer/compare` itself is built. |
| `DOCUMENT` | `DOCUMENT_UPLOADED`, `DOCUMENT_REVIEW_SUBMITTED` (exhibitor-side), `DOCUMENT_APPROVED`, `DOCUMENT_REJECTED` (operator-side) | Maps onto `document-structuring.md` §1's 15-status document state machine (`EXTRACTED → EXHIBITOR_REVIEW → OPERATOR_REVIEW → APPROVED/REJECTED → PUBLISHED`, WAVE2D). That contract does not itself define event emission — this contract is where that gap is named. |
| `CONTENT` | Not a separate event domain — **see §3.3**: `CONTENT_REVIEW_RESULT` is a *notification type*, not an interaction event; it is emitted as a side effect of the `DOCUMENT_APPROVED`/`DOCUMENT_REJECTED` events above, not its own event. |
| `NOTIFICATION` | `NOTIFICATION_DELIVERED`, `NOTIFICATION_READ` | Needed once the notification inbox (§3) exists, to let the same interaction-event pipeline (and downstream `behavior_signal`/`attribute_evidence` learning tables, which already FK into `interaction_event`) treat "did the user read this notification" as a behavior signal like any other, rather than inventing a second signal pipeline. |

## 3. Notifications

### 3.1 Decision: new `notification` schema, two tables, deliberately not merged with `matching.recommendation_delivery`

`matching.recommendation_delivery` already implements almost the exact shape the WAVE2E prompt
describes for notification delivery (`channel`, `delivery_status IN ('QUEUED','SENT','DELIVERED',
'FAILED','SKIPPED')`, `requested_at`, `delivered_at`, `provider_message_id`, `failure_reason`) — but
it is **hard-FK'd to `recommendation_session_id` + `match_result_id`, both `NOT NULL`**. It
structurally cannot represent `MEETING_REQUEST_STATUS`, `DOCUMENT_REVIEW_REQUIRED`,
`EVENT_OPERATION_NOTICE`, or any notification not tied to a specific recommendation result.
**Deliberate exception, recorded before implementation per AGENTS.md**: do not widen
`recommendation_delivery`'s FKs to nullable to make it generic — that table's whole design (see its
own docstring) assumes "one row per (result, channel, send attempt)" for recommendation fan-out
specifically, and loosening its FKs would weaken the referential-integrity guarantee the matching
pipeline currently relies on. Instead, define a new, structurally parallel pair of tables that reuse
the *same shape* (so `recommendation_delivery` is a direct template `matching.recommendation_delivery`
implementer can copy) under a new `notification` schema — additive, following the same precedent
`SCHEMA_KIOSK`/`SCHEMA_DOCUMENT` set when no existing schema fit a genuinely new domain.

Proposed tables (shapes only — no migration authored by this task):

**`notification.user_notification`** — one row per notification instance (the in-app inbox fact):

| Column | Type | Notes |
|---|---|---|
| `notification_id` | UUID PK | |
| `tenant_id`, `event_id` | UUID, FK `exhibition.event` | Standard tenant/event scoping convention. |
| `recipient_user_id` | UUID, FK `profile.user_account.user_id`, **NOT NULL** | Kiosk sessions have no persistent identity (`PROJECT_SCOPE.md` exclusion: "kiosk sign-up, kiosk long-term personalization") — **notifications are a registered-user-only surface by construction**, never addressed to a `guest_session_id` or `kiosk_session_id`. This is the mechanism that enforces that exclusion at the schema level, not just by convention. |
| `notification_type` | `String(60)`, `CheckConstraint` closed to the 9-value catalog in §3.2 | |
| `object_type` / `object_id` | nullable, free reference (not routed through `exhibition.recommendable`) | Same deliberate exception `document-structuring.md` §7 already recorded for `extracted_attribute`'s entity reference: a notification about a `MeetingRequest`, a `PartnerDocument`, or an admin `event_message` references entities that are not, and in some cases (a still-under-review document) structurally cannot be, rows in the `recommendable` registry (which is a registry of *approved, matchable* entities only). Cite that precedent rather than re-litigating it. |
| `relevant_version` | `String(50)`, nullable | Semantics vary per `notification_type` — see the dedup table in §3.2 for what it holds per type (e.g. `profile_version` for `PROFILE_CONFIRMATION_REQUIRED`, a document's `version_no` for `DOCUMENT_REVIEW_REQUIRED`). |
| `payload_json` | JSONB | Render data only — same allow-listing invariant as `interaction_event.context_json` (§1.1): no raw contact info, no free-text verbatim beyond what the notification is explicitly about. |
| `created_at` | `DateTime(timezone=True)`, `server_default=func.now()` | |
| `read_at` | `DateTime(timezone=True)`, nullable | |

Dedup constraint (§3.2's key, directly as a DB constraint, reusing the exact
`postgresql_nulls_not_distinct=True` pattern `profile.consent_policy` already uses for its own
composite uniqueness-with-nullable-columns constraint):

```
UniqueConstraint(
    "tenant_id", "notification_type", "recipient_user_id", "object_id", "relevant_version",
    name="uq_user_notification_dedup_key",
    postgresql_nulls_not_distinct=True,
)
```

**`notification.notification_delivery`** — one row per (notification, channel, send attempt),
structurally identical to `matching.recommendation_delivery` on purpose:

| Column | Type | Notes |
|---|---|---|
| `notification_delivery_id` | UUID PK | |
| `notification_id` | UUID, FK `notification.user_notification` | |
| `channel` | `String(20)`, `CheckConstraint IN ('IN_APP', 'EMAIL')` | **Closed, not open, unlike `recommendation_delivery.channel`** — see §3.4: SMS/push are explicitly not-built interface-only per `PROJECT_SCOPE.md`/the task instruction, so this CHECK should not silently accept a value nothing can ever send. Widen the CHECK the day SMS/push actually ships, not before. |
| `delivery_status` | `String(20)`, `CheckConstraint IN ('QUEUED','SENT','DELIVERED','FAILED','SKIPPED')` | Same closed set as `recommendation_delivery`, reused verbatim for consistency. |
| `provider_message_id`, `failure_reason` | nullable strings | Same as `recommendation_delivery`. |
| `requested_at`, `delivered_at` | timestamps, same `delivered_at >= requested_at` CHECK convention | |

### 3.2 Notification type catalog, dedup semantics, and source event

| `notification_type` | Fires on | `relevant_version` holds | Source (§2) |
|---|---|---|---|
| `PROFILE_CONFIRMATION_REQUIRED` | A profile attribute inferred from behavior needs explicit user confirmation (existing `profile.inferred_preference` confirm flow, `POST /profiles/{id}/inferences/{id}/confirm`) | `profile.user_profile.profile_version` at inference time | `MINIMUM_PROFILE_COMPLETED` / inference-created |
| `PERSONALIZED_RECOMMENDATION_READY` | A new `matching.recommendation_session` completes for the user | `recommendation_session_id` (used as the version discriminator — a new session is always a new notification, never re-deduped against an older one) | `RECOMMENDATION_IMPRESSION` (session-level, not per-item) |
| `EVENT_START_REMINDER` | Scheduled, ahead of `exhibition.event`'s start | event's own version/scheduling id if the event record is versioned; otherwise the event day | system/worker-originated, no interaction-event source |
| `SAVED_EXHIBITOR_UPDATED` | A favorited exhibitor/product/booth's approved data changes materially (needs `BACKEND-009` favorites + a change-detection hook on `exhibitor.py`'s `MASTER_APPROVAL_STATUSES`-gated tables) | the changed entity's own version/updated_at | — |
| `MEETING_REQUEST_STATUS` | `meeting.py`'s status machine transitions (`requested → accepted/counter_proposed/rejected/...`) | `meeting_request.row_version` (existing optimistic-lock column) | `MEETING_REQUEST_DECIDED` |
| `MEETING_TIME_REMINDER` | Scheduled, ahead of an accepted meeting's slot start | the `MeetingRequest` row's `row_version` at accept time | system/worker-originated |
| `DOCUMENT_REVIEW_REQUIRED` | A `partner_document` reaches `OPERATOR_REVIEW` (`document-structuring.md` §1) — addressed to operators, not the exhibitor | the document's `version_no` | proposed `DOCUMENT_REVIEW_SUBMITTED` (§2.3) |
| `CONTENT_REVIEW_RESULT` | A `partner_document`/extraction reaches `APPROVED`/`PUBLISHED`/`REJECTED` — addressed to the exhibitor | the document's `version_no` | proposed `DOCUMENT_APPROVED`/`DOCUMENT_REJECTED` (§2.3) |
| `EVENT_OPERATION_NOTICE` | An operator publishes an `event-message` (§5) | the `event_message_id` + its own `published_version` if it is ever edited-and-republished | admin-originated, no interaction-event source |

### 3.3 Naming: "event-message", not "campaign"

Per the task's explicit instruction, the admin broadcast tool (§5) and its resulting
`EVENT_OPERATION_NOTICE` notifications must be named `event-message`/`event_message` throughout —
endpoints, table names, error codes, UI copy this contract's language flows into. This is an
operations tool for event-day operational notices (delays, booth relocations, closures), not a
marketing/campaign platform, and PROJECT_SCOPE.md's exclusions (no CRM, nothing marketing-shaped)
make that distinction load-bearing, not cosmetic. Do not let an implementer rename it to
"campaign", "broadcast", or "blast" for familiarity with marketing-tool conventions.

### 3.4 Channel policy

| Channel | Status | Consent gate |
|---|---|---|
| `IN_APP` | Always available, cannot be disabled per notification type | None — this is the one channel every `notification_type` in §3.2 must always produce a `notification.user_notification` row for, regardless of any preference setting (§3.5). A user can mark it read, never "opt out of receiving it in the inbox". |
| `EMAIL` | Available only with explicit consent | Gated on an active `profile.user_consent` row against a `profile.consent_policy` with `purpose = 'NOTIFICATION_EMAIL'` (proposed convention value — `purpose` is a free string column today, no enum to extend, consistent with the existing `AGE_CONFIRMATION`/`PERSONALIZED_RECOMMENDATION` example values already documented in `consent.py`). If consent is absent, withdrawn, or expired (`effective_until` passed) at send time, silently skip the `EMAIL` `notification_delivery` row (`delivery_status = 'SKIPPED'`, `failure_reason = 'CONSENT_NOT_GRANTED'`) — never block the `IN_APP` row on it. |
| `SMS` / push | **Explicitly not built** — interface only | `notification_delivery.channel`'s CHECK constraint (§3.1) deliberately excludes these values today; the column exists so a future migration only needs to widen the CHECK, not add a column. Do not implement a send path for either in this wave. |

### 3.5 `GET/PATCH /me/notification-preferences`

Per-`notification_type` `EMAIL` toggle (not `IN_APP` — see §3.4, it cannot be disabled). Proposed
shape:

```
GET /api/v1/me/notification-preferences
{
  "preferences": [
    {"notification_type": "PERSONALIZED_RECOMMENDATION_READY", "email_enabled": true},
    {"notification_type": "EVENT_START_REMINDER", "email_enabled": false},
    ...
  ]
}
```

`email_enabled` for a type the user has never set defaults to `true` *if and only if* the underlying
`NOTIFICATION_EMAIL` consent (§3.4) is already granted — i.e., the preference is a secondary,
per-type fine-tune sitting on top of the coarse binary consent gate, not an independent opt-in.
This is a Blocker-Score-<7 default (reversible, no privacy/security dimension beyond what the
consent gate already enforces) — flag back to the user if `docs/`'s design intent differs once a
notification-preferences UI mock exists.

### 3.6 Endpoints

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/v1/me/notifications` | Cursor-paginated (reuse the existing `next_cursor` convention from `RecommendationSessionItemsResponse`), filterable by `notification_type`, `read`/`unread`. |
| `GET` | `/api/v1/me/notifications/unread-count` | Single integer — **not** subject to small-group suppression (§6): this is always exactly one user's own count, never an aggregate across users. |
| `POST` | `/api/v1/me/notifications/{id}/read` | Sets `read_at`; idempotent (setting an already-read notification to read again is a no-op success, not an error). |
| `POST` | `/api/v1/me/notifications/read-all` | Bulk, scoped to the caller only. |
| `GET` / `PATCH` | `/api/v1/me/notification-preferences` | §3.5. |

## 4. Admin analytics

### 4.1 Genuine data-source gap: no durable search history exists yet

`GET /admin/analytics/searches` and `GET /admin/analytics/no-results` need queryable history of what
was searched and whether it returned results. Today, `apps/api/app/services/search_sessions.py`'s
`SearchSessionStore` writes `SearchSessionRecord` (the query, category codes, and full
`SearchResponse`) to **Redis only**, with a TTL — by design (kiosk sessions must not accumulate
long-term data, per `PROJECT_SCOPE.md`), and nothing currently persists a durable, aggregable trace
of searches to Postgres. **Recommended resolution, consistent with §2.3's proposed `SEARCH_*`
events**: once `SEARCH_EXECUTED`/`SEARCH_ZERO_RESULT` land in `CANONICAL_EVENTS` and get emitted
into `interaction.interaction_event` (already durable, already partitioned, already has the BRIN
time index), the admin analytics mart derives `/admin/analytics/searches` and `/no-results` from
that — not from a new bespoke search-log table, and not from Redis. This keeps "kiosk stores nothing
long-term identifiable" intact (the event's subject is `guest_session_id`/`kiosk_session_id`, not a
raw query-to-person mapping held anywhere beyond the existing consent/PII-separation boundary) while
still making search analytics durable. Do not treat this as blocking — it's an explicit dependency
chain for whoever implements §4, not a reason to skip building the admin router.

### 4.2 Endpoints and their backing signal (informative — no migration authored here)

| Path | Backing source |
|---|---|
| `GET /api/v1/admin/analytics/overview` | Rollup across the below; `analytics` schema mart (reserved, zero tables today — this is where the first `analytics.*` table gets created). |
| `GET /api/v1/admin/analytics/web` | `interaction_event` filtered `source = 'WEB'` (§1.1) once that column exists; until then, filtered by `guest_session_id IS NULL AND user_id IS NOT NULL` as an interim proxy — document the proxy explicitly as temporary if used. |
| `GET /api/v1/admin/analytics/kiosk` | `interaction_event` filtered on the proposed `kiosk_session_id` (§1.1) — blocked on that column existing; interim proxy is `kiosk.kiosk_session` row counts alone (device/session counts, no behavior detail) until the FK lands. |
| `GET /api/v1/admin/analytics/buyer` | `matching.recommendation_session` / `match_result` filtered to buyer-tier subjects, per WAVE2C's finding that `/recommendations` already serves buyers — no new source needed. |
| `GET /api/v1/admin/analytics/searches` | §4.1. |
| `GET /api/v1/admin/analytics/no-results` | §4.1, filtered to the `SEARCH_ZERO_RESULT` event specifically. |
| `GET /api/v1/admin/analytics/data-quality` | New `quality.*` tables (schema reserved, zero tables today — first genuine use of `SCHEMA_QUALITY`). Recommended signal sources to aggregate, all already existing and none needing a new collection mechanism: `exhibitor.py`'s `MASTER_APPROVAL_STATUSES`/`REVIEW_STATUSES`/`PROFILE_APPROVAL_STATUSES` backlog counts (how much is stuck in `DRAFT`/pending review), `ai.ai_run.validation_status` distribution (`VALID`/`INVALID`/`REVIEW`/`FAILED` rates), `document-structuring.md`'s extraction `review_status` distribution (esp. `AI_INFERRED` rows awaiting operator judgment per that contract's §4), and `matching.filter_evaluation`/`filter_result` (existing hard-filter miss-reason records in `filtering.py`) for candidate-generation health. |

All six of `overview/web/kiosk/buyer/searches/no-results` plus `data-quality` return **breakdown
rows**, not just a single top-line number, and are therefore subject to §6's small-group
suppression rule on every row.

## 5. `event-message` operations tool

Not "campaign" — see §3.3. Draft → preview → publish → cancel lifecycle:

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/v1/admin/event-messages` | List, filterable by status. |
| `POST` | `/api/v1/admin/event-messages` | Creates a `DRAFT`. Body: `title`, `body`, target-segment definition (structured filter, not free SQL — reuse the same allow-listed-filter posture the rest of the API applies to user input). |
| `GET` | `/api/v1/admin/event-messages/{id}/preview` | Returns the **exact** matched-recipient count and a sample of the resolved segment. **Deliberately not subject to §6 small-group suppression** — an operator composing a message to a specific small segment needs the real count to judge whether the message is worth sending at all; suppressing it here would break the feature's purpose. This is a considered exception, not an oversight — contrast with §4's analytics *reporting* views, where the same underlying count, shown as a retrospective breakdown, must be suppressed. |
| `POST` | `/api/v1/admin/event-messages/{id}/publish` | `DRAFT/SCHEDULED → PUBLISHING → PUBLISHED`. Fans out `EVENT_OPERATION_NOTICE` (§3.2) to every matched recipient as a `notification.user_notification` row, `IN_APP` always, `EMAIL` per §3.4's consent gate — this is the one path that can create a large batch of notifications sharing the same `object_id` (`event_message_id`), which is exactly why the dedup key (§3.1) includes `object_id`: republishing the same message (see `relevant_version` in §3.2) does not double-notify a recipient who already got the prior version. |
| `POST` | `/api/v1/admin/event-messages/{id}/cancel` | `DRAFT/SCHEDULED → CANCELLED`. Terminal for that row; a corrected message is a new `event_message`, not a resurrected cancelled one — consistent with the "versioned, immutable published artifacts" invariant in AGENTS.md. |

## 6. Small-group statistical suppression

Binding rule (task instruction, and consistent with AGENTS.md's privacy invariant): **any aggregate
row in any admin analytics response (§4) whose underlying distinct-user count is fewer than 5 must
be suppressed or shown as "fewer than 5", never as an exact number** — this applies per-row, not
just to the top-level total (a breakdown table can have a healthy total with one thin row that must
still be individually suppressed). Proposed response shape so clients can render suppression
distinctly from a true zero:

```json
{"value": null, "suppressed": true, "underlying_count_floor": 5}
```

vs. an unsuppressed row:

```json
{"value": 12, "suppressed": false}
```

Applies to every breakdown dimension the admin analytics endpoints expose (by demographic/interest
segment, by kiosk device, by exhibitor, by time bucket where the bucket is narrow enough to isolate
individuals). Does not apply to `GET /me/notifications/unread-count` (§3.6, always exactly one
user's own data) or to `event-message` preview counts (§5, deliberate exception, operator targeting
their own send, not a retrospective report).

## 7. Cross-cutting bindings to existing invariants (explicit, per AGENTS.md)

- Kiosk sessions never receive notifications and are never a `notification.user_notification`
  recipient (§3.1) — the `recipient_user_id NOT NULL` FK enforces this at the schema level, not just
  by convention, directly supporting `PROJECT_SCOPE.md`'s "kiosk sign-up, kiosk long-term
  personalization" exclusion.
- Contact info gating (buyer/exhibitor business contact hidden until meeting acceptance + consent) is
  untouched by this contract — no notification payload (§3.1 `payload_json`) may carry raw contact
  fields; render notifications by reference (`object_id`) and let the client fetch the already-gated
  detail view, never inline PII into a notification row.
- Unapproved exhibitor/product data must never reach `SAVED_EXHIBITOR_UPDATED` notifications or
  `/admin/analytics/*` breakdowns keyed on non-`APPROVED` entities the way it must never reach public
  search/recommendation output — same `MASTER_APPROVAL_STATUSES` gate applies.
- AI hallucination-prevention (`AI must never assert a value the source text does not contain`) is
  not directly implicated by this contract (no AI output is minted here), but `data-quality`
  analytics (§4.2) is one of the surfaces meant to make hallucination-guard *failures* visible to
  operators — its `ai.ai_run.validation_status` signal is exactly that guard's output.
- Ontology concept codes: this contract introduces no new ontology concept codes. The event-name
  additions proposed in §2.3 are `event_type` catalog values (a separate, smaller, flat vocabulary
  the AI_SEARCH track owns), not concept codes from the 259-concept catalog — do not conflate the
  two when implementing.

## 8. Open items for the next implementer (BACKEND, once `BACKEND-007`/notification work is picked up)

1. Run `alembic heads` first (current chain tip was `0016_kiosk_session` as of the last verified
   state in `.harness/state.json` — re-verify, do not assume).
2. Add `SCHEMA_NOTIFICATION = "notification"` to `apps/api/app/db/base.py` (CONTRACTS-owned path —
   coordinate, this task did not edit it) and author the `notification.user_notification` /
   `notification.notification_delivery` tables per §3.1.
3. Add the four nullable columns to `interaction.interaction_event` per §1.1
   (`event_version`, `source`, `kiosk_session_id`, plus the mutual-exclusivity CHECK extension) —
   additive, does not touch existing rows' meaning.
4. Coordinate with AI_SEARCH to extend `CANONICAL_EVENTS` (§2.3) — this task cannot do so itself
   (`src/meet_ai/ontology/**` is AI_SEARCH-owned).
5. Build `apps/api/app/api/v1/routers/admin.py` if it still does not exist by the time this is
   picked up (re-check first — `BACKEND-007`/WAVE2D's document-review endpoints may have created it
   in the meantime; extend, do not duplicate, per the standing prior-art rule) covering §4's
   analytics group and §5's `event-message` group.
6. Build `apps/api/app/api/v1/routers/notifications.py` (new file, `/me/notifications*` per §3.6) —
   or fold into `profile.py` if that router's owner prefers keeping all `/me/*` surfaces together;
   either is compatible with this contract, the path shapes in §3.6 don't depend on file layout.
7. Add whatever error codes the real implementation throws to `.harness/contracts/error-codes.yaml`
   (not edited by this task — out of scope, per the same convention `WAVE2D-CONTRACTS.md` followed).
8. First real use of `analytics`/`quality` schemas (§4) — re-read their one-line docstrings in
   `db/base.py` before diverging from "derived data mart" / "data quality issues" as their intended
   contents.
