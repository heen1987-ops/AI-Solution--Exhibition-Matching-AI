# CR-009 — Web-first channels and kiosk exclusion

Status: APPROVED
Requested: 2026-08-02
Approved by: explicit user decision in the living product-roadmap conversation and current task

## Problem

The earlier scope treated a dedicated on-site kiosk as a first-class service channel. The event is
not expected to operate intermediate kiosks, and asking visitors to locate shared hardware adds
installation, queueing, privacy, network, handoff, and operations costs that do not serve the core
matching engine. The anonymous web search API already supports the useful part of that journey.

## Scope change

- Active channels are `REGISTERED_WEB`, `GUEST_WEB`, `BUYER_WEB`, and `ADMIN_PARTNER_WEB`.
- Dedicated `KIOSK` UI/runtime/deployment and new kiosk feature work are excluded from MVP/v1.x.
- Event entrance, badge, print, and booth QR codes link directly to guest web URLs.
- Anonymous guest search remains available without signup or profile creation.
- The shared deterministic matching/search engine remains channel-independent.

## Compatibility decision

- Existing `apps/kiosk`, kiosk API routes, database records, and `/kiosk-handoff` are retained as
  inactive compatibility assets in this change. They are not default build/release targets.
- CR-009 does not remove frozen OpenAPI paths or database structures. A later cleanup must publish a
  versioned deprecation/removal contract and retention plan before deleting them.
- Existing public `/api/v1/search` with channel `WEB` becomes the guest-web search integration.

## Safety

- No kiosk data is migrated into a user profile automatically.
- QR entry does not embed contact details or create a personal profile.
- Approved-catalog, active-event, Hard Filter, UNKNOWN, evidence, and score-version boundaries remain
  unchanged.

## Rollback

Restore the earlier `PROJECT_SCOPE.md` channel table and root kiosk build scripts. The retained kiosk
source/API allow rollback without reconstructing deleted assets.
