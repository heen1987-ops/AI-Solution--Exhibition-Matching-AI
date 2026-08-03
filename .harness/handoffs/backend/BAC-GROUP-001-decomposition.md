# BAC-GROUP-001 Decomposition Handoff

Date: 2026-08-02
Track: BACKEND
Status: GROUP IN_PROGRESS

## Summary

`BAC-GROUP-001` was decomposed from a coarse Wave 2 group into concrete API
tasks `BAC-002` through `BAC-009`. The decomposition follows the frozen
`.harness/contracts/openapi.yaml` paths and operationIds rather than the older
narrative names in the roadmap where they differ.

## Created Tasks

- `BAC-002`: API request context and authorization guard scaffolding.
- `BAC-003`: Favorites API, backed by `profile.saved_recommendable`.
- `BAC-004`: Admin content approval API, backed by `ai.content_approval`.
- `BAC-005`: Kiosk session and QR handoff APIs.
- `BAC-006`: Buyer matches and meeting request/status APIs.
- `BAC-007`: Profile and guest conversion APIs.
- `BAC-008`: Search and recommendation API facade, blocked on `AIS-GROUP-001`.
- `BAC-009`: QA contract-test handoff, blocked until API tasks complete.

## Contract Notes

- Favorites are implemented under `/favorites` and `/favorites/{saved_recommendable_id}`.
- QR handoff is implemented under `/kiosk/qr-sessions`.
- Admin content approvals are implemented under `/admin/content-approvals`.
- Buyer meeting creation is implemented under `/buyer/matches/{exhibitor_id}/meetings`.
- Meeting status updates are implemented under `/meetings/{meeting_id}/status`.
- Profile read/update is implemented under `/profile/me` and `/profile/me/attributes`.
- Guest QR conversion is implemented under `/guest/convert` per W-8/roadmap; static
  contract sync is recorded as follow-up because the frozen OpenAPI file omitted that
  explicit path.

## Guardrails

- Do not add kiosk signup or kiosk PII input.
- Do not expose contact details before a meeting reaches `CONFIRMED`.
- Do not implement CRM, payments, contracts, automatic approval, or real-time
  learning as part of these tasks.
- Use the common error envelope from CTR-002/CTR-004.
