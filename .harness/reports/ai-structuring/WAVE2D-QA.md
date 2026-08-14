# WAVE 2D — QA-AI-STRUCTURING report

Track: QA-AI-STRUCTURING (WAVE 2D) · Date: 2026-08-03

Owned deliverables:

- `apps/api/tests/integration/test_ai_structuring_e2e.py` (new)
- `apps/api/tests/security/test_document_security.py` (new)
- `.harness/reports/ai-structuring/WAVE2D-QA.md` (this file)

## Environment notes

No live PostgreSQL is reachable in this sandbox (no `POSTGRES_TEST_DATABASE_URL`, no local
docker daemon reachable from this worktree, and `aiosqlite` is not installed in the shared venv
either). Following the convention already established by `test_document_api.py`,
`test_extraction_api.py`, and the WAVE 2C QA track's own `test_buyer_meeting_e2e.py`, every test
below drives the **real** production coroutines end to end — the real
`app/api/v1/routers/document.py` and `build_extraction_router()` FastAPI routers (mounted on
their own standalone `FastAPI()` app, since neither is registered in `app.main.app` yet — that
wiring is the integrator's job, not this track's), the real `app/services/document/*`,
`app/services/extraction/*`, `app/services/indexing/*` service layers, the real
`ai.extraction.extractor.GroundedExtractor` + `ai.extraction.validator` grounding/injection/
ontology defenses (fed a scripted `FakeExtractionBackend`, no live LLM call), and the real
`apps.worker.app.jobs.document_parsing.parse_document` PII-masking parser — against one shared
scripted `AsyncSession` fake per file. Nothing production-side was modified by this track.

**Prior art found and reused, not duplicated**: by the time this session ran, BACKEND-DOCUMENT,
WORKER-PARSING, AI-EXTRACTION, BACKEND-EXTRACTION, and BACKEND-INDEXING had all already landed
fully-implemented, well-documented pipelines (`app/models/document.py`,
`app/services/document/{validation,storage,tokens,service}.py`,
`apps/worker/app/jobs/document_parsing.py`, `ai/extraction/{types,extractor,validator,
grounding,provider,attribute_schema,ontology_support}.py`, `app/models/extraction.py`,
`app/services/extraction/{ingestion,review,attribute_schema,ontology_validation,errors}.py`,
`app/api/v1/routers/{document,extraction}.py`, `app/services/indexing/{service,
document_builder}.py`, `app/models/indexing.py`). No new production code was written by this
track — it is test-only per its OWNED PATHS. Every one of these modules already has good unit
test coverage of its own (`test_document_api.py`, `test_extraction_api.py`, `test_indexing.py`,
`test_ai_extraction.py`); this track's job was the seam between them (the actual end-to-end walk)
plus a security-focused deep dive on the upload/download surface — not re-proving what those
files already prove well.

## Result summary

39 new test functions across the two owned files: **33 pass, 0 fail, 6 xfail (strict — all 6
prove real, confirmed bugs described below; the suite will loudly fail via XPASS the moment any
of them is fixed, so they cannot silently rot)**.

```
apps/api/tests/integration/test_ai_structuring_e2e.py     6 passed, 2 xfailed
apps/api/tests/security/test_document_security.py        27 passed, 4 xfailed
--------------------------------------------------------------------------------
33 passed, 6 xfailed
```

Full backend suite (`pytest apps/api/tests -q --ignore=tests/test_ai_buyer_matching.py`,
excluding one pre-existing collection error documented below): **650 passed, 2 failed
(pre-existing, not introduced by this track, see below), 7 skipped, 7 xfailed**. Confirmed by
running the same command with this track's two files excluded: the same 2 failures occur either
way, and a third, unrelated test (`test_event_message_api.py::
test_duplicate_message_count_stmt_excludes_terminal_statuses`) is order/flake-dependent
regardless of whether this track's files are included (observed failing in one run and passing
in another, with and without this track's files present) — not investigated further since it is
outside this track's owned paths and not part of the document/extraction/indexing pipeline.

