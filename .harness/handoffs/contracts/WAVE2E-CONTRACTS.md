# WAVE2E-CONTRACTS handoff — interaction events, notifications, admin analytics/operations

Track: CONTRACTS-OPERATIONS (WAVE 2E). Owned paths: `.harness/contracts/operations-analytics.md`
(new), `.harness/handoffs/contracts/WAVE2E-CONTRACTS.md` (this file, new). This run touched only
those two paths — no `apps/**`, no migrations, no `.harness/state.json`/`backlog.yaml`/`locks.yaml`.

Purpose: WAVE 2E workers (and anyone implementing `BACKEND-007` or a future notifications task) may
not read this before starting, but should check it before finishing to avoid duplicating already-
shipped work or re-deciding something already decided here.

## TL;DR for other agents touching this area

**Most of the "event envelope" the WAVE2E prompt asked for already exists**, shipped as part of the
matching/behavior-learning pipeline, under the flat `apps/api/app/**` layout (not
`apps/api/src/modules/**` — see `.harness/assumptions.md` ASSUMPTION-003). Before writing any new
event/notification/analytics table or router:

1. `apps/api/app/models/matching.py::InteractionEvent`
   (`interaction.interaction_event`, partitioned by `event_date`, append-only) — **this is the event
   envelope.** Extend with new nullable columns (§1.1 of the contract snapshot), do not create a
   parallel table.
2. `apps/api/app/api/v1/routers/recommendations.py`'s `POST /interactions/batch` — **this is the
   batch ingestion endpoint** the prompt's `POST /events/interaction/batch` describes. Do not build
   a second one.
3. `src/meet_ai/ontology/catalog.py::CANONICAL_EVENTS` — **this is the event-name catalog**, a live,
   enforced, 20-member closed set, AI_SEARCH-owned. Extend it (coordinate with that track), do not
   invent a parallel dot-namespaced vocabulary that the ingestion endpoint won't even accept
   (`event_type not in CANONICAL_EVENTS` is a hard reject today).
4. `apps/api/app/models/matching.py::RecommendationDelivery`
   (`matching.recommendation_delivery`) — the closest existing thing to a "notification delivery"
   table, but hard-scoped to recommendation results. **Do not widen its FKs to make it generic** —
   copy its shape into a new `notification.notification_delivery` table instead (contract snapshot
   §3.1 has the exact deliberate-exception reasoning).
5. No admin router, no notification inbox, and no durable search-history store exist anywhere yet —
   these are the genuine gaps this contract actually defines net-new (§3, §4, §5 of the snapshot).

Full detail, field-by-field mapping, and exact source citations:
[`.harness/contracts/operations-analytics.md`](../../contracts/operations-analytics.md).

## Prior art checked before writing this

- `apps/api/app/models/matching.py` — `InteractionEvent` (event envelope), `InteractionClientEventDedupe`
  (offline resend dedup), `RecommendationDelivery` (nearest existing "notification-shaped" table).
- `apps/api/app/schemas/recommendation.py` — `InteractionEventIn`/`InteractionBatchRequest`/
  `InteractionBatchResponse`/`Envelope`/`Meta` (the existing response envelope, reused for
  `event_context.request_id` correlation instead of adding a redundant column — see contract §1.1).
- `apps/api/app/api/v1/routers/recommendations.py` — the live `POST /interactions/batch` handler,
  including its `client_event_id` dedup logic and its `CANONICAL_EVENTS` import/enforcement.
- `src/meet_ai/ontology/catalog.py` — `CANONICAL_EVENTS` (read in full; all 20 members quoted in the
  contract snapshot §2.1) and `Catalog._validate_events`'s cross-check against `event_mappings`.
  Confirmed via `.harness/locks.yaml` that `src/meet_ai/ontology/**` is AI_SEARCH-owned, not
  CONTRACTS-owned — did not edit it.
