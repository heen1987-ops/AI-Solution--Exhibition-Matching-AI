# Buyer profile & buyer↔exhibitor matching contract

> Task: WAVE2C-CONTRACTS (buyer profile / matching surface). Verifies which endpoints from the
> WAVE2C worker prompt already exist under the real repo layout (`apps/api/app/**`, not
> `src/modules/**` — see `.harness/assumptions.md` ASSUMPTION-003) and defines the parts that do
> not exist yet. This file does not change any code; it is a reference for the CONTRACTS track and
> for any WAVE2C worker touching buyer/matching endpoints.
>
> Precedence, per `.harness/assumptions.md` ASSUMPTION-002/DECISION-005: where an already-shipped,
> tested implementation differs from the WAVE2C prompt's assumed shape, the shipped implementation
> is treated as canonical and the prompt's shape is recorded as a "naming variant", not implemented
> as a second parallel surface.

## 1. Endpoint existence check

| Prompt-requested route | Status | Real route | Notes |
|---|---|---|---|
| `GET/PATCH /me/buyer-profile` | EXISTS (different name) | `GET /api/v1/profiles/me`, `PUT /api/v1/profiles/me/buyer-needs`, `PATCH /api/v1/profiles/me/attributes`, `PATCH /api/v1/profiles/me/user-type` | `apps/api/app/api/v1/routers/profile.py`. Buyer-specific fields live in `profile.buyer_need` (1:1 extension of `profile.user_profile`, `user_type='BUYER'`). No single "buyer-profile" resource — it is the general profile resource scoped by `user_type`. Same naming pattern already recorded in DECISION-005 (`/me/event-profile` ↔ `/profiles/me`). |
| `POST /buyer/matches` | EXISTS (different name) | `POST /api/v1/recommendations` (`recommendation_type` in request body selects the slate) | `apps/api/app/api/v1/routers/recommendations.py`, backed by `app/services/matching/orchestrator.py`. Already recorded in DECISION-005 (`/buyer/matches` ↔ `/recommendations` with `user_type=BUYER`). |
| `GET /buyer/matches/{id}` | EXISTS (different name) | `GET /api/v1/recommendation-sessions/{recommendation_session_id}/items` | Same router. `{id}` in the prompt = `recommendation_session_id` (see §3). |
| `POST /buyer/compare` | MISSING — genuine gap | none | No side-by-side compare endpoint exists anywhere in `apps/api`. See §5 for a proposed design (not implemented — CONTRACTS track only writes contracts, does not touch `apps/**`). |

Do not create a parallel `apps/api/app/api/v1/routers/buyer.py` for the first three rows — extend
`profile.py` / `recommendations.py` if new buyer-only fields are needed. A new router is
justified only for `POST /buyer/compare` if/when BACKEND picks it up.

## 2. Buyer verification status enum

**Finding: no such enum exists in the codebase today.** The closest existing signals are:

- `profile.user_account.authentication_state` (`apps/api/app/models/identity.py`): 2-value DB
  column `PHONE_VERIFIED | ACCOUNT_AUTHENTICATED`, exposed as a 3-value API concept together with
  the implicit `GUEST` state (no `user_account` row) — see that file's docstring, "authentication_state
  / actor_role에 대한 메모". This is identity/session verification, not buyer-business verification.
- `profile.buyer_need.business_email_verified` / `.company_verified` (`apps/api/app/models/profile.py`):
  two independent booleans, no combined status, no workflow state (no PENDING/REJECTED/SUSPENDED).
- `exhibition.*` uses a 6-value `VERIFICATION_STATUSES` for **exhibitor** supply-capability claims
  (`apps/api/app/models/exhibitor.py`: `SELF_DECLARED, DOCUMENT_SUBMITTED, OPERATOR_REVIEWED,
  VERIFIED, EXPIRED, REJECTED`) — a different domain (exhibitor claims about their own supply
  chain), not reusable as-is for buyer identity verification, but is the closest prior-art pattern
  and is used as a style reference below.

This is a **Blocker Score ≥ 7 gap** (high impact: gates meeting-request and contact-share
eligibility; hard to reverse once buyers start requesting meetings under an unverified flow;
real privacy/trust risk if unverified buyers reach exhibitor contact details; no existing
decision in `.harness/decisions.md` or `.harness/assumptions.md` resolves it). Applying the
safest reversible default: **defining** the enum here as the CONTRACTS deliverable the task asked
for, without touching `apps/api/app/models/**` or issuing a migration (out of this track's scope —
"Do NOT touch database/migrations or any apps/** code"). Whichever track implements buyer
verification should add a `verification_status` column to `profile.buyer_need` (nullable during
migration, `DEFAULT 'UNVERIFIED'` after backfill) following this contract.