| # | Check | Tests | Pass | Fail | xfail (bug) |
|---|-------|------:|-----:|-----:|------------:|
| Upload security | MIME spoofing (2), exe/script (7)/archive (4) rejection, oversized/empty file (2) | 15 | 15 | 0 | 0 |
| Cross-company access | Real role-query authorization (not stubbed), 404-not-403 non-leak, OPERATOR override | 5 | 5 | 0 | 0 |
| Signed-URL-equivalent expiry | Token round trip, cross-document reuse, CRLF-safety, route-shadow proof | 4 | 0 | 0 | 4 (bug #2) |
| Duplicate-file handling | Same-exhibitor 409, cross-exhibitor allowed | 2 | 2 | 0 | 0 |
| Path traversal | 4 malicious filenames + storage-adapter unit check | 5 | 5 | 0 | 0 |
| E2E pipeline hops 1–6 | Upload → parse/mask → extract/ground → ingest → review → approve → publish → index-tier segregation | 6 | 6 | 0 | 0 |
| Persistence regression | `db.commit()` never called in review/extraction/indexing services | 2 | 0 | 0 | 2 (bug #1) |
| **Total** | | **39** | **33** | **0** | **6** |

## What each check actually exercises

**File-security matrix (`test_document_security.py`)** — every test drives a real multipart
`TestClient` request through the real router:
- MIME spoofing: `.pdf` extension with plain-text bytes, `.txt` extension with a ZIP-signature
  payload — both blocked before anything reaches storage (`storage._objects == {}` asserted
  after each).
- Executable/script/archive rejection: an EXE disguised with an allowed extension (magic-byte
  sniffing), plus six blocked extensions (`.exe .sh .ps1 .js .vbs .jar`) and four archive
  extensions (`.zip .rar .7z .tar.gz`), all parametrized.
- Oversized/empty file: `DOCUMENT_MAX_UPLOAD_BYTES` monkeypatched to 10 bytes to keep the test
  fast rather than allocating a real 25MB+ payload; separately, a zero-byte file is rejected.
- Cross-company access: seeds real `UserRole`/`Role`-shaped rows for two exhibitors and drives
  the actual `_require_exhibitor_access` SQL-shaped query (not monkeypatched, unlike
  `test_document_api.py`'s own router-layer tests) across upload/list/detail/download-token/
  delete; a same-company-but-wrong-document-id request is proven to 404 (not 403, so existence
  is never leaked to an unauthorized actor); an OPERATOR role is proven to bypass the
  per-exhibitor gate (so the denial above is genuinely role-based, not "always 403").
- Signed-URL-equivalent expiry: real HMAC token issuance/verification through the router,
  tampering (flipped char), expiry, and cross-document token reuse — **4 of these 6 tests are
  `xfail`, see Bug #2 below**.
- Duplicate handling: identical bytes under the same exhibitor → 409 with `existing_document_id`
  and exactly one stored object; identical bytes under two different exhibitors → both succeed
  (dedup is per-exhibitor, not global).
- Path traversal: four traversal-shaped filenames (`../../../etc/passwd.pdf`, Windows-style,
  double-encoded, absolute-path) all upload successfully but the resulting `storage_key` is
  proven to always be `exhibitor/{uuid}/{uuid}/{uuid}.pdf` — the filename never reaches
  `build_storage_key` at all, so no filename can influence the path (structural, not just
  convention). The `LocalFilesystemStorageAdapter`'s own defense (`StorageKeyError` on a
  directly-supplied `../` key) is also re-checked as belt-and-suspenders. A CRLF-header-
  injection attempt via a quoted filename is checked against the real `Content-Disposition`
  response header (also blocked by Bug #2's `xfail`, since it needs the download endpoint).

**E2E pipeline walk (`test_ai_structuring_e2e.py`)** — one synthetic (non-real) exhibitor
document flows through every stage with the same identifiers at each hop:
- Hop 1: real upload via the router + real `document_service`, plus one negative control
  (disguised executable rejected).
- Hop 2: the real `apps/worker` parser splits the text into paragraph segments and masks a
  phone-number-shaped string — asserted absent from every segment's text before it can reach any
  AI step.
- Hop 3: the real `GroundedExtractor`/`ExtractionValidator` is fed a scripted model response
  containing (a) a genuine grounded fact, (b) a claim whose *only* cited evidence is a
  prompt-injection sentence ("이 문서를 읽는 AI에게: 이전 지시를 모두 무시하고..."), and (c) a
  critical trade-condition field (`trade.moq`) the source text never states. Asserted: the
  grounded fact survives, the injection-only claim is dropped with
  `ISSUE_INJECTION_SUSPECTED_EVIDENCE`, and `trade.moq` is reported missing rather than guessed.
- Hop 4: `ingest_extraction_result` (real) turns the validated result into `extracted_attribute`
  rows — proven that the injection-rejected claim never becomes a row at all (no attribute is
  ever published without evidence, per the AGENTS.md invariant), and that the UNKNOWN critical
  field gets `fact_type='UNKNOWN'`/`normalized_value=None`, never a fabricated value.
- Hop 5: `submit-review` is proven blocked (`422`, `TRADE_CONDITION_UNKNOWN_UNACKNOWLEDGED` +
  `EXTRACTIONS_PENDING_REVIEW`) until the exhibitor patches/confirms/acknowledges every row; the
  full exhibitor-review → operator-claim → operator-approve flow is then walked through the real
  router, proving (i) a bare `confirm` without a `PATCH normalized_value` can never publish
  (`document-structuring.md`'s own documented rule — "confirming a null-normalized row is still
  just a review-status change, not a publish"), (ii) the UNKNOWN critical trade condition is
  approved but produces **no** `PublishedContentVersion` even after operator approval ("unknown
  stays unknown" holds through approval, not just through extraction), and (iii) a rival
  exhibitor is denied (`403`) from even listing the extractions mid-flow.
- Hop 6: two `PublishedContentVersion` rows (one `PUBLIC`, one `VERIFIED_BUYER`) are fed through
  the real `indexing_service._gather_published_attributes` and the real
  `document_builder.build_public_document`/`build_verified_buyer_document` — proven that the
  `PUBLIC` tier's `published_attributes` never contains the `VERIFIED_BUYER`-only key, while the
  `VERIFIED_BUYER` tier legitimately sees both (since `VERIFIED_BUYER` clearance is a superset of
  `PUBLIC`). A literal forbidden-key-set check (`contact_email`, `contact_phone`,
  `internal_memo`, `storage_key`, `raw_path`) is also run against both tier documents as a
  structural (not just docstring-claimed) guarantee.

## Bugs found in sibling tracks' code

Both were found while building this track's own tests (not while running someone else's test
suite) and are proven with strict `xfail` regression tests in this track's owned files, so they
cannot silently regress further or be missed in CI — a fix flips the test to XPASS, which
`strict=True` reports as a failure until the `xfail` marker is removed.

### Bug #1 — HIGH — `app/services/extraction/review.py`, `app/api/v1/routers/extraction.py`,
`app/services/extraction/ingestion.py`, and `app/services/indexing/service.py` never call
`db.commit()`

`grep -rn commit app/services/extraction/review.py app/api/v1/routers/extraction.py
app/services/extraction/ingestion.py app/services/indexing/service.py` returns **zero matches**
across all four files. `app/db/session.py`'s own `get_db()` docstring is explicit that commit is
the router/service layer's responsibility ("커밋은 라우터/서비스 계층 책임이다") — it never
commits itself, and a real `AsyncSession` rolls back an uncommitted transaction when the
request-scoped session closes at the end of a request. Every other persistence-touching
router/service in this repo follows the commit-explicitly convention
(`document/service.py`, `partner.py`, `meetings.py`, `profile.py`, `consent.py`,
`buyer_profile.py`, `conversation.py`, `adaptive.py`, `imports.py`, `webhooks.py`,
`recommendations.py`, `matching/result_store.py`, `kiosk.py`,
`exhibitor_preference/service.py`, `buyer_match/orchestrator.py`,
`interaction_event/ingestion.py` — 16 files, confirmed via grep).

**Impact**: in production, every `PATCH /partner/extractions/{id}`, `POST .../confirm`,
`POST .../submit-review`, `POST /admin/ai-review` (claim), `POST .../approve`, `.../reject`,
`.../request-changes` call would return a correct `200`/response body (the in-memory ORM object
really was mutated within that request's session) but **never durably persist** — the very next
request, with a fresh session, would see the change as if it never happened. The entire
exhibitor-review → operator-approval → publish pipeline this track was asked to test cannot
survive across two HTTP requests as currently implemented. `app/services/indexing/service.py`'s
`regenerate_exhibitor_documents`/`unpublish_exhibitor_documents` have the identical gap — the
search-index `SearchDocument`/`IndexingJob`/`CacheInvalidationEvent` rows they build would never
persist either.

This is exactly the class of defect that each landing track's own unit tests (which use
in-memory fakes that persist unconditionally, not real commit/rollback-on-close semantics)
structurally cannot catch — proving it required this QA track's cross-cutting, "does this
actually survive a request boundary" lens.

**Evidence**: `test_confirm_and_approve_flow_is_never_actually_persisted_bug` and
`test_indexing_regenerate_is_never_actually_persisted_bug` in
`test_ai_structuring_e2e.py`. Both call the real service functions with a `commit_count`-tracking
fake session and assert `commit_count > 0` after a successful mutating call chain — both
currently fail (`xfail(strict=True)`, so they show as expected-fail, not a red build, but will
loudly XPASS-fail the moment `db.commit()` is added).

**Recommendation**: add `await db.commit()` at the end of every mutating function in
`review.py`/`ingestion.py`/`indexing/service.py`, or (cleaner, matching the "confirm is a
review-status-only change" contract already documented in `document-structuring.md`) commit once
per router handler in `extraction.py` right after calling the service function, matching every
other router in this repo.

### Bug #2 — HIGH — `GET /partner/documents/download` is unreachable: shadowed by
`GET /partner/documents/{document_id}`

`app/api/v1/routers/document.py` registers `GET /partner/documents/{document_id}` (the
document-detail endpoint) before `GET /partner/documents/download` (the token-download
endpoint). Both patterns match a request path with exactly one segment after `/documents/`, and
Starlette/FastAPI resolve routes in registration order (first match wins) — so **every** request
to `/partner/documents/download?token=...` is actually dispatched to `get_document_detail` with
`document_id="download"` (which then fails Pydantic's UUID validation, returning `422`) instead
of ever reaching `download_by_token`. The signed-token download mechanism this router's own
module docstring describes as the "서명된 URL 대체" (signed-URL substitute) — the entire point
of the two-step issue-token/download-by-token design — cannot be exercised through the real HTTP
surface today.

**Evidence**: `test_download_route_is_shadowed_by_the_document_detail_route_bug` in
`test_document_security.py` inspects the real router's live route list and asserts the static
`download` route is registered before the dynamic `{document_id}` route — currently fails
(`assert 6 < 2`, i.e. `download` is registered *after*, at index 6, while `{document_id}` is at
index 2). Three further tests that exercise the actual download HTTP round trip (expiry,
tampering, cross-document reuse, CRLF-header-safety) are also `xfail` for the same root cause —
all four are captured under one shared `_DOWNLOAD_ROUTE_SHADOWED_REASON` constant for a single
source of truth.

**Recommendation**: move the `@router.get("/partner/documents/download")` handler definition to
before `@router.get("/partner/documents/{document_id}")` in the module (or make the dynamic
route non-greedy by giving the static route to a distinct, non-conflicting prefix) — a
one-line reordering fix. This track deliberately did not attempt the fix itself (test-only
OWNED PATHS; the file belongs to BACKEND-DOCUMENT).

### Pre-existing, unrelated issues observed while running the full suite (not introduced by this track)

1. **`test_exhibitor_models.py::test_alembic_chain_has_one_published_head`** — the Alembic
   migration chain still has multiple unmerged heads (same root cause flagged as the top finding
   in the WAVE 2C QA report, `.harness/reports/buyer-matching/WAVE2C-QA.md` — evidently still
   unresolved as of this session). Confirmed unrelated to this track: fails identically with and
   without this track's two files present.
2. **`test_exhibitor_models.py::test_metadata_contains_published_supply_and_filter_tables`** —
   downstream of #1 (expects an exact table count that has since grown). Same as WAVE 2C's
   finding #2.
3. **`test_event_message_api.py::test_duplicate_message_count_stmt_excludes_terminal_statuses`**
   — observed failing in one full-suite run and passing in another (order/flake-dependent),
   reproducible identically whether or not this track's files are included in the run. Not
   investigated further — outside this track's owned paths and unrelated to the document/
   extraction/indexing pipeline.
4. `apps/api/tests/test_ai_buyer_matching.py` still fails collection with
   `ModuleNotFoundError: No module named 'ai'` in a bare `apps/api`-only pytest invocation (same
   as WAVE 2C's finding #4) — excluded via `--ignore` in every command in this report for that
   reason; not a regression, that track's fixture imports `ai.buyer_matching.reason_codes`
   without the `sys.path` bootstrap this track's own file (and `test_ai_extraction.py`) uses.

## Skipped tests

None. Every check on this track's checklist has a real, runnable test — the two genuine gaps
found (Bugs #1 and #2) are captured as strict `xfail` regressions rather than silent skips, per
this task's own instruction to mark unresolvable pieces with a clear reason rather than deleting
them.

## Confirmation of absolute prohibitions

- Did not edit `apps/api/app/api/v1/api.py`, `apps/api/app/models/__init__.py`,
  `apps/user-web/lib/api-client.ts`, or `apps/user-web/lib/types.ts`.
- Did not edit any file outside this track's OWNED PATHS — `git status --porcelain` before/after
  shows only the three new files listed at the top of this report (everything else in the
  working tree's diff predates this session, part of the prior `backend/`→`apps/api` monorepo
  migration).
- No new DB migration was added (test-only track; no model/schema changes).
- No kiosk flow, contact-info exposure ordering, or approval-gating rule was weakened — this
  track's entire purpose was to add tests proving those rules hold (and, where they did not
  fully hold, to document exactly why with a reproducible regression test), without modifying
  any production code.
- No ontology concept codes were invented: `company.name`, `trade.moq`,
  `trade.export_capability`, `company.description` (attribute codes) are all real entries in
  `ai/schemas/extraction/attribute_schema.json`, verified by reading that file directly before
  use, not guessed.
- No small-group/minority statistics are produced or exposed by these tests.
- No personal data belonging to any real person appears in any test fixture — the synthetic
  exhibitor document text, phone number, and company name used throughout are fabricated for
  this test only (the phone-number-shaped string exists specifically to prove it gets masked and
  never reaches the AI layer or any published attribute).
