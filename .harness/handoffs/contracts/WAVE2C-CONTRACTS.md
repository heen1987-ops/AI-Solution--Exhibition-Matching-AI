# WAVE2C-CONTRACTS handoff — buyer profile / matching / meeting surface

> Track: CONTRACTS-BUYER (WAVE 2C). Owned paths: `.harness/contracts/**`,
> `.harness/handoffs/contracts/WAVE2C-CONTRACTS.md`. This run touched only those two paths — no
> `apps/**`, no migrations, no `.harness/state.json`/`backlog.yaml`/`locks.yaml`.
>
> Purpose: WAVE 2C workers run in parallel and may not read this before starting, but should check
> it before finishing (per the task instructions) to avoid duplicating already-shipped work or
> re-deciding something already decided here.

## TL;DR for other WAVE2C agents

**Most of what a naive reading of the WAVE2C prompt asks for already exists**, built by earlier
BACKEND waves under the flat `apps/api/app/**` layout (not the `src/modules/**` layout the
external prompt assumed — see ASSUMPTION-003). Before writing any new router/model/schema file in
this area:

1. `apps/api/app/models/meeting.py` — full meeting/lead/follow-up domain (`AvailabilitySlot`,
   `MeetingRequest`, `MeetingSlotRequest`, `MeetingContactShare`, `MeetingStatusHistory`, `Lead`,
   `FollowUp`). **Extend, do not duplicate.**
2. `apps/api/app/api/v1/routers/meetings.py` — full meeting API (buyer + partner sides), including
   idempotency, optimistic locking, atomic slot reservation, contact-share disclosure. **Extend, do
   not duplicate.**
3. `apps/api/app/api/v1/routers/recommendations.py` + `app/services/matching/**` — this *is* the
   buyer↔exhibitor matching engine (`POST /recommendations`, `user_type=BUYER` on the caller's
   profile selects buyer-tier matching). **Do not build a separate `/buyer/matches` router.**
4. `apps/api/app/api/v1/routers/profile.py` — this *is* the buyer profile surface
   (`/profiles/me/buyer-needs`, `profile.buyer_need` table). **Do not build a separate
   `/me/buyer-profile` router.**
5. `apps/api/app/models/exhibitor.py`'s `TRADE_AVAILABILITY_STATUSES` already implements the
   YES/NO/CONDITIONAL/NEGOTIABLE/UNKNOWN enum exactly as specified. **Nothing to build here.**

Full detail, field-by-field mapping, and exact source citations: see
`.harness/contracts/buyer-matching.md` and `.harness/contracts/meeting.md` (both new files from
this run).

## Genuine gaps found (confirmed absent, not just renamed)