### 2.1 Values and permissions

| Status | Meaning | `matching` (can call `POST /recommendations` as BUYER / receive buyer-tier results) | `meeting-request` (can call `POST /meetings`) | `contact-share` (can be the counterparty of an `interaction.meeting_contact_share` disclosure) |
|---|---|---|---|---|
| `UNVERIFIED` | Buyer profile created (`user_type='BUYER'`), no verification step attempted yet. Default state for every new buyer profile. | Yes — degraded/limited slate (see below) | No | No |
| `PENDING` | Buyer submitted verification evidence (business email domain, company registration doc, etc.); awaiting operator or automated review. | Yes — degraded/limited slate (unchanged from `UNVERIFIED`) | No | No |
| `VERIFIED` | Verification evidence accepted. Corresponds to `business_email_verified=true` and/or `company_verified=true` plus an explicit review step (not just the booleans alone — see §2.2). | Yes — full buyer-tier slate | Yes | Yes (subject to per-meeting `contact_share` consent — see `meeting.md` §3) |
| `LIMITED` | Verification partially accepted (e.g. business email verified but no company registration document, or verification expired and not yet renewed past a grace window). Operator judgment call, distinct from `PENDING` (which is "not reviewed yet") and from `VERIFIED` (which is "fully reviewed and accepted"). | Yes — full buyer-tier slate | Yes, but exhibitor UI should show a "미검증 등급 바이어" badge (see `PartnerBuyerSummaryResponse` — non-breaking additive field, not yet implemented) | Yes, but exhibitor's `contact_sharing_enabled`-style opt-in (not yet modeled — see §2.3) should be able to require `VERIFIED` and reject `LIMITED` |
| `REJECTED` | Verification evidence explicitly rejected by an operator (fraudulent, non-business email, etc.). | Yes — degraded/limited slate only, same as `UNVERIFIED` | No | No |
| `SUSPENDED` | Operator suspended an otherwise-verified buyer for policy violation (spam meeting requests, abusive behavior, etc.). Distinct from `REJECTED`: was verified once, now blocked. | No — recommendation requests should fail with `403 RESOURCE_FORBIDDEN` (reuse existing error code, see `error-codes.yaml`) | No | No |
| `EXPIRED` | Verification was accepted but its validity window (see `BuyerNeed.decision_timeline`-adjacent idea — verification itself needs its own `verified_at`/`valid_until`, not yet modeled) has lapsed. Distinguishes "never verified" from "was verified, needs renewal", so exhibitors/operators can prioritize renewal outreach differently from cold onboarding. | Yes — degraded/limited slate | No — must re-verify (or drop to `LIMITED` if partial evidence still valid; operator judgment) | No |

**Degraded/limited slate**, referenced above, means: `POST /recommendations` still succeeds for
`UNVERIFIED`/`PENDING`/`REJECTED`/`EXPIRED` buyers (do not hard-block browsing — MVP completion
criteria requires "buyer exhibitor search/matching" to work before verification friction), but the
matching policy layer (`app/services/matching/slate_policy.py`, `diversity_policy.py`) should treat
unverified buyers as ineligible for `EXCLUSIVE`/high-trust exhibitor slots the same way it already
treats cold-start profiles — this is a policy-tuning detail for the matching-policy owner, not a
new endpoint.

### 2.2 Why `VERIFIED` is not just "either boolean is true"

`buyer_need.business_email_verified` and `.company_verified` are currently set by whatever wrote
`BuyerNeed` (today: nothing does — no verification flow exists yet). Per AGENTS.md invariant 7
("AI output is a proposal. Deterministic validation and user/operator confirmation govern hard
constraints"), flipping `verification_status` to `VERIFIED` must be an explicit operator action
(`POST /admin/buyers/{id}/verify`, §4) or a fully deterministic automated check (e.g. business
email domain allow-list) — never inferred silently from partial signals. The two existing booleans
remain useful as *evidence flags* feeding into the operator's decision, not as the status itself.

### 2.3 Known follow-on gap (out of this track's scope, recorded for the backlog)

Exhibitor-side "accept contact from buyers below `VERIFIED`" preference (referenced in the
`LIMITED` row above) has no column today. `exhibition.exhibitor_buyer_preference`
(`apps/api/app/models/exhibitor.py`) models *what kind* of buyer an exhibitor wants (buyer_type/
channel/region/volume), not a minimum verification tier. Do not add this column from the
CONTRACTS track (no `apps/**` edits); record as an expansion candidate for whichever track owns
`exhibitor.py` next, referencing this section.

## 3. Buyer match request/response JSON shape

The prompt's assumed shape (`match_session_id`, `buyer_profile_version`, `policy_version`,
`results[]` with `rank/exhibitor_id/match_level/reason/reason_codes/unknown_fields/
meeting_available`) maps onto the **already-implemented** `POST /api/v1/recommendations` /
`GET /api/v1/recommendation-sessions/{id}/items` contract
(`apps/api/app/schemas/recommendation.py`) as follows:

