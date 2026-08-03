# BAC-010 DB Contract Test Request

Date: 2026-08-02
Requester: BACKEND
Target Track: QA_SECURITY

Please add DB-backed contract tests for the CR-001 guest web session APIs:

- `POST /api/v1/guest/sessions`
- `GET /api/v1/guest/sessions/{guest_session_id}`
- `POST /api/v1/guest/sessions/{guest_session_id}/favorites`
- `DELETE /api/v1/guest/sessions/{guest_session_id}/favorites/{temporary_favorite_id}`
- `POST /api/v1/guest/sessions/{guest_session_id}/convert`

Required cases:

- Starting a session creates `profile.guest_session` with `entry_channel='WEB'`,
  `device_type='MOBILE_WEB'`, requested language, no PII, and a future
  `expires_at`.
- Session lookup returns `ACTIVE` and temporary favorites for an active session.
- Expired sessions return `410 GUEST_SESSION_EXPIRED`.
- Temporary favorites create a guest-session-owned temporary `profile.user_profile`
  and `profile.saved_recommendable`; duplicate saves return `409 RESOURCE_CONFLICT`.
- Removing a temporary favorite is scoped to the same `guest_session_id`.
- Conversion with `transfer_temporary_favorites=true` moves saved recommendables to
  the authenticated registered profile.
- Invalid `profile_link_token` returns `410 WEB_ENTRY_LINK_EXPIRED`.
- Converted sessions cannot be converted again and return `409 RESOURCE_CONFLICT`.

Guardrails:

- Do not add name, phone, email, address, login ID, or fingerprint fields.
- Do not extend `/api/v1/kiosk/*`; those routes are deprecated after CR-001.
