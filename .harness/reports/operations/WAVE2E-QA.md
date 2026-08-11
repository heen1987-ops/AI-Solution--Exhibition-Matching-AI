# WAVE 2E — QA-OPERATIONS report

Track: QA-OPERATIONS (WAVE 2E) · Date: 2026-08-03

Owned deliverables:

- `apps/api/tests/integration/test_operations_analytics_e2e.py` (new)
- `apps/api/tests/security/test_analytics_notification_privacy.py` (new)
- `.harness/reports/operations/WAVE2E-QA.md` (this file)

## Environment notes

No live PostgreSQL is reachable in this sandbox (`POSTGRES_TEST_DATABASE_URL` unset, no local
docker daemon) — same constraint every other QA track in this repo reports (see
`.harness/reports/buyer-matching/WAVE2C-QA.md`). This is also a **live multi-agent repo**: several
sibling tracks in this wave landed new files partway through this QA session, after this track's
initial exploration pass. The two test files' module docstrings note this explicitly and are
written against the *final* state described below, not the state when this session started.

Landing state at the end of this session (confirmed by direct inspection, not assumed):

| Domain | Model | Schema | Service | Router | Migration |
|---|---|---|---|---|---|
| event-collection | `app/models/interaction_event.py` | `app/schemas/interaction_event.py` | `app/services/interaction_event/*` | `app/api/v1/routers/interaction_event.py` (`build_interaction_event_router()`) | reuses existing `0008_matching_runtime` tables |
| aggregation | `app/models/analytics.py` | — | `apps/worker/app/jobs/analytics_aggregation.py`, `data_quality.py`, `cache_invalidation.py` | (worker job, no HTTP surface) | `0017_analytics_aggregation` |
| analytics-dashboard | — | `app/schemas/analytics.py` | `app/services/analytics/{access,suppression,tables,queries}.py` | `app/api/v1/routers/analytics.py` (`build_analytics_router()`) | none of its own (reads provisional tables — see Finding 2) |
| notification | `app/models/notification.py` | `app/schemas/notification.py` | `app/services/notification/{service,email_adapter}.py` | `app/api/v1/routers/notification.py` (`build_notification_router()`) | `0020_notification` |
| event-message | `app/models/event_message.py` | `app/schemas/event_message.py` | `app/services/event_message/{content,service,targeting,workflow}.py` | `app/api/v1/routers/event_message.py` (`build_event_message_router()`) | `0020_event_message` |

