# CR-010 — Web guest session entry and personal My Event landing

Status: APPROVED
Requested: 2026-08-03
Approved by: explicit user direction to continue the web-first implementation and fix the reviewed user-entry blockers

## Problem

The active user web calls `POST /api/v1/sessions` before onboarding, but the frozen OpenAPI omitted
the route even though `docs/frontend-backend-ai-interface-spec.md` section 7.1 already defines it.
The call therefore returns 404 and prevents the matching engine from receiving a guest profile.
The living roadmap also requires Kakao/email personal links to open a mobile My Event page without
placing user identifiers in the URL.

## Approved contract

- `POST /api/v1/sessions` is a public web-entry operation.
- The request accepts `event_id`, `entry_channel` (`QR` or `WEB`), optional `entry_code`, optional
  web `device_type`, and optional language.
- A successful request atomically creates an anonymous guest session, a minimal general-visitor
  profile, and a visit session scoped to the same tenant and event.
- The raw guest credential is returned only in a `Secure`, `HttpOnly`, `SameSite=Lax`, `Path=/`,
  no-`Domain` `__Host-meet_ai_guest` cookie. Only its keyed digest is persisted.
- The response exposes opaque record IDs, event availability, minimum age, and expiry. It never
  exposes the guest credential.
- Dedicated kiosk values are rejected. Historical kiosk contracts remain inactive compatibility
  assets under CR-009.
- `/e/{event_slug}/my` exchanges an opaque, one-time CR-006 personal link, removes the token from
  browser history, uses `Referrer-Policy: no-referrer`, and rehydrates CSRF only from the verified
  server session.
- Phone OTP issuance, verification, and guest/account merge remain excluded until a provider,
  abuse-control policy, and privacy retention contract are approved.

## Compatibility

This is an additive minor contract update. Existing matching, profile, admin, and public search
contracts are unchanged.
