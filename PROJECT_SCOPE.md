# Project Scope

> Canonical scope contract for the parallel-development harness. The web-first pivot is approved
> in CR-009 and supersedes the earlier web/kiosk split wherever the documents disagree.

## One-line definition

A mobile-first web service that connects pre-registered visitors, anonymous on-site guests,
verified buyers, exhibitors, and event operators to one deterministic AI matching and discovery
engine without requiring an app installation or dedicated kiosk hardware.

## Active service channels

1. **REGISTERED_WEB** — persistent profile, proactive recommendations, favorites, visit planning.
2. **GUEST_WEB** — anonymous natural-language/category search, exhibitor/product/booth detail,
   map access, and optional later account linkage. Search is never gated by signup.
3. **BUYER_WEB** — verified buyer profile, hard-condition matching, comparison, and meeting request.
4. **ADMIN_PARTNER_WEB** — exhibitor content submission and operator review/approval/operations.

`KIOSK` is not an active MVP or v1.x channel. QR codes on event entrances, badges, printed maps,
and booth materials are entry links to `GUEST_WEB`; they are not kiosk handoff tokens.

## Two modules

1. **Web service module** — the four active channels above, implemented primarily in
   `apps/user-web` and `apps/admin` and backed by `apps/api`.
2. **Common AI/data platform** — canonical exhibitor/product/booth data, ontology, natural-language
   intent normalization, keyword+vector retrieval, deterministic ranking, grounded reasons,
   document structuring proposals, approval workflow, and quality evaluation.

The matching engine remains channel-independent. Web surfaces consume its versioned contracts and
must not recreate score formulas or infer missing facts.

## Fixed tech stack (do not swap without an ADR)

- Frontend: Next.js, React, TypeScript, Tailwind CSS
- Backend: Python, FastAPI, Pydantic, SQLAlchemy, Alembic
- Data: PostgreSQL, pgvector, PostgreSQL Full Text Search, Redis, S3-compatible object storage
- Async: RQ or Celery (no Kafka in MVP)
- Deploy: Docker, managed Postgres/Redis, CDN, WAF

## Applications

| App | Status | Owner track | Users |
|---|---|---|---|
| `apps/api` | active | BACKEND | all active web channels |
| `apps/user-web` | active | USER_WEB | registered visitors, guests, buyers |
| `apps/admin` | active, auth-gated | ADMIN | event operators, exhibitor admins, reviewers |
| `apps/worker` | active | BACKEND | document parsing, search indexing, analytics aggregation, notification-outbox draining |
| `apps/kiosk` | inactive compatibility source | KIOSK | no active deployment or release target |

The existing kiosk source and API are retained temporarily as reversible compatibility assets.
They receive no feature development and are excluded from default root validation/build commands.
Removal of the frozen kiosk API and stored records requires a separate compatibility migration.

## Explicit exclusions

Do not implement the following without an approved scope change:

- Dedicated kiosk hardware, kiosk web runtime, kiosk deployment, kiosk configuration UI, or kiosk
  session/handoff feature development
- Native mobile app installation as a prerequisite
- Precise indoor navigation, real-time congestion prediction, real-time per-product inventory
- Long-term CRM, quotes/contracts/settlement, sample shipping management
- Complex meeting-room auto-assignment, real-time online learning/multi-armed bandits
- Dedicated vector database, Kafka, large warehouse, or premature microservice decomposition
- Automatic model retraining/promotion

## Mandatory boundaries

- Only approved and currently participating exhibitor information reaches search or recommendation.
- Hard filters execute before ranking; UNKNOWN is not silently converted to pass, mismatch, or zero.
- AI output is a proposal until deterministic validation and the required human confirmation.
- Buyer contact details are disclosed to an exhibitor only when **all** of the following hold at
  once: the meeting is `accepted` (not merely `requested`/`counter_proposed`), the buyer explicitly
  opted into contact sharing at request time, and the exhibitor side has itself explicitly enabled
  contact sharing for that meeting (`meeting_contact_share.exhibitor_enabled_at` /
  `exhibitor_enabled_by_staff_id`). This is stricter than "the exhibitor accepts a meeting request"
  alone — acceptance and the exhibitor's contact-sharing toggle are two separate actions, and only
  the requesting exhibitor's own staff can ever see the fields the buyer chose to share. Full
  field-by-field detail: `.harness/contracts/meeting.md` §3 (note: that document predates the
  2026-08-11 unification merge and enumerates the request-time buyer-consent and staff-ownership
  gates in detail; the exhibitor-enabled-sharing gate above was the specific defect this merge
  fixed in main's pre-merge two-of-three check — see `.harness/decisions.md` DECISION-026).
- Guest web search requires no login, phone number, email address, or persistent personal profile.
- Current query and explicit/confirmed profile data outrank weak behavioral signals.
- Existing weighted-v1 public ranks remain authoritative until a separate promotion decision.

## MVP completion criteria

- **Registered web**: login/prefill, interests, personalized recommendations, natural-language
  search, favorites, visit plan, and simple meeting requests.
- **Guest web**: direct QR/URL entry, no-login natural-language/category search, approved exhibitor
  and booth results, detail and map access, and optional later account linkage.
- **Buyer web**: verified profile, MUST/PREFER/EXCLUDE conditions, hard-filtered exhibitor matching,
  comparison, meeting request, and consent-gated contact sharing.
- **Admin/partner web**: exhibitor/product/booth submission and approval, ontology management,
  document extraction review, and basic search/recommendation/zero-result operations.
- **Document extraction review**: exhibitor document upload, grounded AI attribute extraction that
  is never auto-published, exhibitor confirmation of proposed attributes, and operator approval
  before any extracted content reaches the search/embedding index. Both confirmation steps are
  required; neither substitutes for the other.
- **Interaction analytics**: interaction-event collection feeding operator analytics/funnels/
  operations dashboards, with aggregates covering fewer than 5 distinct users suppressed at the
  database level rather than filtered only in application code.
- **In-app notification inbox**: read state, per-type email opt-in gated on explicit consent, and
  frequency-capped delivery for account-linked users, complementary to (not a replacement for) the
  Alimtalk-first outbound access-link delivery described in DECISION-022/CR-012.
- **AI engine**: shared natural-language and Excel-profile intent contract, keyword+vector candidate
  retrieval, deterministic ranking, grounded reason claims, offline evaluation, and provider outage
  fallback without relaxation of hard constraints.
