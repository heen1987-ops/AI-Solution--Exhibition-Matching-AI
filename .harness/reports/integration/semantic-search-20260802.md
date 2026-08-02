# AISEARCH-002 Semantic Search — Integration Report

Date: 2026-08-02
Contract: CR-004 / DECISION-007

## Outcome

- Added `ai.object_embedding` with a 512-dimensional pgvector column, immutable model-version
  lineage, one active pointer per recommendable content/language, and a SUMMARY-only active-row
  HNSW cosine index whose predicate is rendered literally in search SQL.
- Added a validated OpenAI embedding-provider adapter and an approved-public-catalog backfill
  command. The integration is opt-in and requires a dedicated API key.
- Added semantic top-K recall before the existing 300-candidate cap, then applied the frozen
  deterministic score `0.45 semantic + 0.30 keyword + 0.15 category + 0.05 data quality + 0.05
  booth availability`.
- Public web search and kiosk search use the same scorer. Kiosk passes its session language.
- Provider, validation, or pgvector-query failures fall back to the existing FTS, keyword, and
  structured signals without score-weight renormalization.
- Event existence/OPEN status is checked in a short DB transaction before provider I/O. Optional
  structured/vector/hydration queries use savepoints, and Korean/Japanese/Chinese free text can
  retain semantic-only candidates.

## Privacy and lineage

- Backfill input is limited to approved, non-deleted public exhibitor and event-product catalog
  text. Query text and generated vectors are not logged by this implementation.
- Each stored vector records the exact model version, language, source content type, and SHA-256
  content hash. A replacement is staged inactive and promoted atomically.
- Each participation SUMMARY includes its approved public product text. Recall reads SUMMARY rows
  only, so one product-rich exhibitor cannot monopolize the raw ANN window. Semantic hydration is
  round-robin by participation and the independent 300-row FTS window remains available.
- Company and product names are placed before descriptions; remaining bytes are distributed fairly
  across description sources, so one oversized early product cannot erase later product names.
- Source-field, approval, or recommendable-membership changes immediately deactivate the affected
  participation's active catalog vectors through database triggers. `BEFORE STATEMENT` triggers
  acquire a short global catalog advisory lock before row changes and FK cascades; final backfill
  shares that lock and rechecks the latest snapshot before activation, closing qualifying-row
  phantoms without reversing the managed source-write lock order.
- Provider inputs are capped conservatively by UTF-8 bytes (8,000 per input, 240,000 per request).
  Completed batches use an event/language staging lock and commit inactive for retry reuse;
  activation rechecks the approved catalog snapshot under the global source lock before switching
  pointers.

## Verification evidence

- Backend suite: `174 passed, 2 skipped`; the skips require an explicitly configured live
  PostgreSQL database.
- Aggregate root/AI/API suite: `351 passed, 2 skipped`, plus `12 subtests passed`.
- Semantic unit/contract tests cover score clamping, exact weights, response shape/dimension
  validation, provider fallback, pgvector savepoint fallback, SQL filters, and cosine ordering.
- Object-embedding tests cover approved-public-only source selection, provider input limits,
  product-name priority/fair truncation, model-contract rollback, retryable inactive batch staging,
  source snapshot recheck, statement-level advisory-lock/source-membership trigger publication,
  hashes, dimensions, and atomic activation.
- Alembic `upgrade head --sql` and targeted `0017 -> 0016` downgrade SQL compile successfully;
  the single migration head is `0017_object_embedding` and the ORM registry contains 94 tables.
- Generated OpenAPI still exactly matches the frozen snapshot: 66 paths and 171 schemas.
- Targeted Ruff `F`/`I` checks and `pip check` pass. Existing unrelated full-repository Ruff debt
  is not represented as green.

## Remaining operational validation

- Docker/PostgreSQL was not running locally, so live extension creation, HNSW execution, and the
  source-invalidation triggers and opt-in PostgreSQL integration tests remain to be exercised
  against an isolated stack.
- A real-provider smoke test, catalog backfill, `EXPLAIN ANALYZE`/exact-vs-ANN recall comparison,
  latency/cost measurement, gateway/WAF rate limiting for the public OPEN-event provider path,
  and gold-set relevance evaluation remain G3 release work. These do not enable themselves;
  semantic search stays off by default.
