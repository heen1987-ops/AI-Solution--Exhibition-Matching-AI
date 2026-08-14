# Public Search + Kiosk Vertical Slice — Integration Report

Date: 2026-08-02
Scope: BACKEND-008, BACKEND-006, KIOSK-001~004, guest QR handoff

## Outcome

- Public catalog and anonymous search are mounted under `/api/v1`.
- The kiosk runs as an independent Next.js application with no login or PII input.
- The complete on-site path is connected: idle → language → anonymous session → natural-language
  or category search → approved results → exhibitor/booth detail → map → signed QR → guest web.
- Invalid/expired QR tokens are rejected by the API before public data is returned.

## Privacy and exposure invariants

- Public repository SQL requires an OPEN event, APPROVED exhibitor/participation/product, approved
  product images, and non-deleted records.
- Kiosk request/DB schemas contain no name, phone, email, password, or long-lived profile fields.
- Live search/session/QR state uses Redis TTL. The durable kiosk tables retain only anonymous device,
  lifecycle, selected opaque result IDs, and token hash data for aggregate audit statistics.
- QR payload includes only opaque handoff ID, event ID, and expiry; selected result IDs remain
  server-side and the token is bound to their Redis record by SHA-256 hash plus HMAC signature.
- Client state is limited to `sessionStorage` and is cleared on manual close, idle timeout, handoff,
  expiry, and return to the idle screen.

## Search implementation

- Structured category recall resolves canonical ontology concept codes.
- Keyword recall uses PostgreSQL `to_tsvector`/`plainto_tsquery`/`ts_rank_cd`, with a deterministic
  Python token fallback for compatibility and Korean substring recall.
- Ranking uses the documented coefficient layout: semantic 0.45, keyword 0.30, category 0.15,
  data quality 0.05, booth availability 0.05. Semantic is explicitly zero until the repository
  publishes `ai.object_embedding`/pgvector data; this remaining work is AISEARCH-002.
- Results exclude closed/unapproved entities and deduplicate repeated exhibitors.

## Verification evidence

- `pytest`: 148 passed, 2 skipped (live Postgres checks are opt-in).
- Ruff: all changed backend, schema, migration, and test files pass.
- Alembic: one head, `0016_kiosk_session`; ORM metadata contains 93 tables.
- Kiosk: 3 component/privacy tests pass; TypeScript and Next production build pass (12 pages).
- User web: TypeScript and Next production build pass (20 pages, including `/kiosk-handoff`).
- Contract artifacts parse successfully; OpenAPI snapshot contains 66 paths.

## Remaining release work

- Publish and populate the semantic embedding table, then wire pgvector similarity into
  AISEARCH-002 instead of the current explicit zero semantic score.
- Run optional live Postgres/Redis integration tests and browser-device kiosk tests outside the
  Google Drive synced worktree.
- Complete admin approval/statistics and favorite APIs before G2 can pass.
