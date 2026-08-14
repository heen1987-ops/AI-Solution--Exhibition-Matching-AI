# Meeting / consultation contract

> Task: WAVE2C-CONTRACTS (meeting/consultation surface). Verifies which endpoints from the
> WAVE2C worker prompt already exist under the real repo layout and defines the status machine,
> contact-share disclosure conditions, and the one genuine endpoint gap (`/admin/buyers/*`, covered
> in `buyer-matching.md` §4, not repeated here).
>
> Precedence, per `.harness/assumptions.md` ASSUMPTION-002/DECISION-005 and the extensive
> docstring already present in `apps/api/app/models/meeting.py` (its own "상담 상태값 표기 대문자
> vs 소문자에 대한 문서 간 불일치 처리" section): the **shipped** implementation's lowercase status
> values are canonical. This file documents that shipped machine and maps the WAVE2C prompt's
> assumed uppercase enum onto it as a naming variant — it does not introduce a second enum.

## 1. Endpoint existence check

| Prompt-requested route | Status | Real route | Notes |
|---|---|---|---|
| `POST /meetings` | EXISTS | `POST /api/v1/meetings` | `apps/api/app/api/v1/routers/meetings.py`. Full implementation: atomic slot reservation, idempotency key, contact-share consent capture, ontology topic resolution. |
| `GET /me/meetings` | EXISTS (different name) | `GET /api/v1/meetings` | Buyer subject already derives the "me" scope from the auth-stub header (`X-Profile-Id`, `_buyer_profile_header`) — same pattern as `/profiles/me` not needing a `{profile_id}` path param. No `/me/meetings` alias exists or is needed; do not add one. |
| `GET /meetings/{id}` | EXISTS | `GET /api/v1/meetings/{meeting_id}` | As specified. |
| `PATCH /meetings/{id}` | EXISTS (different shape) | `POST /api/v1/meetings/{meeting_id}/cancel`, `POST /api/v1/meetings/{meeting_id}/respond` | The real API models buyer-side state transitions as two explicit action endpoints (cancel; accept/decline a counter-proposal) rather than a generic `PATCH` with a `status` field — consistent with the optimistic-locking + status-history design (`MeetingStatusHistory` append-only log) already built. A generic `PATCH` that accepted an arbitrary `status` value would bypass the transition-legality checks each action endpoint enforces (`_BUYER_CANCELLABLE_STATUSES`, "only from `counter_proposed`" for `/respond`). Do not add a generic `PATCH` — it would create a second, less-safe path to the same state changes. |
| `GET /partner/meetings` | EXISTS | `GET /api/v1/partner/meetings` | Same file. Scoped by `participation_id` (a whole exhibitor team, not per-staff), see file's own comment on wireframes §8 E-02. |
| `/partner/meetings/{id}/accept` | EXISTS (merged) | `POST /api/v1/partner/meetings/{meeting_id}/decision` with `{"action": "ACCEPT", "slot_id": ..., "version": ...}` | See §1.1. |
| `/partner/meetings/{id}/reject` | EXISTS (merged) | same endpoint, `{"action": "REJECT", "version": ...}` | See §1.1. |
| `/partner/meetings/{id}/propose-time` | EXISTS (merged) | same endpoint, `{"action": "COUNTER_PROPOSE", "slot_id": ..., "version": ...}` | See §1.1. |

Also already implemented, not requested by the prompt but part of the same domain and worth
knowing about before any WAVE2C worker touches this area: `GET
/exhibitors/{exhibitor_id}/availability` (12.2), `GET
/partner/meetings/{meeting_id}/buyer-summary` (E-03, also the contact-disclosure trigger — §3),
`POST /partner/meetings/{meeting_id}/outcome` (E-04, records `Lead`/`FollowUp`).

### 1.1 Why three prompt endpoints collapsed into one `/decision` endpoint

`apps/api/app/schemas/meeting.py`'s `PartnerDecisionRequest` uses a single `action: Literal["ACCEPT",
"REJECT", "COUNTER_PROPOSE"]` discriminator instead of three routes. This is a legitimate, already-
tested design choice (all three actions share the same optimistic-locking/`row_version` check, the
same slot-reservation/-release machinery, and the same `MeetingStatusHistory` write — splitting them
into three routes would mean tripling that shared logic or extracting it into a helper anyway). Do
not add three thin wrapper routes that each call the same handler with a fixed `action` — that adds
a second surface with no behavioral difference and doubles the OpenAPI surface for no benefit. If a
WAVE2C consumer (e.g. admin dashboard generator) specifically needs REST-verb-per-action routes,
treat that as a client-side convenience wrapper, not a reason to change the server contract.

## 2. Meeting status machine

### 2.1 Canonical values (shipped, `apps/api/app/models/meeting.py` `MEETING_STATUSES`)

```
draft -> requested -> accepted -> completed
                    -> counter_proposed -> accepted -> completed
                    -> counter_proposed -> cancelled
                    -> rejected
                    -> cancelled
