# Project Scope

> Canonical scope contract for the parallel-development harness. See
> [docs/vibe-coding-master-spec-v1.md](./docs/vibe-coding-master-spec-v1.md) for full detail and
> [docs/redesign-web-kiosk-split.md](./docs/redesign-web-kiosk-split.md) for the pivot rationale.

## One-line definition

For pre-registered users and buyers: proactive, personalized exhibitor/booth recommendations
based on registration data and interests. For unregistered on-site visitors: anonymous
natural-language search via kiosk (or a QR-handed-off guest web view) for exhibitors/booths
matching their current interest. A web/kiosk-split AI matching & discovery service.

## Three modules

1. **Web personalization module** (pre-registered general users + buyers) — persistent profile,
   proactive recommendations, favorites, buyer↔exhibitor matching, lightweight meeting requests.
2. **Kiosk portable search module** (anonymous on-site visitors) — no login, no long-lived
   profile, natural-language/category search, exhibitor/booth results, map, QR handoff to
   mobile, auto session reset.
3. **Common AI/data platform** — exhibitor/booth/product data, interest ontology, NL query
   analysis, hybrid (keyword+vector) search, ranking, recommendation-reason generation,
   exhibitor-content AI structuring, approval workflow, basic stats, auth/audit.

## Fixed tech stack (do not swap without an ADR)

- Frontend: Next.js, React, TypeScript, Tailwind CSS
- Backend: Python, FastAPI, Pydantic, SQLAlchemy, Alembic
- Data: PostgreSQL, pgvector, PostgreSQL Full Text Search, Redis, S3-compatible object storage
- Async: RQ or Celery (no Kafka in MVP)
- Deploy: Docker, managed Postgres/Redis, CDN, WAF

## Applications

| App | Owner track | Users |
|---|---|---|
| `apps/api` | BACKEND | all |
| `apps/user-web` | USER_WEB | pre-registered users, buyers, QR guests |
| `apps/kiosk` | KIOSK | anonymous on-site visitors |
| `apps/admin` | ADMIN | event operators, exhibitor admins, data reviewers |
| `apps/worker` | BACKEND | document structuring, embeddings, notifications, aggregation |

`apps/api` and `apps/user-web` were physically migrated from the legacy `backend/`/`frontend/`
directory names on 2026-08-02 (pnpm workspace adoption, DECISION-006). Full monorepo now uses
`pnpm-workspace.yaml` (`apps/*`, `packages/*`).

## Explicit exclusions (do not implement without an approved scope change)

Precise indoor navigation, real-time congestion prediction, real-time per-product inventory,
long-term CRM, quotes/contracts/settlement, sample shipping management, complex meeting-room
auto-assignment, real-time online learning / multi-armed bandit, dedicated vector DB, Kafka,
complex microservice decomposition, large data warehouse, automatic model retraining/promotion,
kiosk sign-up, kiosk long-term personalization, kiosk personal-data entry.

If you find yourself implementing any of the above "because it seemed useful," stop and record it
in `.harness/expansion-candidates.md` instead.

## MVP completion criteria (summary — see master spec §55 for full detail)

- **Web**: registered login, view/edit interests, personalized recommendations, NL search,
  favorites, buyer exhibitor search/matching, simple meeting requests.
- **Kiosk**: no signup required, NL/category search, exhibitor/booth results, detail + map,
  QR handoff to mobile, session data wiped after close.
- **Admin**: register/approve exhibitor+product+booth, manage interest-area codes, kiosk config,
  booth operating status, basic search/recommendation stats + zero-result queries.
- **AI**: NL query structured into allowed ontology codes, keyword+vector search combined,
  recommendation/search reasons are grounded in real evidence, keyword search survives AI
  outages, unapproved exhibitor data never used.
