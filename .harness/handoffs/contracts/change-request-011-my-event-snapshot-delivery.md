# CR-011 — My Event snapshot delivery boundary

Status: APPROVED
Requested: 2026-08-03
Approved by: explicit user direction to separate matching calculation from user delivery and make
the mobile My Event page the primary product surface

## Problem

The matching pipeline already persists immutable `matching.recommendation_session` snapshots and
the browser can establish a verified event-scoped session through an opaque personal link. However,
the active user web calls `GET /api/v1/home` while the backend does not publish that route, and the
personal-link landing only renders navigation links. The stored matching result therefore is not
delivered on the primary My Event surface.

## Approved contract

- `POST /api/v1/recommendations` remains the explicit calculation command. It may be invoked by an
  authorized synchronous workflow or a later batch worker and persists a versioned snapshot.
- `GET /api/v1/home` is a delivery-only query. It must never invoke the matching orchestrator, an
  LLM, or any external AI provider.
- `GET /api/v1/home` resolves the verified tenant, event, and profile from the server session and
  returns the newest owned `ACTIVE` recommendation snapshot and its persisted items.
- An expired snapshot may be returned with `stale=true`; an invalidated snapshot is never returned.
- If no snapshot exists, the route returns `RECOMMENDATION_NOT_READY` with HTTP 404. It does not
  silently calculate a new result or relax constraints.
- `/e/{event_slug}/my` exchanges the opaque personal link as already frozen by CR-010, removes the
  token from browser history, and then renders the actual My Event dashboard from `GET /home`.
- The initial My Event surface renders up to ten persisted recommendation cards with grounded
  reasons and supports save, explicit dismiss, detail, and eligible meeting actions. It does not
  expose the internal numeric score.
- Kakao Alimtalk, SMS, and email remain delivery adapters that link to My Event. This change does
  not implement a provider integration or expand message frequency.
- Dedicated kiosk runtime and handoff development remain excluded under CR-009.

## Compatibility

This is an additive minor API operation already described by
`docs/frontend-backend-ai-interface-spec.md` section 9.3. Existing calculation, session-item,
interaction, authentication, and meeting operations remain unchanged.
