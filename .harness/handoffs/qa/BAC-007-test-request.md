# BAC-007 QA Test Request

Date: 2026-08-02
Requester: BACKEND
Target Owner: QA_SECURITY
Status: REQUESTED

## Scope

Please add DB-backed contract tests for profile and guest conversion APIs:

- `GET /api/v1/profile/me`
- `PATCH /api/v1/profile/me/attributes`
- `POST /api/v1/guest/convert`

## Required Coverage

- Missing profile header on `GET /profile/me` and `PATCH /profile/me/attributes`
  returns 401 `AUTHENTICATION_REQUIRED`.
- `GUEST_WEB` cannot patch profile attributes and receives 403
  `PERMISSION_DENIED`.
- `GET /profile/me` returns DB user type mapped to API user type:
  `GENERAL_VISITOR -> GENERAL_REGISTERED`, `BUYER -> BUYER_REGISTERED`.
- `PATCH /profile/me/attributes` rejects stale `row_version` with 409
  `RESOURCE_CONFLICT`.
- `PATCH /profile/me/attributes` rejects unknown, disabled, or non-assignable
  ontology codes with 422 `VALIDATION_ERROR`.
- Successful PATCH writes `profile.profile_attribute` rows with
  `source_type = USER_EDITED`, increments profile version fields, and creates
  `profile.profile_version`.
- `POST /guest/convert` requires `X-MeetAI-User-Id` and an active
  `profile.user_account`.
- QR mismatch, expired session, or missing session returns 410
  `QR_HANDOFF_EXPIRED`.
- Already converted guest sessions return 409 `RESOURCE_CONFLICT`.
- Successful conversion clears `guest_session.entry_code`, sets
  `converted_user_id/converted_at`, and transfers guest-owned visit sessions to
  the registered profile.
- Successful conversion does not create or update `identity.user_identity` and
  does not persist name, phone, email, address, or login ID.

## Contract Note

FastAPI OpenAPI now exposes `/api/v1/guest/convert`; the frozen static contract
file did not have that explicit path even though the redesign roadmap requires
it. Please flag whether CONTRACTS should sync `.harness/contracts/openapi.yaml`
through the formal change procedure.
