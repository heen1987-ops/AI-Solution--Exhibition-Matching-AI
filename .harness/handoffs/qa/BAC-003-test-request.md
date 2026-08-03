# QA Test Request: BAC-003 Favorites API

Date: 2026-08-02
Requester: BACKEND
Target QA task: BAC-009 or earlier API contract-test slice

## Requested Coverage

Add DB-backed FastAPI integration tests for:

- Missing `X-MeetAI-Profile-Id` returns 401 with `{error:{code: AUTHENTICATION_REQUIRED}}`.
- `X-MeetAI-User-Type: GUEST_WEB` returns 403 with `{error:{code: PERMISSION_DENIED}}`.
- `GET /api/v1/favorites` returns saved rows scoped to the current profile and paginated.
- `POST /api/v1/favorites` inserts an active recommendable.
- Duplicate save returns 409 `RESOURCE_CONFLICT`.
- Inactive or missing `exhibition.recommendable` returns 404 `RESOURCE_NOT_FOUND`.
- `DELETE /api/v1/favorites/{saved_recommendable_id}` is idempotent.
- Cross-profile delete does not remove another profile's saved row.

## Notes

Use the existing `backend/tests/conftest.py` DB skip convention. Do not create
PII fixtures; use synthetic UUIDs and existing schema seed helpers or local
minimal rows.
