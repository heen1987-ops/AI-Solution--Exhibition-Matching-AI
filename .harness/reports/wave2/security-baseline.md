# QA-003: Security/Privacy Baseline Report (Wave 2)

Scope: unapproved-data exposure, kiosk anonymity, QR handoff signing, absolute-rule compliance.

## Verdict: PASS

## 1. Unapproved exhibitor/product data never reaches public output

Traced every public/anonymous read path down to its SQL:

- `apps/api/app/api/v1/routers/exhibition_public.py` (GET /events/{id}, /events/{id}/exhibitors,
  /exhibitors/{id}, /exhibitors/{id}/products, /events/{id}/booths, /booths/{id},
  /events/{id}/map) → `app.services.exhibition_public` → `app.services
  .exhibition_public_repository`. The repository's `_approved_participation_stmt()` hard-codes,
  for every query in the module:
  - `Exhibitor.master_approval_status == "APPROVED"` and `Exhibitor.deleted_at IS NULL`
  - `ExhibitorParticipation.participation_status == "APPROVED"`
  - `Event.event_status == "OPEN"`
  and `fetch_products_by_participation` / `fetch_images_by_product` additionally require
  `Product.master_approval_status == "APPROVED"`, `Product.deleted_at IS NULL`,
  `EventProduct.approval_status == "APPROVED"`, `ProductImage.approval_status == "APPROVED"`.
  These filters live in the repository, not the router, so no caller can bypass them.

- `apps/api/app/api/v1/routers/search.py` (POST /search, GET /search/{id}) and
  `apps/api/app/api/v1/routers/kiosk.py` (POST /kiosk/sessions/{id}/search) both call the same
  `app.services.catalog_search.search_approved_catalog()`. Its `_candidate_pool_stmt()` joins
  require, in one statement:
  - `ExhibitorParticipation.participation_status == "APPROVED"`
  - `Exhibitor.master_approval_status == "APPROVED"`, `Exhibitor.deleted_at IS NULL`
  - `EventProduct.approval_status == "APPROVED"`
  - `Product.master_approval_status == "APPROVED"`, `Product.deleted_at IS NULL`
  - `Booth.operating_status IN ("OPEN", "PAUSED")`
  and the function separately checks `Event.event_status == "OPEN"` before running any query,
  returning `[]` for unknown/inactive events rather than erroring. Structured (ontology-code)
  matches additionally require `ProductAttribute.review_status == "APPROVED"`
  (`_structured_matches`), so an AI-extracted-but-unreviewed attribute cannot pull an item into
  results even indirectly.
  - Both the free-text and pure-category-browse branches only add a result to `ranked` if it
    survived the approved candidate pool `_candidate_pool_stmt()` produced — there is no code
    path in `search_approved_catalog` that re-adds a row bypassing that pool.

- Verified no router in this set queries `Exhibitor`/`Product`/`ExhibitorParticipation` directly
  without going through the approval-filtered repository/service functions above.

**Result**: unapproved exhibitor/product data cannot reach `/events/*`, `/exhibitors/*`,
`/booths/*`, `/search`, or `/kiosk/sessions/*/search` responses. PASS.

## 2. Kiosk collects no personal data

- No `<input>`/`<textarea>` element exists anywhere in `apps/kiosk/**`.
- `apps/api/app/models/kiosk.py` (`KioskSession`, `KioskQrHandoff`) and
  `apps/api/app/schemas/kiosk.py` contain no name/phone/email/password columns or fields —
  confirmed by direct read, not just docstring claims.
- `apps/kiosk/lib/types.ts` (`StoredKioskState`) persists only: language, session metadata,
  query text, category codes, results, interpreted concepts, timestamp — nothing identity-linked.
- Session TTL: `KioskConfigResponse.session_timeout_seconds` is constrained
  `Field(ge=60, le=120)` in `apps/api/app/schemas/kiosk.py`, matching the 60–120s requirement;
  `compute_session_expiry`/`is_session_expired` in `apps/api/app/models/kiosk.py` implement the
  expiry check purely (no background sweep — timer enforcement is documented as the
  frontend/worker's job, consistent with the redesign spec).

**Result**: PASS — kiosk module collects no identity/contact/long-lived-profile data anywhere
in the stack (frontend state, API schema, or DB model).

## 3. QR handoff token is signed, expiring, and contains no personal data

`apps/api/app/services/kiosk.py`:

- `issue_handoff_token()` builds a payload of exactly `{handoff_id, event_id, expires_at}` —
  no contact info, no selected-result content (`selected_result_ids` stays server-side in Redis
  + the `kiosk_qr_handoff` audit row, never inside the token itself).
- The payload is HMAC-SHA256 signed via `compute_webhook_signature`, using a
  purpose-scoped secret derived from the app's shared secret via `derive_webhook_secret`
  (`_HANDOFF_SECRET_PURPOSE`) — a leaked webhook secret from another purpose cannot forge a
  handoff token and vice versa.
- `verify_handoff_token()` checks the signature via `verify_webhook_signature` and then
  independently checks `expires_at <= now` and raises `ValueError("expired handoff token")` if
  the token is stale — expired tokens are rejected by construction, not by convention.
- `KioskHandoffRequest`/response schemas (`apps/api/app/schemas/kiosk.py`) carry no personal
  fields either.

**Result**: PASS — matches BACKEND-006's acceptance criterion "QR handoff 토큰은 서명+만료시각
포함, 페이로드에 개인정보 없음" exactly.

## 4. Contact details hidden pre-acceptance

Out of this wave's owned_paths (`meetings.py` is pre-existing/BACKEND-004, not part of the
BACKEND-006/008/KIOSK/ADMIN/AISEARCH-002 set under review) — not re-audited here; no new code in
this wave touches meeting/contact-reveal logic. No finding either way; out of scope for QA-003's
assigned tracks.

## 5. Absolute-rule spot checks specific to this wave

- Ontology hardcoding: none found (see contract-compliance.md §3) — both `ai/query_interpreter
  .py` and the interim `search_query_interpreter.py` resolve exclusively through
  `meet_ai.ontology.load_catalog()`.
- No temporary mocks masquerading as production logic found in the reviewed files — the one
  explicit stub (`apps/admin` `SessionSwitcher`/`auth-state.ts`) is clearly labeled in-UI
  ("임시세션" badge) and in code comments as a dev stand-in, not disguised as real auth.

## Summary

| Check | Result |
|---|---|
| Public catalog endpoints filter to APPROVED/OPEN only, filter lives in repository not router | PASS |
| Search (`/search`, `/kiosk/*/search`) filters to APPROVED/OPEN + reviewed product attributes only | PASS |
| Kiosk collects zero personal data (UI, storage, API schema, DB model) | PASS |
| Kiosk session TTL bounded 60–120s with explicit expiry check | PASS |
| QR handoff token signed (HMAC, purpose-scoped secret), expiry-checked, PII-free payload | PASS |
| Dev-only admin auth stub is clearly labeled, not disguised as real login | PASS (documented gap, see scope-compliance.md) |
