# WAVE 2C — QA-BUYER report

Track: QA-BUYER (WAVE 2C) · Date: 2026-08-02

Owned deliverables:

- `apps/api/tests/integration/test_buyer_meeting_e2e.py` (new)
- `apps/api/tests/security/test_buyer_meeting_privacy.py` (new)
- `.harness/reports/buyer-matching/WAVE2C-QA.md` (this file)

## Environment notes

No live PostgreSQL was reachable in this sandbox: `POSTGRES_TEST_DATABASE_URL` is unset and
`docker ps` cannot reach a daemon (`failed to connect to the docker API at
npipe:////./pipe/dockerDesktopLinuxEngine`). All tests below therefore drive the **real**
FastAPI router coroutines in `app/api/v1/routers/meetings.py` and the **real** production
scoring/filter functions in `app/services/matching/{hard_filter,feature_builder}.py` directly
(no reimplementation of business logic), backed by a small scripted `AsyncSession` fake whose
call order was traced line-by-line from each router function — the same convention this repo's
own `test_recommendation_api.py` / `test_search_api.py` already use. A genuine Postgres-backed
round trip is included and gated on `POSTGRES_TEST_DATABASE_URL` (skipped here, ready for CI),
matching the existing `test_postgres_recommendation_contract.py` pattern.

