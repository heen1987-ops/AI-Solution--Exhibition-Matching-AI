# QA Test Request: BAC-006 Buyer Matching and Meetings API

Date: 2026-08-02
Requester: BACKEND
Target QA task: BAC-009 or earlier API contract-test slice

## Requested Coverage

Add DB-backed FastAPI integration tests for:

- `GET /api/v1/buyer/matches`
  - Missing profile returns 401.
  - Non-buyer profile returns 403.
  - Buyer with no recommendation session returns an empty paginated result.
  - Buyer with recommendation results returns ordered results and reasons.
- `POST /api/v1/buyer/matches/{exhibitor_id}/meetings`
  - Non-buyer request returns 403.
  - Missing or unpublished exhibitor returns 404 `EXHIBITOR_NOT_PUBLISHED`.
  - Approved exhibitor with approved, consultation-enabled participation creates
    `interaction.meeting` with status `REQUESTED`.
  - `contact_disclosed` is false on creation.
- `PATCH /api/v1/meetings/{meeting_id}/status`
  - Cross-profile buyer request is denied.
  - Invalid status transition returns 409 `INVALID_STATE_TRANSITION`.
  - `CONFIRMED` creates or completes `interaction.meeting_contact_share`.
  - Rejected/cancelled transitions do not create contact share.

## Notes

Use the existing `backend/tests/conftest.py` DB skip convention. Do not assert
plaintext message storage; message encryption is intentionally deferred until an
encryption/KMS adapter exists.
