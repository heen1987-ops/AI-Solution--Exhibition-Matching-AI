# BAC-005 QA Test Request

Date: 2026-08-02
Requester: BACKEND
Target Owner: QA_SECURITY
Status: REQUESTED

## Scope

Please add DB-backed contract tests for kiosk anonymous session and QR handoff APIs:

- `POST /api/v1/kiosk/sessions`
- `DELETE /api/v1/kiosk/sessions/{guest_session_id}`
- `POST /api/v1/kiosk/qr-sessions`

## Required Coverage

- Active `exhibition.kiosk_device` creates a `profile.guest_session` with
  `entry_channel = 'KIOSK'`, requested `language`, no `converted_user_id`, and no PII.
- `exhibition.kiosk_config.idle_timeout_seconds` controls `expires_at`; default is
  90 seconds when no config row exists.
- Missing or non-`ACTIVE` kiosk devices return 404 `RESOURCE_NOT_FOUND`.
- Deleting an existing session returns 204, expires the session, and clears
  `entry_code`.
- Deleting a missing session still returns 204.
- QR handoff stores a fresh `entry_code` on the guest session and returns 201.
- Missing, expired, or non-kiosk guest sessions return 410 `QR_HANDOFF_EXPIRED`.
- Request schemas reject any accidental PII fields if strict model config is later
  added across v1 API DTOs.

## Guardrails

Do not introduce kiosk signup, contact input, persistent fingerprinting, precise indoor
navigation, or a QR handoff table. `profile.guest_session.entry_code` is the contract
storage point for this wave.