| Prompt field | Real field | Notes |
|---|---|---|
| `match_session_id` | `recommendation_session_id` | UUID, PK of `matching.recommendation_session` (= `MatchRun`). |
| `buyer_profile_version` | `profile_version` | Int, FK-paired with `profile_id` into `profile.profile_version` (see `MatchRun.__table_args__` composite FK `["profile_id", "profile_version_id"] -> ["profile.profile_version.profile_id", ...]` in `apps/api/app/models/matching.py`). |
| `policy_version` | `policy_version` | Present as-is. Derived from `MatchRun.policy_version_id -> matching.match_policy_version`; the response exposes the human-readable version string, not the UUID. |
| — (not in prompt) | `ranking_version`, `explanation_version` | Two additional version fields the real contract already tracks (AGENTS.md invariant 3: "version immutable published artifacts"). Recommend the WAVE2C worker keep both — they are needed to reproduce why a given slate looked the way it did, independent of policy version. |
| `results[]` | `items[]` | List of `RecommendationItem`. |
| `results[].rank` | `items[].rank` | Present as-is, 1-based. |
| `results[].exhibitor_id` | `items[].exhibitor_id` | Present as-is (nullable — only populated when `object_type` resolves to an exhibitor-owned entity; see `_resolve_result_object_id` in `recommendations.py`). |
| `results[].match_level` = `HIGH \| MEDIUM \| POSSIBLE \| LOW` | `items[].match_level` = **`VERY_HIGH \| HIGH \| MEDIUM \| LOW`** (`apps/api/app/services/matching/types.py`, `MATCH_LEVELS`) | **Value mismatch, not just naming.** The real enum has 4 values but they are not the same 4 as the prompt's assumption — `VERY_HIGH` replaces `POSSIBLE` at the opposite end of the scale (`VERY_HIGH` = best match, not `POSSIBLE` = weakest speculative match). Per the precedence rule in this file's header, `VERY_HIGH/HIGH/MEDIUM/LOW` is canonical; do not add a `POSSIBLE` value or rename `VERY_HIGH`. If a worker's downstream code (UI, docs) was written against `HIGH/MEDIUM/POSSIBLE/LOW`, it must be corrected to match the shipped enum, not the other way around. |
| `results[].reason` (singular) | `items[].reasons[]` (list of `{code, text, evidence_refs}`) | Real contract already supports multiple stacked reasons per result (AGENTS.md invariant 5: "store provenance, evidence references"). Prompt's singular `reason` is a simplification; use `reasons[0].text` if a single display string is needed, but do not collapse the list in the API itself. |
| `results[].reason_codes` | `items[].reasons[].code` (one code per reason object, not a separate parallel array) | Same data, different shape. Derive prompt's flat `reason_codes: [...]` client-side as `items[].reasons.map(r => r.code)` if a WAVE2C consumer needs that exact shape — do not add a redundant field to the API response. |
| `results[].unknown_fields` | **MISSING — genuine gap** | No field in `RecommendationItem` currently states which of the buyer's hard-filter dimensions the matching engine could not evaluate due to missing/unknown exhibitor data (AGENTS.md invariant 7: "Unknown stays UNKNOWN, never silently coerced"). The closest existing signal is `cold_start_status` / `cold_start_reason_codes` (buyer-side data insufficiency), not exhibitor-side field-level unknowns. Recommend adding `unknown_fields: list[str]` (ontology `attribute_code`s or trade-condition field names the matcher treated as `UNKNOWN`, e.g. `"TRADE_CONDITION.EXPORT_STATUS"`) to `RecommendationItem` when the matching-explanation track next touches `explanation_generator.py` — additive, non-breaking. Not implemented here (out of CONTRACTS scope). |
| `results[].meeting_available` | `items[].availability.meeting` (bool, inside the `AvailabilityView` object, itself inside `context_details.availability` from `MatchResult.context_details`) | Present, just nested under `availability` alongside `open/tasting/purchase` rather than being a top-level field. |

### 3.1 Exhibitor public trade-condition value enum

Already implemented exactly as specified in the WAVE2C prompt — **no gap, no naming variant**:

