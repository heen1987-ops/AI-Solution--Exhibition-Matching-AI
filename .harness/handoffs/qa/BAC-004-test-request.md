# QA Test Request: BAC-004 Admin Content Approval API

Date: 2026-08-02
Requester: BACKEND
Target QA task: BAC-009 or earlier API contract-test slice

## Requested Coverage

Add DB-backed FastAPI integration tests for:

- Non-operator request returns 403 `PERMISSION_DENIED`.
- Operator request without `X-MeetAI-User-Id` returns 401 `AUTHENTICATION_REQUIRED`.
- Missing exhibitor returns 404 `RESOURCE_NOT_FOUND`.
- Existing exhibitor without source document returns 404 `RESOURCE_NOT_FOUND`.
- Valid operator + exhibitor + source document creates `ai.content_approval`.
- Valid approval updates `exhibition.exhibitor.master_approval_status`.
- `APPROVED` and `REJECTED` decisions both work.
- The endpoint does not expose or require PII fixtures.

## Notes

Use the existing `backend/tests/conftest.py` DB skip convention. The current
CTR-002 contract only supplies `exhibitor_id`, so the implementation uses the
latest `ai.source_document` for that exhibitor as the approval target.