| Gap | Where documented | Suggested owner |
|---|---|---|
| `POST /buyer/compare` — no compare endpoint exists anywhere. | `buyer-matching.md` §5 (proposed shape included) | BACKEND (new router or extend `recommendations.py`) |
| `/admin/buyers`, `/admin/buyers/{id}/verify`, `/admin/buyers/{id}/reject` — no admin router exists at all yet (confirmed: no `apps/api/app/api/v1/routers/admin*.py`; `partner.py`'s own docstring says operator-approval is explicitly out of its scope). | `buyer-matching.md` §4 (proposed shape included) | Whichever track builds the operator/admin router — check prior art again first, a router may land from a parallel wave before you start. |
| Buyer verification status enum (`UNVERIFIED/PENDING/VERIFIED/LIMITED/REJECTED/SUSPENDED/EXPIRED`) — no such column or enum exists on `profile.buyer_need` or anywhere else. Only two independent booleans (`business_email_verified`, `company_verified`) and an unrelated identity-auth `authentication_state` exist today. | `buyer-matching.md` §2 (full permission table + rationale; applied as a Blocker-Score-≥7 safest-reversible-default per AGENTS.md's escalation rule, since no prior decision resolves it) | Whoever implements `/admin/buyers/*` needs a migration adding this column to `profile.buyer_need`, owned by CONTRACTS per the parallel-dev rule ("Database schema changes go through Alembic migrations only, owned by the CONTRACTS track") — **not done in this run**, this run only defines the contract. |
| `RecommendationItem.unknown_fields` — no field distinguishes "exhibitor data known to be X" from "exhibitor data not evaluable, treated as UNKNOWN" at the per-result level (AGENTS.md invariant 7). | `buyer-matching.md` §3 table, `results[].unknown_fields` row | Matching-explanation track (`app/services/matching/explanation_generator.py`) — additive schema field, not a new endpoint. |
| `no_show` meeting status is modeled in the DB CHECK constraint but no endpoint ever sets it. | `meeting.md` §2.1 | Whoever next touches `POST /partner/meetings/{id}/outcome` — small addition, not a new endpoint. |
| Contact-share disclosure (`meetings.py`'s `get_partner_buyer_summary`) does not yet gate on buyer verification status (only on the buyer's own consent, `meeting.status`, and exhibitor-staff ownership). | `meeting.md` §3, closing note | Same implementer as the verification-status column above — one more condition in an existing function, not a rewrite. |

## Value/naming mismatches worth knowing before you write client or test code

- `match_level` is **not** `HIGH|MEDIUM|POSSIBLE|LOW` as an external spec assumed — the shipped
  enum is `VERY_HIGH|HIGH|MEDIUM|LOW` (`app/services/matching/types.py`, `MATCH_LEVELS`). This is a
  value difference, not just a naming one — don't assume `POSSIBLE` maps to anything.
- Meeting status values are lowercase in the DB/API (`requested`, `accepted`, `counter_proposed`,
  ...), not the uppercase `REQUESTED/ACCEPTED/TIME_PROPOSED/...` an external spec assumed. Full
  mapping table in `meeting.md` §2.3.
- `/partner/meetings/{id}/accept|reject|propose-time` is one endpoint
  (`POST /partner/meetings/{id}/decision`) with an `action` discriminator, not three routes. See
  `meeting.md` §1.1 for why that's intentional, not a shortcut to "fix".
- `POST /buyer/matches` response fields: `match_session_id` → `recommendation_session_id`,
  `buyer_profile_version` → `profile_version`, `results[].reason` (singular) →
  `items[].reasons[]` (list). Full mapping in `buyer-matching.md` §3.

## Absolute-prohibition self-check for this run

- Did not edit `apps/api/app/api/v1/api.py`. ✅ (never opened it for writing; only referenced by
  path in prose.)
- Did not edit `apps/api/app/models/__init__.py`. ✅
- Did not edit `apps/user-web/lib/api-client.ts` or `.../types.ts`. ✅ (never touched
  `apps/user-web/**` at all.)
- Did not touch any other track's owned paths. ✅ — only wrote
  `.harness/contracts/buyer-matching.md`, `.harness/contracts/meeting.md`, and this handoff file.
- Did not touch database/migrations or any `apps/**` code. ✅ — read-only exploration of
  `apps/api/app/models/**` and `apps/api/app/api/v1/routers/**` for fact-finding; zero writes there.
- No kiosk PII collection concern — this track never touched kiosk flows.
- No new ontology concept codes invented — every concept-code reference in the two contract docs
  cites an existing code/namespace already present in the codebase (`BIZ_GOAL`, `MEETING_OUTCOME.*`,
  `FOLLOW_UP_ACTION.*`), or explicitly flags a namespace as "not yet seeded" using the same TODO
  language `meeting.py`/`meetings.py` already use.
- No AI-asserted values: this run did not touch any AI extraction path.
- No small-group statistics involved.

## Assumption/decision applied without stopping for user input

One Blocker-Score-≥7 item was resolved with the safest reversible default per the task's own
instruction ("apply the safest reversible default, state the assumption explicitly... and
continue"): the buyer verification status enum and its permission table (`buyer-matching.md` §2)
were **defined as a contract** but **not implemented** (no migration, no model/column change) —
the safest reversible choice, since defining a contract is trivially revisable and blocks nothing,
while adding a live DB column or endpoint under ambiguity would not be. This should be treated as
a proposal for the next track that touches `profile.buyer_need` or builds `/admin/buyers/*`, not as
an already-decided architecture — flag it back to the user/orchestrator if a conflicting design
surfaces elsewhere (e.g. if `docs/2026-backju-ai-matching-service-design.md` or a later CONTRACT
task defines buyer verification differently).