accepted -> no_show   (not currently settable by any implemented endpoint — see §2.3)
```

| Status | Meaning | Set by |
|---|---|---|
| `draft` | Reserved for future multi-step meeting creation flows; no implemented endpoint currently leaves a meeting in this state — `POST /meetings` writes `requested` directly. Kept in the CHECK constraint for forward compatibility (model docstring). | — |
| `requested` | Buyer submitted the request; a candidate slot has been provisionally reserved (`_reserve_slot`, atomic conditional `UPDATE`). | `POST /meetings` |
| `accepted` | Exhibitor accepted a slot (either the buyer's original candidate or one the exhibitor counter-proposed and the buyer then accepted). `confirmed_start`/`confirmed_end`/`confirmed_slot_id` are populated. This is `MEETING_CONFIRMED_STATUS` — the only status where the DB-level `EXCLUDE` constraints (no double-booked staff/buyer time range) apply and where contact-share can disclose (§3). | `POST /partner/meetings/{id}/decision` (`ACCEPT`), `POST /meetings/{id}/respond` (`ACCEPT_COUNTER`) |
| `counter_proposed` | Exhibitor proposed a different slot than the buyer requested. | `POST /partner/meetings/{id}/decision` (`COUNTER_PROPOSE`) |
| `rejected` | Exhibitor declined outright. | `POST /partner/meetings/{id}/decision` (`REJECT`) |
| `cancelled` | Buyer cancelled (own request, or declined a counter-proposal). | `POST /meetings/{id}/cancel`, `POST /meetings/{id}/respond` (`DECLINE`) |
| `completed` | Exhibitor recorded an outcome (`Lead`/`MeetingOutcomeRequest`) for an `accepted` meeting. | `POST /partner/meetings/{id}/outcome` (auto-transitions `accepted -> completed` as a side effect) |
| `no_show` | Modeled in the CHECK constraint and in the wireframe spec (§6.2) but **no implemented endpoint currently sets it** — genuine small gap, not blocking (MVP completion criteria doesn't call out no-show tracking explicitly). Record as an expansion candidate for the outcome-recording endpoint (`POST /partner/meetings/{id}/outcome` could accept a `no_show: bool` alternative to the current `is_qualified_lead` outcome shape) rather than a new endpoint. | — (gap) |

### 2.2 Allowed transitions (as actually enforced in code, not just the value list)

Source: `_BUYER_CANCELLABLE_STATUSES`, `_DECIDABLE_SOURCE_STATUSES`, `_OUTCOME_ALLOWED_SOURCE_STATUSES`
in `apps/api/app/api/v1/routers/meetings.py`.

| From | Action | Actor | To |
|---|---|---|---|
| `requested`, `counter_proposed` | `ACCEPT` | exhibitor (`/decision`) | `accepted` |
| `requested`, `counter_proposed` | `REJECT` | exhibitor (`/decision`) | `rejected` |
| `requested` | `COUNTER_PROPOSE` | exhibitor (`/decision`) | `counter_proposed` (**not** allowed from an already-`counter_proposed` state — an exhibitor cannot counter-propose twice in a row without the buyer responding first) |
| `counter_proposed` | `ACCEPT_COUNTER` | buyer (`/respond`) | `accepted` |
| `counter_proposed` | `DECLINE` | buyer (`/respond`) | `cancelled` |
| `draft`, `requested`, `accepted`, `counter_proposed` | cancel | buyer (`/cancel`) | `cancelled` |
| `accepted`, `completed` | record outcome | exhibitor (`/outcome`) | `accepted -> completed`; already-`completed` meetings can have outcome fields updated/re-recorded without a further status change |

Every transition writes an append-only `MeetingStatusHistory` row (`previous_status`, `new_status`,
`changed_by_user_id`, optional `reason_code`) — satisfies AGENTS.md invariant 5 ("append-only
activity needed to reproduce decisions"). Concurrency: buyer/exhibitor decision endpoints take
`SELECT ... FOR UPDATE` + check `row_version` (optimistic lock, `409 MEETING_VERSION_CONFLICT` on
mismatch); slot double-booking is additionally guarded by a DB-level `EXCLUDE` constraint
(`409 MEETING_CONFLICT` on `IntegrityError`) as a defense-in-depth backstop.

### 2.3 Mapping to the WAVE2C prompt's assumed enum

| Prompt value | Shipped value | Notes |
|---|---|---|
| `REQUESTED` | `requested` | Case only. |
| `ACCEPTED` | `accepted` | Case only. |
| `TIME_PROPOSED` | `counter_proposed` | Naming, not just case — "time proposed" in the prompt is the exhibitor's counter-offer, same concept as `counter_proposed`. |
| `REJECTED` | `rejected` | Case only. |
| `CANCELLED` | `cancelled` | Case only. Prompt's single `CANCELLED` does not distinguish buyer- vs. exhibitor-initiated cancellation the way `docs/frontend-backend-ai-interface-spec.md`'s draft (`CANCELLED_BY_BUYER`/`CANCELLED_BY_EXHIBITOR`) does — the shipped model also doesn't distinguish (single `cancelled` value); `MeetingStatusHistory.changed_by_user_id` is where that distinction actually lives if needed later. |
| `COMPLETED` | `completed` | Case only. |
| (not in prompt) | `draft`, `no_show` | Two shipped/reserved values the prompt's enum omits entirely — see §2.1 for their status. |

**Do not** introduce an uppercase parallel enum anywhere in `apps/api/**` to match the prompt —
API responses already serialize the lowercase DB values as-is (`MeetingResponse.status: str`, no
enum coercion in `apps/api/app/schemas/meeting.py`). Any new WAVE2C client code should consume the
lowercase values directly.

## 3. Contact-share disclosure conditions

Buyer contact info (`identity.user_identity.name_enc`/`phone_enc`/`email_enc`) is disclosed to an
exhibitor **only** when **all** of the following hold simultaneously (enforced in
`get_partner_buyer_summary`, `apps/api/app/api/v1/routers/meetings.py`) — this is the concrete
implementation of AGENTS.md's absolute prohibition "Meeting/contact details stay hidden until the
exhibitor accepts a request":

1. `meeting.status == "accepted"` (`MEETING_CONFIRMED_STATUS`) — not `requested`, not
   `counter_proposed`. A pending or merely-proposed meeting never discloses contact info.
2. An `interaction.meeting_contact_share` row exists for this `meeting_id` **and**
   `accepted_at IS NOT NULL` — i.e. the buyer explicitly opted in to contact sharing at request
   time (`MeetingCreateRequest.contact_share.accepted=true`, with a valid
   `consent_policy` document version resolved at creation time). A meeting created without
   `contact_share` never has this row at all, so this condition alone already blocks disclosure for
   buyers who never consented.
3. The requesting exhibitor staff member (`staff_id` header) belongs to the meeting's
   `participation_id` (existing `_load_active_staff` + `meeting.participation_id != staff.participation_id`
   check earlier in the same handler) — i.e. only the specific exhibitor team the meeting is with,
   never any other exhibitor.
4. Field-level scoping: only the fields the buyer listed in `contact_share.shared_fields` at
   request time are returned (`ALLOWED_CONTACT_SHARE_FIELDS = NAME, PHONE, BUSINESS_EMAIL, EMAIL` in
   `apps/api/app/schemas/meeting.py`) — a buyer who shared only `PHONE` never has `NAME`/`EMAIL`
   disclosed even once condition 1-3 are satisfied.

When all four hold, the first successful disclosure additionally: stamps
`meeting_contact_share.disclosed_at`/`.disclosed_to_user_id` (so repeat views by the same or a
different staff member don't re-trigger the audit write) and appends an `audit.audit_log` row
(`action_type="VIEW"`, `resource_type="interaction.meeting_contact_share"`,
`reason_code="PARTNER_BUYER_CONTACT_VIEW"`) — satisfies AGENTS.md invariant 6 (observability) and
invariant 5 (provenance) for this specific privacy-sensitive read path.

**Note on the buyer verification status gap (`buyer-matching.md` §2):** condition 2 above (explicit
buyer opt-in) is currently the *only* gate tied to buyer identity/trust — there is no additional
check that the buyer is `VERIFIED` before contact can be shared. Per `buyer-matching.md` §2.1's
permission table, `contact-share` should require at minimum `VERIFIED` (or exhibitor-opted-in
`LIMITED`); until the `verification_status` column and its check land, this is a **known gap**
between the intended trust model and the shipped enforcement — flagged here so the eventual
verification-status implementer knows exactly which function (`get_partner_buyer_summary`) needs
one more condition added, not a rewrite.

## 4. Non-goals confirmed against `PROJECT_SCOPE.md`

`PROJECT_SCOPE.md`'s exclusions list rules out "complex meeting-room auto-assignment" — the shipped
design's `staff_id`/`booth_id` on `AvailabilitySlot` are simple direct assignments (an exhibitor
staff member opens a slot; the slot carries its own staff/booth), not an auto-assignment engine.
No contract change needed here; noted only so a WAVE2C worker doesn't mistake the existing
`_reserve_slot` atomic-UPDATE logic for something that needs a "smarter" auto-assignment layer.