Prior art found and reused rather than duplicated (per this track's instructions): the buyer
meeting domain (`apps/api/app/models/meeting.py`, `apps/api/app/api/v1/routers/meetings.py`,
`apps/api/app/schemas/meeting.py`) was already fully implemented by the BACKEND-MEETING track
by the time this session ran, as was the hard-filter/feature-builder pipeline
(`apps/api/app/services/matching/*`) and the recommendations/partner routers. No new
production code was written — this track is test-only per its OWNED PATHS.

## Result summary

45 new test functions across the two owned files; 44 pass, 0 fail, 1 explicitly skipped
(pending a live DB). `pytest -q` output:

```
apps/api/tests/security/test_buyer_meeting_privacy.py     35 passed
apps/api/tests/integration/test_buyer_meeting_e2e.py       9 passed, 1 skipped
--------------------------------------------------------------------
44 passed, 1 skipped in ~2s
```

| # | Check | Tests | Pass | Fail | Skip |
|---|-------|------:|-----:|-----:|-----:|
| 1 | Zero contact-info exposure before acceptance + consent | 5 | 5 | 0 | 0 |
| 2 | Zero cross-buyer / cross-exhibitor data access | 5 | 5 | 0 | 0 |
| 3 | Zero unverified-buyer meeting requests succeeding | 5 | 5 | 0 | 0 |
| 4+5+6 | Hard filters / approval gating / UNKNOWN handling (one shared test block — several tests, e.g. the mixed-batch test, deliberately exercise more than one of these three at once) | 13 | 13 | 0 | 0 |
| 7 | Meeting status transitions never skip states illegally | 7 | 7 | 0 | 0 |
| — | Journey/contract scaffolding (route inventory, hop-by-hop E2E walk, live-DB placeholder) | 10 | 9 | 0 | 1 |
| **Total** | | **45** | **44** | **0** | **1** |

Full backend suite (`pytest apps/api/tests -q`, excluding one pre-existing collection error
documented below): **258 passed, 3 failed (pre-existing, not introduced by this track), 3
skipped**.

## What each check actually exercises

**1. Contact exposure gating** — calls the real `get_partner_buyer_summary` coroutine with
scripted session states for: status `requested` (not yet accepted), status `accepted` with no
`MeetingContactShare` row, a `MeetingContactShare` row with `accepted_at is None`, and the
positive control (accepted + consented) which also asserts the audit log (`AuditLog`,
`action_type="VIEW"`, `reason_code="PARTNER_BUYER_CONTACT_VIEW"`) is written exactly once and
never duplicated on a second view.

**2. Cross-buyer / cross-exhibitor isolation** — a buyer cannot `GET`/`cancel` another buyer's
meeting (404 `RESOURCE_FORBIDDEN`, not a leaking 403); exhibitor staff from participation A
cannot read or decide on a meeting belonging to participation B; an `active=False` staff row is
treated as unauthenticated (401), covering offboarded partner accounts.

**3. Unverified buyer requests** — `create_meeting` is called with: no `X-Profile-Id` at all
(and the fake session raises `AssertionError` if the router touches the DB before the
auth-required 401 — it does not), a linked `UserAccount` whose `authentication_state` is
`GUEST` (not `PHONE_VERIFIED`/`ACCOUNT_AUTHENTICATED`), a profile with no linked account at
all, a soft-deleted profile, and a `GENERAL_VISITOR` profile trying to submit a buyer meeting.
All five are rejected before a meeting row is ever created.

**4/5/6. Hard filters, approval gating, UNKNOWN handling** — these call
`hard_filter.evaluate_hard_filters` **directly** (the real production entry point, not a test
double) with hand-built `MatchCandidate`/`ResolvedProfile`/`ResolvedContext` objects: an
unapproved exhibitor, a cancelled participation, a below-MOQ candidate, and — the check this
track was specifically asked to prioritize — a candidate whose `oem_status`/`export_status` is
`"UNKNOWN"` against a buyer profile whose goal *requires* OEM/export capability. The assertion
is that `UNKNOWN` passes (is not treated as `NO`), while an explicit `"NO"` on the same
candidate is rejected — proving the engine distinguishes "not yet declared" from "declined",
matching `hard_filter.py`'s own `== "NO"` (never `!= "YES"`) comparisons and
`feature_builder._AVAILABILITY_STATUS_SCORE["UNKNOWN"] = None` (component dropped, not
defaulted to a guessed score). A mixed-batch test confirms an unapproved candidate never rides
along in the eligible list next to valid ones. A source-inspection test also pins
`candidate_generator._load_supply_profiles`'s default trade-profile values to `"UNKNOWN"`
(never `"NO"`) as a regression guard on the data-loading layer feeding the filters.

**7. Status-machine integrity** — `record_meeting_outcome` (the only path to `completed`) is
called against a meeting still in `requested`, proving `REQUESTED -> COMPLETED` cannot happen
in one step (409 `MEETING_CONFLICT`, meeting left unchanged); `decide_meeting(ACCEPT)` against
an already-`accepted` meeting is rejected (no double-accept/replay); cancelling a `completed`
meeting is rejected (terminal state protected); and the router's own state tables
(`_DECIDABLE_SOURCE_STATUSES`, `_OUTCOME_ALLOWED_SOURCE_STATUSES`,
`_BUYER_CANCELLABLE_STATUSES`) are statically audited to confirm no terminal/initial status is
ever listed as a valid decision/outcome source.

**Journey (`test_buyer_meeting_e2e.py`)** — walks hop 1 (buyer creates a meeting with contact
consent) → hop 2 (exhibitor accepts) → hop 3 (buyer summary now reveals contact) → hop 4
(exhibitor records outcome, meeting completes) → hop 5 (aggregate transition-sequence check
against the documented state graph), plus a route-inventory test and a test pinning that the
redesign doc's separate `/buyer/matches`/"compare" endpoints were intentionally mapped onto the
existing `/recommendations` + `/recommendation-sessions/{id}/items` pair (DECISION-005 in
`.harness/decisions.md`) rather than duplicated — so a future track reintroducing a parallel
`/buyer/matches` route (which would bypass the hard-filter/approval pipeline tested above) would
be caught by this test failing on route inventory.

## Skipped tests (with reasons — left in place as a checklist per this task's instructions)

- `test_live_postgres_buyer_meeting_round_trip` (`apps/api/tests/integration/test_buyer_meeting_e2e.py`,
  marked `pytest.mark.postgres_integration`): skipped because `POSTGRES_TEST_DATABASE_URL` is
  not configured in this sandbox. Its docstring specifies exactly what the integrator should
  seed and assert (tenant/event/exhibitor/participation/availability_slot/profile/
  user_account/consent_policy rows, then a real `TestClient` walk of
  `POST /meetings -> POST /partner/meetings/{id}/decision -> GET .../buyer-summary ->
  POST .../outcome`) — this is the only way to actually prove the `EXCLUDE`-constraint
  double-booking guard and the conditional-`UPDATE` slot reservation are correct, since no fake
  can verify real constraint behavior.

No other track's endpoint was missing from this run — by the time this session executed,
`meetings.py`, `recommendations.py`, and `partner.py` were already fully landed, so nothing
else needed a "target endpoint not found yet" skip.

## Bugs found in other tracks' code (observed while running the full suite for regression safety)

These were **not** introduced by this QA-BUYER track (git status confirms this track only added
the three files above); they are pre-existing/concurrent issues surfaced by running
`pytest apps/api/tests -q` for the "confirm you have not broken anything pre-existing" step.

1. **HIGH — fragmented Alembic migration chain (4 unmerged heads).**
   `alembic heads` on this tree resolves to four heads, not one:
   `0017_buyer_match`, `0017_document_storage`, `0017_exhibitor_preference`, and
   `0018_buyer_profile` (which itself chains onto a fifth file,
   `0017_meeting_buyer_extension`, that also branches directly off `0016_kiosk_session`). All
   four/five migrations set `down_revision = "0016_kiosk_session"` independently — at least
   three parallel tracks generated a new migration against the same base revision without
   coordinating. `alembic upgrade head` is ambiguous against this tree today. This directly
   violates the repo rule in `AGENTS.md`/this task's prohibitions ("Any DB schema change must
   be a new Alembic migration ... that chains onto the current head"). Evidence:
   `apps/api/tests/test_exhibitor_models.py::test_alembic_chain_has_one_published_head` fails
   with `assert ['0017_buyer_match', '0017_document_storage', '0017_exhibitor_preference',
   '0018_buyer_profile'] == ['0016_kiosk_session']`. **Recommendation**: the CONTRACTS track (or
   the wave integrator) needs to pick one canonical ordering and rewrite the other three/four
   migrations' `down_revision` into a single linear chain (or an explicit merge revision)
   before `G2_FEATURE_COMPLETE` can close — this blocks any real database from being migrated.

2. **MEDIUM — related test-contract drift.**
   `apps/api/tests/test_exhibitor_models.py::test_metadata_contains_published_supply_and_filter_tables`
   fails (`97 == 93` table count) — a direct consequence of the new buyer-match/
   document-storage/exhibitor-preference/buyer-profile tables landing without that contract
   test's expected count being updated. Not independently investigated further since it is
   downstream of finding #1 and outside this track's owned paths; flagging so the integrator
   updates the expected count once the migration chain above is resolved (not before, since the
   final table set may still change during the merge).

3. **MEDIUM — document dedup rejects legitimate same-content uploads across different exhibitors.**
   `apps/api/tests/test_document_api.py::test_upload_document_allows_same_content_for_different_exhibitors`
   fails: `app/services/document/service.py`'s `upload_document` raises `DocumentDuplicateError`
   even though the test's own name asserts two *different* exhibitors uploading byte-identical
   content (e.g. a shared spec-sheet PDF) should both succeed. Reading `service.py:138`, the
   duplicate lookup (`find_duplicate(db, exhibitor_id=..., content_hash=...)`) does appear to
   scope by `exhibitor_id`, so this looks like either a test-fixture bug (the fake session's
   duplicate lookup not actually filtering by `exhibitor_id`) or a real service-layer bug where
   the scoping is lost somewhere in the call chain — this track did not have time to fully
   isolate which, since document storage is outside QA-BUYER's owned paths. Flagging for the
   DOCUMENT-STORAGE track owner to triage; it is unrelated to the buyer/meeting/contact-privacy
   surface this track is responsible for and does not affect any of the 7 priority checks above.

4. **INFO — a fourth track's test file cannot yet be collected.**
   `apps/api/tests/test_ai_buyer_matching.py` fails collection with
   `ModuleNotFoundError: No module named 'ai'` (it imports `ai.buyer_matching.reason_codes`,
   which has not landed in `ai/` yet at the time this session ran). This is expected
   in-progress concurrent work per this wave's model (tracks land at different times) rather
   than a bug — noted here only so the integrator isn't surprised by a collection error when
   running the full suite before that track finishes; excluded from this report's own
   full-suite run via `--ignore` so it doesn't mask other results.

## Confirmation of absolute prohibitions

- Did not edit `apps/api/app/api/v1/api.py`, `apps/api/app/models/__init__.py`,
  `apps/user-web/lib/api-client.ts`, or `apps/user-web/lib/types.ts`.
- Did not edit any file outside this track's OWNED PATHS (verified via `git status --porcelain`
  before/after: only the three files listed at the top of this report were added).
- No new DB migration was added by this track (test-only track; no model/schema changes).
- No kiosk flow, contact-info exposure ordering, or unapproved-exhibitor exposure rule was
  weakened — this track's entire purpose was to add tests proving those rules hold, and all 44
  assertions pass against the current implementation without modifying it.
- No ontology concept codes were invented: `"BIZ_GOAL.DISTRIBUTION"`, `"BIZ_GOAL.OEM"`, and
  `"BIZ_GOAL.EXPORT"` used in test fixtures were verified against the installed
  `meet_ai.ontology` catalog (`load_catalog().concepts`) before use, not guessed.
- No small-group statistics are produced or exposed by these tests.
