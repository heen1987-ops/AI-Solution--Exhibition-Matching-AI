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

Next.js operator and exhibitor-partner frontend. Production access remains blocked until the shared
authentication/RBAC/MFA contract is implemented. It must not expose unapproved extracted content.

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
- S3-compatible storage is planned for uploaded documents.
- `apps/worker` is the planned asynchronous boundary for parsing, embedding, notification, and
  aggregation. No separate service is created before measured operational need.

### Adapters, Netlify, and deployment

Provider adapters currently live near their owning API services; a top-level `adapters/` directory
does not exist. Netlify functions/config exist only where explicitly committed; there is no active
`.openai/hosting.json` or canonical `netlify/` application directory in this snapshot. Deployment
must target `apps/user-web`, `apps/admin` when auth-ready, and `apps/api`; it must not target
`apps/kiosk` under CR-009.

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
