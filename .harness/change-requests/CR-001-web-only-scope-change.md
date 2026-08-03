# CR-001 - WEB_ONLY Scope Change

Date: 2026-08-02
Status: APPLIED_CONTRACT_SYNC_DONE
Source: `/Users/ppp/.codex/attachments/d6e8f232-34fa-4609-84ba-4cd4e7fd576b/pasted-text.txt`

## Requested Decision

Adopt a mobile-first web-only channel strategy:

- `WEB_ONLY = TRUE`
- `KIOSK_MODULE = EXCLUDED`
- `APP_INSTALL = NOT_REQUIRED`
- `GUEST_SEARCH = ENABLED`
- `REGISTERED_PERSONALIZATION = ENABLED`
- `BUYER_MATCHING = ENABLED`

Requested channels:

- `REGISTERED_WEB`
- `GUEST_WEB`
- `BUYER_WEB`
- `ADMIN_PARTNER_WEB`

Requested entry methods:

- Event website
- QR
- Short URL
- Email link
- Registration link

## Conflict With Current Frozen Baseline

Current `AGENTS.md` and frozen redesign-v2 contracts define three modules:

- Web hyper-personalization
- Portable kiosk search
- Common AI/data platform

The new document explicitly removes dedicated kiosk work and replaces kiosk handoff
with guest web entry/profile-link flows. This conflicts with:

- `AGENTS.md` DEC-002 and project goal summary.
- `.harness/contracts/openapi.yaml` `/kiosk/*` paths.
- `.harness/contracts/domain-model.md` `KioskDevice`, `KioskConfig`,
  `KioskSession`, and `QrHandoff` mappings.
- `.harness/contracts/event-catalog.yaml` `KIOSK.*` events.
- Existing backend implementation for `BAC-005`.
- Existing scaffold and smoke coverage for `apps/kiosk`.
- `AIS-GROUP-001` scope that still mentions kiosk scoring.

## Required Contract Work

Before any destructive change:

1. Update canonical scope documents through CONTRACTS ownership.
2. Replace `KIOSK` channel contracts with `GUEST_WEB` contracts.
3. Add or confirm guest web session APIs:
   - `POST /api/v1/guest/sessions`
   - `GET /api/v1/guest/sessions/{session_id}`
   - `POST /api/v1/guest/sessions/{session_id}/search`
   - `POST /api/v1/guest/sessions/{session_id}/favorites`
   - `DELETE /api/v1/guest/sessions/{session_id}/favorites/{id}`
   - `POST /api/v1/guest/sessions/{session_id}/convert`
4. Reclassify existing kiosk DB objects and API code as deprecated until a safe
   cleanup migration is approved.
5. Rewrite `AIS-GROUP-001` from "kiosk score" to "guest web search quality".
6. Replace kiosk E2E smoke with mobile guest web E2E smoke.

## Immediate Harness Action

CR-001 has been applied to the canonical harness baseline. Further kiosk-specific
feature work is superseded by guest web work unless a new approved change request
explicitly reintroduces kiosk scope.

## Applied Contract Sync

Updated canonical files:

- `AGENTS.md`
- `PROJECT_SCOPE.md`
- `.harness/decisions.md` (`DEC-011`)
- `.harness/contracts/openapi.yaml`
- `.harness/contracts/domain-model.md`
- `.harness/contracts/event-catalog.yaml`
- `.harness/contracts/error-codes.yaml`
- `.harness/contracts/ontology.yaml`
- `.harness/backlog.yaml`
- `.harness/state.json`
- `.harness/quality-gates.yaml`

Follow-up tasks:

- `BAC-010`: align backend implementation to `/guest/sessions` WEB_ONLY contract.
- `AIS-GROUP-001`: redefine search quality around guest web/session intent instead
  of kiosk scoring.
- `QAS-007`: replace kiosk smoke and PII checks with guest web mobile smoke and
  guest web PII checks.
- `CTR-011`: plan safe cleanup for deprecated kiosk tables/API/app artifacts.