- `apps/api/app/models/kiosk.py` — `KioskSession.kiosk_id` (string device code, not a UUID) and
  confirmed `kiosk.kiosk_session` has zero FK relationship to `interaction.interaction_event` today
  (the genuine gap behind `/admin/analytics/kiosk` having no reliable per-event kiosk attribution).
- `apps/api/app/services/search_sessions.py` — confirmed `SearchSessionStore` is Redis-only, TTL-
  bound, not a durable analytics source (the gap behind §4.1 of the contract snapshot).
- `apps/api/app/models/consent.py` — `ConsentPolicy.purpose`/`UserConsent.source_channel` (existing
  free-string consent-purpose convention and its own, narrower `WEB/QR/KIOSK` channel enum — checked
  to confirm it should *not* be reused/widened for the event envelope's `source` field; see contract
  §1.1's deliberate-exception note on why the two enums stay separate).
- `apps/api/app/db/base.py` — full schema list and its one-line docstrings per schema (`analytics` =
  "운영 DB에서 파생한 데이터마트" / operations-derived data mart; `quality` = "데이터 품질 이슈" /
  data quality issues) — both reserved, zero tables registered in `models/__init__.py` today. Used
  as the intended backing schemas for §4's admin analytics rather than inventing new schema names.
- `.harness/contracts/document-structuring.md` (WAVE2D) — the 15-status document/extraction review
  state machine `DOCUMENT_REVIEW_REQUIRED`/`CONTENT_REVIEW_RESULT` map onto (contract snapshot §3.2),
  and its already-recorded "entity_reference polymorphism" deliberate exception, cited rather than
  re-litigated for `notification.user_notification.object_id`.
- `.harness/contracts/buyer-matching.md` (WAVE2C) — confirmed `/recommendations` already serves
  buyers (`user_type=BUYER`), so `/admin/analytics/buyer` needs no new data source, and the proposed-
  but-not-yet-built `POST /buyer/compare` is where a future `BUYER_COMPARE_VIEWED` event would attach.
- `apps/api/app/models/exhibitor.py` — `MASTER_APPROVAL_STATUSES`/`REVIEW_STATUSES`/
  `PROFILE_APPROVAL_STATUSES` — the existing approval-backlog signal `/admin/analytics/data-quality`
  should aggregate, rather than inventing a second status-tracking mechanism.
- `apps/api/app/models/ai.py`, `apps/api/app/models/filtering.py` — `AiRun.validation_status` and
  `FilterEvaluation`/`FilterResult` as further existing `data-quality` signal sources.
- `.harness/contracts/openapi.json` (grepped all `paths` keys) and `.harness/contracts/error-codes.yaml`
  — confirmed no `/me/notifications*`, no `/admin/analytics/*`, no `/admin/event-messages*` exist
  today, and that `error-codes.yaml` already flags `"admin router (BACKEND-007 대기)"` as
  not-yet-cataloged — consistent with this contract's own finding.
- `.harness/state.json`, `.harness/backlog.yaml`, `.harness/decisions.md`, `.harness/assumptions.md`
  (ASSUMPTION-003), `.harness/risks.md`, `AGENTS.md`, `PROJECT_SCOPE.md` — read in full per the
  mandatory pre-task checklist. No existing backlog task id matches "CONTRACTS-OPERATIONS"/"WAVE 2E"
  verbatim (this track's prompt is external/Codex-originated, same category as WAVE2C/2D — see
  ASSUMPTION-003's framing of "외부(Codex) 프롬프트"), so this handoff does not flip any
  `backlog.yaml` status; a FOUNDATION-track pass should fold `BACKEND-007`'s scope note to reference
  this contract once this is merged.

## Decisions made (Blocker Score < 7, applied the safest reversible default per the standing rule)

1. **Extend `interaction.interaction_event` rather than create a parallel envelope table.** Reversible
   (additive nullable columns only), low impact, no privacy/security dimension — not escalated.
   Contract snapshot §1.1.
2. **Keep the flat `SCREAMING_SNAKE_CASE` `CANONICAL_EVENTS` naming instead of adopting the prompt's
   dot-namespaced `DOMAIN.ACTION` style.** The dot-namespace convention *is* used elsewhere in this
   codebase (ontology concept codes, `CODE_PATTERN` in `catalog.py`), which made this worth
   double-checking rather than assuming — but `CANONICAL_EVENTS` itself, the thing actually enforced
   on the ingestion endpoint, has never used it. Renaming a live, tested, enforced 20-member set for
   style consistency alone is exactly the kind of low-value churn the "check for prior art" rule
   exists to prevent. Reversible (a pure string-value renaming, if ever wanted, doesn't change any
   table shape), no privacy/security dimension — not escalated.
3. **New `notification` schema and two new tables (`user_notification`, `notification_delivery`)
   rather than widening `matching.recommendation_delivery`'s FKs to nullable.** Widening a shipped
   table's FKs to accommodate a new use case it wasn't designed for would weaken an existing
   referential-integrity guarantee for zero benefit (the new tables can just copy its shape). Also
   genuinely reversible either way (no migration was actually authored by this task), so the choice
   itself carries no execution risk yet — not escalated.
4. **`recipient_user_id` on `user_notification` is `NOT NULL`, no guest/kiosk recipient path.** This
   is the one decision in this run closest to touching a privacy/scope invariant
   (`PROJECT_SCOPE.md`'s kiosk exclusions) rather than a pure naming/structure choice — but it is not
   actually ambiguous: nothing in the task prompt or existing docs suggests kiosk sessions should
   ever receive notifications, and the exclusion list is explicit ("kiosk sign-up, kiosk long-term
   personalization"). Applying the exclusion as a schema-level `NOT NULL` (rather than leaving it as
   an unenforced convention some future endpoint could quietly violate) is the safer reversible
   default, not a new policy decision — not escalated to Blocker Score ≥ 7.
5. **`notification_delivery.channel` CHECK is closed to `('IN_APP', 'EMAIL')`**, unlike
   `recommendation_delivery.channel` which is deliberately left open (no CHECK, per that table's own
   docstring, because "6단계 온톨로지가 없어" — no standardized channel ontology exists yet). Chose
   closed here specifically because the task instruction is explicit that SMS/push are "explicitly
   NOT built — interface only" for *this* feature, a stronger and more specific statement than
   `recommendation_delivery`'s general "no ontology yet" reasoning. Reversible (widen the CHECK when
   SMS/push actually ship) — not escalated.
6. **Admin `event-message` preview counts are exempt from small-group suppression; analytics
   breakdown rows are not.** Documented explicitly as a considered distinction (contract §5, §6)
   rather than picking one rule and letting the other surface silently violate it. Both readings are
   defensible from the task instruction alone (it names the suppression rule once, generically); this
   is a judgment call about *where* a single stated rule applies, not a fabricated new rule — kept as
   a recommendation for the implementer to confirm rather than presented as immutable.

None of the above met Blocker Score ≥ 7 (no high-impact + hard-to-reverse + privacy/security-risk
combination with zero evidence in existing docs), so none required stopping for user input. Recorded
here per the standing assumption-logging convention, mirroring `WAVE2D-CONTRACTS.md`'s format —
self-contained within this handoff and the contract snapshot rather than added to the shared
`.harness/assumptions.md` (these are contract-drafting judgment calls scoped to this domain, not
project-wide assumptions another unrelated track would need to discover independently).

## Genuine gaps found (confirmed absent, not just renamed) — table for quick scanning

| Gap | Where documented | Suggested owner |
|---|---|---|
| Notification inbox (`GET /me/notifications`, read/unread, preferences) — nothing exists at all | `operations-analytics.md` §3 | BACKEND, new `notifications.py` router or folded into `profile.py` |
| Durable, queryable search history for admin analytics — `SearchSessionStore` is Redis/TTL only | `operations-analytics.md` §4.1 | BACKEND + AI_SEARCH (needs `SEARCH_*` events landed in `CANONICAL_EVENTS` first) |
| Admin router entirely | `operations-analytics.md` §4, §5 | BACKEND (`BACKEND-007`, currently `READY`) |
| `event_version`, `source`, `kiosk_session_id` columns on `interaction_event` | `operations-analytics.md` §1.1 | BACKEND/CONTRACTS migration author |
| `SEARCH.*`, `FAVORITE.*`, kiosk-session-lifecycle, `BUYER.*`, `DOCUMENT.*` event-catalog members | `operations-analytics.md` §2.3 | AI_SEARCH (`src/meet_ai/ontology/catalog.py` owner) |
| `analytics`/`quality`/`notification` Postgres schemas — reserved or proposed, zero tables | `operations-analytics.md` §4.2, §3.1 | BACKEND/CONTRACTS migration author |

## Value/naming mismatches worth knowing before writing client or test code

- The prompt's envelope field `event_name` is the existing `event_type` column/field — not renamed,
  just documented as the same concept under two names. Don't search for a literal `event_name`
  column or Pydantic field anywhere; it doesn't exist and isn't planned to.
- The prompt's `event_context.user_id_hash` does not exist and should not be built — the existing
  table already resolves subject identity via a proper nullable FK (`user_id` XOR `guest_session_id`,
  soon XOR `kiosk_session_id`), which is a stronger pattern than a hash sitting in a hot table. See
  contract §1.2.
- `POST /events/interaction` (singular) has no existing equivalent and is optional/thin-wrapper only
  — the batch endpoint already accepts a single-element array. Don't build a second ingestion code
  path for it.
- "event-message", never "campaign" — see contract §3.3. This is a naming requirement stated
  explicitly in the task, not a style preference; downstream code, tests, and copy should all match.

## Absolute-prohibition self-check for this run

- Did not edit `apps/api/app/api/v1/api.py`. ✅ (never opened it for writing.)
- Did not edit `apps/api/app/models/__init__.py`. ✅
- Did not edit `apps/user-web/lib/api-client.ts` or `.../types.ts`. ✅ (never touched
  `apps/user-web/**` at all.)
- Did not touch any other track's owned paths. ✅ — only wrote
  `.harness/contracts/operations-analytics.md` and this handoff file. Read-only exploration of
  `apps/api/app/models/**`, `apps/api/app/api/v1/routers/**`, `apps/api/app/services/**`,
  `apps/api/app/schemas/**`, `src/meet_ai/ontology/catalog.py`, `.harness/contracts/**`; zero writes
  outside the two owned paths.
- Did not touch `database/migrations/**`, `apps/api/alembic/**`, or any other `apps/**` code — no
  migration authored, no model/router/schema/service file created or modified. Contracts only, as
  instructed.
- No new ontology concept codes invented — the contract only proposes new `event_type` *catalog*
  members (§2.3) as a recommendation for the AI_SEARCH track to apply to `catalog.py`, and does not
  itself edit that file or `catalog.v1.json`, and never touches the 259-concept catalog namespace at
  all.
- Kiosk PII/scope invariant: reinforced, not weakened — `notification.user_notification` is designed
  with a `NOT NULL` registered-user-only recipient FK specifically so kiosk sessions structurally
  cannot become notification recipients (§7 of the contract snapshot states this explicitly).
- Contact-info gating: explicitly restated as a binding rule on notification payloads (§7) — no
  notification may inline raw contact fields; render by reference only.
- Unapproved-data gating: explicitly restated (§7) — admin analytics and `SAVED_EXHIBITOR_UPDATED`
  notifications must respect the same `MASTER_APPROVAL_STATUSES` gate as public search/recommendation
  output.
- AI-hallucination-prevention invariant: not directly implicated (no AI output minted here); noted in
  §7 that `data-quality` analytics is a surface for *observing* that guard's existing signal
  (`ai.ai_run.validation_status`), not a new instance of the guard itself.
- Small-group statistics suppression: this is the one domain area where this rule is directly
  load-bearing — defined precisely (§6 of the contract snapshot), including the one considered
  exception (`event-message` preview counts, §5) and why it's an exception rather than a violation.
