# CR-001 Handoff - WEB_ONLY Scope Change

Date: 2026-08-02
Requester: FOUNDATION/BACKEND orchestration
Target Track: CONTRACTS
Status: DONE

## Summary

The user provided a new "web 중심 재설계 기준서" that declares the MVP should be
mobile-web only, with no dedicated app installation and no dedicated kiosk module.
The request has now been applied to the canonical harness baseline without
destructive deletion of existing kiosk artifacts.

## Source

`/Users/ppp/.codex/attachments/d6e8f232-34fa-4609-84ba-4cd4e7fd576b/pasted-text.txt`

## Requested Target State

- `channel_strategy`: `WEB_ONLY`
- `kiosk_module_status`: `EXCLUDED`
- User web modes: `REGISTERED_WEB`, `GUEST_WEB`, `BUYER_WEB`
- Admin/partner mode: `ADMIN_PARTNER_WEB`
- Entry methods: event website, QR, short URL, email link, registration link

## Required Impact Analysis

- Scope docs: `AGENTS.md`, `PROJECT_SCOPE.md`, `docs/redesign-v2/**`.
- Contracts: `openapi.yaml`, `domain-model.md`, `event-catalog.yaml`,
  `error-codes.yaml`, `ontology.yaml`.
- Backend: `/api/v1/kiosk/*` implemented in `BAC-005` must be deprecated or
  replaced after contract sync, not immediately deleted.
- DB: `KioskDevice`/`KioskConfig` migrations exist. Do not create destructive
  cleanup migrations before checking data and deployment state.
- Frontend: `apps/kiosk` scaffold exists and QAS-004 smoke includes kiosk. Replace
  with mobile guest web smoke only after contract approval.
- AI_SEARCH: `AIS-GROUP-001` still includes kiosk scoring. Redefine as guest web
  search quality and multilingual/mobile search before decomposition.

## Guardrails

- Do not delete existing migrations or tables in place.
- Do not modify frozen static contracts outside CONTRACTS ownership.
- Do not keep generating new kiosk tasks while CR-001 is unresolved.
- Preserve privacy improvements: guest web must not store name, phone, email,
  address, browser fingerprint, or long-term personalization without explicit login.

## Current Harness Changes Already Made

- `.harness/state.json` now records `channel_strategy = WEB_ONLY` and
  `kiosk_module_status = EXCLUDED_DEPRECATED_PENDING_CLEANUP`.
- `next_recommended_tasks` now points to `BAC-010`.
- `AIS-GROUP-001` is redefined around guest web search quality.
- `KSK-GROUP-001` is marked `SUPERSEDED`.
- `G2_FEATURE_COMPLETE` is back to `IN_PROGRESS`.

## Changed Files

- `AGENTS.md`
- `PROJECT_SCOPE.md`
- `.harness/decisions.md`
- `.harness/contracts/openapi.yaml`
- `.harness/contracts/domain-model.md`
- `.harness/contracts/event-catalog.yaml`
- `.harness/contracts/error-codes.yaml`
- `.harness/contracts/ontology.yaml`
- `.harness/backlog.yaml`
- `.harness/state.json`
- `.harness/quality-gates.yaml`
- `.harness/change-requests/CR-001-web-only-scope-change.md`
- `.harness/handoffs/contracts/CR-001-web-only-scope-change.md`

## Follow-ups

- `BAC-010` should be executed next to align backend routes with the new
  `/guest/sessions` contract.
- `QAS-007` should replace kiosk smoke/PII checks with guest web mobile checks.
- `CTR-011` should plan cleanup for deprecated kiosk migrations/models/API/app
  without destructive changes before approval.