None of the five routers are wired into `app/api/v1/api.py` yet (every module exposes a
`build_*_router()` for the integrator, exactly per this repo's convention) — confirmed by reading
`api.py`, which this track did not touch, and by grep. No router edits `app/models/__init__.py`
either.

Per-endpoint reachability used by the tests below:

- **event-collection**: fully exercised over real HTTP (`TestClient` against a throwaway
  `FastAPI()` mounting only `build_interaction_event_router()` — never `app.main.app` or
  `app/api/v1/api.py`).
- **notification**: also fully exercised over real HTTP the same way. Its router was deliberately
  built to be testable without a live DB — `get_notification_service` is itself an overridable
  FastAPI dependency, so an `InMemoryNotificationRepository`-backed service can be swapped in with
  a plain `dependency_overrides` entry.
- **analytics-dashboard**: the role/authorization layer (`access.py`) and the buyer-breakdown
  scoping (`queries.get_buyer_analytics`) are exercised directly (no HTTP) — its route handlers
  call ~10 DB-querying helpers directly rather than through one overridable service, so a full
  HTTP round trip needs a live Postgres; recorded as a `pytest.skip` with that specific reason.
- **aggregation**: `apps/worker/app/jobs/analytics_aggregation.py` is pure/storage-agnostic and is
  loaded and called directly (loaded via `importlib.util` under a private module name — apps/api
  and apps/worker both use the top-level package name `app`, so a plain
  `import app.jobs.analytics_aggregation` cannot reach apps/worker's copy once apps/api's `app`
  package is already bound in `sys.modules`, which it is by the time these test files' own
  imports run).
- **event-message**: landed mid-session and was **not** named in this track's original prompt.
  Its pure `targeting.py` query builders (consent exclusion, small-audience suppression, segment
  allowlist) are directly relevant to priority checks 2 and 5 and are given light-touch coverage
  (7 tests). The full draft → approve → schedule → publish router/workflow surface is **not**
  covered — see "Coverage gaps" below.
- One `pytest.mark.postgres_integration` test is left as an explicit skip describing exactly what
  a live-DB run should additionally prove (real unique-constraint behavior under concurrency,
  which no fake can substitute for).

## Result summary

```
apps/api/tests/security/test_analytics_notification_privacy.py    54 passed, 1 xfailed
apps/api/tests/integration/test_operations_analytics_e2e.py       10 passed, 2 skipped
---------------------------------------------------------------------------------------
64 passed, 2 skipped, 1 xfailed
```

Full backend suite (`pytest apps/api/tests -q`): **711 passed, 2 failed (both pre-existing, not
introduced by this track — see "Bugs found in other tracks" below), 5 skipped, 7 xfailed**.

| # | Check | Evidence |
|---|-------|----------|
| 1 | Zero raw search-query-text/PII leakage in analytics output | 9 tests: `mask_search_query` regex coverage (email/phone/RRN/account-number shapes), length cap + control-char stripping, `redact_query_text`'s independent second pass, a full-pipeline test proving the *persisted* row (not just the pure function) never carries the raw string, and the rejection-ledger text-safety test. **1 confirmed bug found and pinned as a regression tripwire — see Finding 1.** |
| 2 | Zero optional-notification sent without consent | 5 notification tests (preference-only, consent-only, both-aligned, email-adapter-outage isolation, frequency-cap/operational-exemption) + 1 event-message test (EMAIL exclusion query is scoped to the *same* `NOTIFICATION_EMAIL` consent purpose the system pipeline uses, not a separate looser bar) |
| 3 | Zero cross-user notification access | 4 tests: in-memory-repository list/mark-read/mark-all-read scoping, a compile-level guard that the three production read `*_stmt` builders always filter by `recipient_user_id`, plus a real HTTP round trip (`POST /me/notifications/{id}/read` for another user's notification → 404, never data) |
| 4 | Zero kiosk user-identification | 9 tests: request-level `model_validator` rejection of WEB identity fields on a KIOSK batch (and vice versa) over both the schema layer and real HTTP, case/separator-insensitive forbidden-key matching, and a structural check that a KIOSK-sourced `InteractionEvent` row's subject columns are always NULL |
| 5 | Zero small-group (<5) statistic exposure | 10 tests: `suppress_metric`/`suppress_rate`/`drop_small_groups` boundary behavior (0 vs 1–4 vs ≥5), a DB-level CHECK-constraint backstop test across all three `analytics.*` model tables, a repeat-actor aggregation test, and 1 event-message test pinning `SMALL_AUDIENCE_THRESHOLD` to the same repo-wide `5` |
| 6 | Event dedup/aggregation consistency (no double counting) | 5 tests: HTTP-level dedup replay (`DUPLICATED`, zero new rows), same-id-different-payload rejection (`IDEMPOTENCY_CONFLICT`, never silently overwritten), pure-function idempotent re-aggregation (identical input → identical output, twice), and a repeat-actor distinct-count test |
| 7 | Zero competitor-detail-stat leakage to EXHIBITOR_ADMIN | 6 tests: full endpoint-gating matrix (only `buyer` reachable, all 6 others denied), escalation-attempt rejection for all three staff-only roles, a `NO_ROLE_ASSIGNED`/`INSUFFICIENT_ROLE` test for VISITOR/BUYER/no-role actors, an `inspect.signature` guard that `resolve_analytics_access` accepts no client-suppliable `exhibitor_id` at all, and — once `queries.py` landed mid-session — a direct test of the real `get_buyer_analytics`: `breakdown` is `[]` on every branch and an exhibitor-scoped call returns fully masked metrics without querying anything |

## Finding 1 — CONFIRMED bug: context-field PII is not masked, only `search_query` is

**Severity: HIGH** (directly the #1 priority check for this track).

`app/services/interaction_event/masking.py::sanitize_context` allow-lists *keys* for the
free-form `context` dict but never runs `mask_search_query`'s PII regexes over the *values* of
allow-listed string keys (e.g. `referrer_screen`, `zone`, `filter_code` — all free strings up to
200 chars). Only the dedicated `search_query` field is masked. A client that puts a phone number
or email into any allow-listed string field survives verbatim into
`interaction.interaction_event.context_json`, and from there — once WORKER-ANALYTICS's
aggregation is pointed at real `interaction_event` data instead of synthetic fixtures — into
analytics output.

Reproduced and pinned as `test_allowlisted_context_string_values_are_not_yet_pii_redacted` in
`test_analytics_notification_privacy.py`, marked `xfail(strict=True)`: it passes today (proving
the leak exists) and will start **failing the suite** (XPASS) the moment someone fixes
`sanitize_context` to redact allow-listed string values too — at which point the xfail marker
should be deleted. Recommended fix (for the BACKEND-EVENT-COLLECTION track, `app/services/
interaction_event/masking.py`, not in this track's owned paths): run the same
email/phone/RRN/account-number regex pipeline `mask_search_query` already has over every
allow-listed string value in `sanitize_context`, not only `search_query`.

## Finding 2 — Two sibling tracks built two different `analytics.*` schemas

**Severity: MEDIUM, appears self-resolving.** `app/models/analytics.py` (WORKER-ANALYTICS, real
ORM tables published via the `0017_analytics_aggregation` migration:
`analytics.daily_metric` / `analytics.funnel_metric` / `analytics.search_no_result_summary` /
`analytics.data_quality_snapshot`) and `app/services/analytics/tables.py` (BACKEND-ANALYTICS, a
**private, non-`Base.metadata`** set of plain `Table` objects with a different, more granular
shape: `overview_daily_snapshot`, `web_engagement_daily`, `kiosk_session_daily`,
`buyer_match_daily`, `search_query_daily`, `data_quality_daily`) describe the same schema
differently. `tables.py`'s own docstring already flags this as a known, deliberately-isolated
placeholder ("the real `analytics.*` tables have not landed anywhere in the repo yet ... when
WORKER-ANALYTICS lands the real tables, reconcile column names here"). By the end of this
session `queries.py` (which was written against `tables.py`, not `app/models/analytics.py`) had
also landed and the whole read path compiles and is exercised in this report's tests — but it is
still built against the placeholder shape, not the real migrated one. **Recommendation**: the
integrator/CONTRACTS should diff `app/services/analytics/tables.py`'s six tables against
`app/models/analytics.py`'s four before `G2_FEATURE_COMPLETE` closes, and either reconcile the
column names (per `tables.py`'s own stated plan) or replace `tables.py` with real
`app/models/analytics.py`-backed queries.

## Coverage gaps (explicitly recorded, not silently skipped)

1. **event_message router/workflow state machine** — `app/api/v1/routers/event_message.py` (draft
   → approve → schedule → publish → complete/cancel, `EventMessageRecipient` persistence,
   duplicate-target warnings) landed mid-session and was not named in this track's original
   prompt. Only its pure `targeting.py` query builders (consent exclusion, small-audience
   suppression, segment allowlist) got coverage in the time available — 7 tests, all passing. The
   full state machine and its interaction with `notification.notifications` (does a published
   `EventMessage` actually reach `NotificationService`, or is IN_APP delivery for event-messages a
   separate code path?) is unverified. **Recommended next QA pass**: a dedicated
   `test_event_message_workflow.py` exercising the router end to end with an in-memory session,
   plus a consent/small-group test suite mirroring this file's sections 2/5 but for the actual
   `EventMessageRecipient` persistence path (this report's targeting-level tests only prove the
   *query* is correctly scoped, not that the router always calls it before every EMAIL send).
2. **`GET /admin/analytics/*` full HTTP round trip** — recorded as a `pytest.skip` with the exact
   reason (no live Postgres; the router's ~10 DB-querying helpers aren't behind one overridable
   dependency the way the notification router is). The role/authorization layer and the
   buyer-breakdown scoping those routes rely on are proven directly instead.
3. **Live-Postgres round trip** — one `pytest.mark.postgres_integration` test documents exactly
   what a real run should additionally prove (real unique-constraint behavior for
   `client_event_id`/dedup and `uq_notifications_dedup_key` under actual concurrency, which no
   fake session can substitute for).

## Bugs found in other tracks' code (observed while running the full suite for regression safety)

Not introduced by this track — confirmed via `git status --porcelain apps/api/tests` before/after
this track's own edits: only the two files under this report's OWNED PATHS were added.

1. **HIGH — the Alembic migration chain is now 7-way fragmented (was 4 at the last QA pass).**
   `alembic heads` on this tree resolves to 7 heads: `0017_analytics_aggregation`,
   `0017_buyer_match`, `0017_document_storage`, `0017_exhibitor_preference`, `0018_buyer_profile`,
   `0020_event_message`, `0020_notification` — none chains onto a single line back to
   `0016_kiosk_session`. This is the same class of issue `.harness/reports/buyer-matching/
   WAVE2C-QA.md` already flagged at 4 heads; it has gotten worse, not better, across waves, which
   suggests the "one Change Request per shared-contract edit" rule is not being followed for new
   Alembic revisions. Evidence: `apps/api/tests/test_exhibitor_models.py::
   test_alembic_chain_has_one_published_head` fails with
   `assert [...7 heads...] == ['0016_kiosk_session']`. **Recommendation**: unblock
   `G2_FEATURE_COMPLETE` by having the integrator pick one canonical linear ordering (or an
   explicit merge revision) for all 7 heads before any more migrations land on top of any of them.
2. **MEDIUM — related test-contract drift, also worse than last pass.**
   `test_metadata_contains_published_supply_and_filter_tables` now expects `93` published tables
   but the real count (once every model module currently in the repo is imported) is well past
   that — a direct consequence of finding 1 above: new tables keep landing without that contract
   test's expected count being updated. This count is also sensitive to *which* test modules get
   collected in the same pytest session (whichever ones happen to import a given new model module
   first) — a bystander instability worth the CONTRACTS track being aware of when re-baselining
   this number, not a bug in this track's own files.
3. **INFO — the document-download-token failures reported by the last full-suite run of this
   session's *earlier* pass (`test_download_token_round_trip_then_expiry_and_tampering_are_both_
   rejected` and two siblings in `test_document_security.py`, all `422` instead of `200`) were
   gone by the time of this report's final full-suite run** — resolved by a concurrent track
   between this session's two full-suite runs, not by this track. Noted for the record only; no
   action needed.

## Confirmation of absolute prohibitions

- Did not edit `apps/api/app/api/v1/api.py`, `apps/api/app/models/__init__.py`,
  `apps/user-web/lib/api-client.ts`, or `apps/user-web/lib/types.ts`.
- Did not edit any file outside this track's OWNED PATHS — verified via
  `git status --porcelain apps/api/tests`: only the two new test files plus this report exist
  under this track's paths.
- No new DB migration was added by this track (test-only track; no model/schema changes).
- No kiosk anonymity, contact-sharing, consent, or approval-gate rule was weakened — this track's
  entire purpose was to add tests proving those rules hold (and, in Finding 1's case, to prove and
  pin one place they currently do not), without modifying the production code under test.
- No ontology concept codes were invented or used by this track's fixtures.
- Small-group statistics: this track's tests themselves never surface exact small-group figures;
  every fixture that generates fewer than 5 distinct actors asserts the value comes back masked
  (`suppressed=True`, `value=None`), never an exact number.
