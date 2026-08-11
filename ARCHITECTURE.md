# Architecture

## System shape

Meet AI is a modular monolith with web clients. The common matching engine is a pure, deterministic
library; API and UI layers adapt inputs and display outputs but do not own ranking formulas.

```text
REGISTERED_WEB ─┐
GUEST_WEB ──────┼─> apps/user-web ─┐
BUYER_WEB ──────┘                  │
                                  ├─> apps/api ─> PostgreSQL / pgvector / Redis / object storage
ADMIN_PARTNER_WEB ─> apps/admin ──┘       │
                                           └─> src/meet_ai engine / evaluation / ontology
```

Dedicated kiosk hardware and `apps/kiosk` are inactive compatibility assets under CR-009 and are
not part of the default development, build, deployment, or MVP acceptance path.

## Runtime boundaries

### `apps/user-web`

Next.js mobile-first frontend for registered visitors, anonymous guests, and verified buyers.
`/explore` is the no-login guest entry and calls the public approved-catalog search endpoint.
Personalized routes use profile, consent, recommendation, favorite, visit, and meeting APIs.

### `apps/admin`

Next.js operator and exhibitor-partner frontend. The shared authentication/RBAC/MFA contract
(CR-006/BACKEND-010) is implemented — opaque one-time personal-link exchange, Secure/HttpOnly
browser sessions, allowlisted-Origin plus session-bound CSRF, scoped RBAC, and WebAuthn/TOTP/
recovery MFA — so production access is no longer categorically blocked; ADMIN-002 (exhibitor/
AI-extraction review screens) remains BLOCKED on BACKEND-007 specifically (see
`.harness/backlog.yaml`), not on authentication. It must not expose unapproved extracted content.

### `apps/api`

FastAPI modular monolith. Routers expose profile, consent, public catalog/search, recommendation,
meeting, import, partner, and future authenticated admin workflows. SQLAlchemy/Alembic own canonical
persistence. External providers are accessed through adapters.

### `src/meet_ai`

- `engine`: versioned pure matching commands/results, deterministic scores, reasons, RRF shadow.
- `evaluation`: golden-set and shadow non-inferiority quality gates.
- `ontology`: immutable published 259-concept catalog and resolution utilities.

This package has no FastAPI, SQLAlchemy, network, or provider dependency.

### Data and asynchronous work

- PostgreSQL stores canonical, versioned business and consent records.
- pgvector is an optional candidate-recall channel; keyword/structured fallback remains available.
- Redis stores bounded sessions/cache, not canonical identity data.
- Uploaded documents are stored through `apps/api/app/services/document/storage.py`'s
  `ObjectStorageAdapter` Protocol. The shipped implementation is
  `LocalFilesystemStorageAdapter` (an `InMemoryStorageAdapter` exists for tests); a real
  S3-compatible adapter behind the same Protocol remains future work, but "storage is planned" is
  no longer accurate — the storage boundary and a working adapter both exist today.
- `apps/worker` is a materialized asynchronous service (`apps/worker/worker/**`, `worker` import
  root — see `.harness/decisions.md` DECISION-028) running document parsing, search indexing,
  analytics aggregation, and notification-outbox draining jobs, added by the WAVE2C/2D/2E work and
  the 2026-08-11 unification merge.

### Adapters, Netlify, and deployment

Most provider adapters live near their owning API services (e.g.
`apps/api/app/services/document/storage.py`), but a top-level `adapters/` directory does exist for
one integration: `adapters/php/BackjuAiSiteContext.php`. Netlify functions also exist and are
committed: `netlify/functions/ontology-extract.ts` and `netlify/functions/conversation-extract.ts`
(plus `netlify/functions/_shared/`). Neither is part of the active `apps/api`/`apps/user-web`/
`apps/admin`/`apps/worker` request path described above; they are legacy integration points kept
for the sites that call them. Deployment must target `apps/user-web`, `apps/admin`, `apps/api`,
and `apps/worker`; it must not target `apps/kiosk` under CR-009.

### Database paths

Canonical migrations are in `apps/api/alembic/**` with supporting SQL under `db/migrations/**`.
New schema changes require an approved Change Request and a single Alembic head.

## Request flows

### Anonymous guest search

```text
QR or URL -> /explore -> POST /api/v1/search(channel=WEB)
-> query normalization -> approved/active catalog retrieval
-> structured + keyword + optional vector candidates
-> deterministic catalog score/reasons -> exhibitor/booth result
```

No login, phone, email, or persistent profile is required. VECTOR outage preserves the existing
structured/keyword path.

### Registered or buyer matching

```text
confirmed profile/current intent -> eligibility and Hard Filter -> candidate recall
-> common matching facade -> grounded reason claims -> web result
-> optional favorite/visit/meeting action
```

UNKNOWN remains distinct. Contact data is disclosed only after accepted meeting workflow.

### Excel matching

```text
standard workbook -> validated import adapter -> canonical profile/company records
-> approval/consent/eligibility boundaries -> common matching facade -> privacy-minimized XLSX
```

Workbook rows never create an alternate score formula.

## Ownership mapping

| Track | Paths |
|---|---|
| FOUNDATION | `.harness/**`, `AGENTS.md`, `PROJECT_SCOPE.md`, `ARCHITECTURE.md`, root build files |
| CONTRACTS | shared contracts, API/model contracts, Alembic and migration specifications |
| BACKEND | `apps/api/app/api/**`, schemas, services, core, DB sessions, `apps/worker/**` |
| USER_WEB | `apps/user-web/**` |
| ADMIN | `apps/admin/**` |
| AI_SEARCH | `src/meet_ai/ontology/**`, `src/meet_ai/engine/**`, `src/meet_ai/evaluation/**` |
| KIOSK | `apps/kiosk/**` retained but inactive under CR-009 |
| QA | `tests/**`, `.harness/reports/**` |

The table follows `.harness/locks.yaml`; more specific task ownership in the backlog still applies.