```
TRADE_AVAILABILITY_STATUSES = ("YES", "NO", "CONDITIONAL", "NEGOTIABLE", "UNKNOWN")
```

`apps/api/app/models/exhibitor.py`, applied via CHECK constraint to `TradeCondition.oem_status`,
`.private_label_status`, `.export_status`. The module's own docstring ("거래조건 가용성 필드를
boolean이 아니라 상태코드로 설계한 이유") already documents the "unregistered vs. impossible"
separation this enum exists to express — directly satisfies AGENTS.md invariant 7's "Unknown stays
UNKNOWN, never silently coerced to YES or NO" for this specific field. `PUT
/partner/products/{product_id}/trade-conditions` (`apps/api/app/api/v1/routers/partner.py`) is the
only writer; there is no public-facing enum drift to reconcile.

## 4. `/admin/buyers` — genuine gap, proposed design

No `apps/api/app/api/v1/routers/admin*.py` exists at all today (confirmed: grepped `admin` across
`apps/api/app/api/v1/` — only incidental matches in `imports.py`/`partner.py` docstrings, no admin
router). `partner.py`'s own docstring explicitly says operator-approval endpoints
(`POST /api/v1/admin/exhibitors/{exhibitor_id}/approve`) were "out of this task's scope... it's
the operator/admin router owner's job" — so an admin router is expected to land from a separate
track, not yet done. Proposed shape for whichever track builds it, styled after the existing
`exhibitor` approval flow (`ExhibitorProfile.approval_status`, `MASTER_APPROVAL_STATUSES` pattern
in `exhibitor.py`) and the existing envelope/auth conventions in `profile.py`/`meetings.py`:

```
GET  /api/v1/admin/buyers?verification_status=&q=&cursor=&limit=
     -> Envelope[{ items: [{ profile_id, tenant_id, event_id, organization_type,
                              verification_status, business_email_verified,
                              company_verified, submitted_at, updated_at }],
                    next_cursor }]

GET  /api/v1/admin/buyers/{profile_id}
     -> Envelope[{ ...same row shape..., evidence: {...} }]
     # `evidence` = whatever the (not-yet-designed) verification submission flow stores;
     # out of scope to shape further here.

POST /api/v1/admin/buyers/{profile_id}/verify
     body: { note: str | None }
     -> sets verification_status = VERIFIED, requires actor role OPERATOR|ADMIN
        (same role-check pattern as partner.py's `_require_exhibitor_access`,
        via profile.user_role / profile.role, role_code IN ('OPERATOR','ADMIN'))
     -> Envelope[{ profile_id, verification_status: "VERIFIED", verified_at, verified_by_user_id }]

POST /api/v1/admin/buyers/{profile_id}/reject
     body: { reason_code: str, note: str | None }
     -> sets verification_status = REJECTED
     -> Envelope[{ profile_id, verification_status: "REJECTED", reason_code }]
```

Both actions should append an `audit.audit_log` row (reuse `AuditLog` from
`apps/api/app/models/consent.py`, same pattern already used in `meetings.py`'s
`get_partner_buyer_summary` for contact-view auditing) with
`resource_type="profile.buyer_need"`, `action_type="VERIFY"` / `"REJECT"`. Idempotency-Key
handling should follow the same in-process-cache pattern used in `meetings.py` until the shared
`integration.idempotency_record` table exists (see that file's TODO 2).

**Not implemented here** — CONTRACTS track owns `.harness/contracts/**` only; this section is the
handoff spec for the track that builds `apps/api/app/api/v1/routers/admin.py` (or extends an
existing router if one lands first — check prior art again before creating a new file, per
AGENTS.md).

## 5. `POST /buyer/compare` — genuine gap, proposed design

No compare endpoint exists. Proposed shape, reusing the same result-item structure as
`RecommendationItem` so client code can share rendering logic:

```
POST /api/v1/buyer/compare
     body: { exhibitor_ids: list[UUID] (2..5 items), recommendation_session_id: UUID | None }
     -> Envelope[{ items: [{ exhibitor_id, ...same per-item shape as RecommendationItem
                              minus rank..., trade_conditions: {...TradeConditionRead-shaped...} }] }]
```

`recommendation_session_id` is optional context (lets the compare view show the same `reasons[]`
already computed for that slate instead of recomputing); when omitted, the endpoint should compute
a fresh explanation using the same `explanation_generator.py` machinery `recommendations.py` uses.
`exhibitor_ids` must all belong to `APPROVED` `ExhibitorParticipation` rows for the caller's
`tenant_id`/`event_id`, same authorization boundary as `POST /meetings`'s participation lookup.
**Not implemented here** — design only.
