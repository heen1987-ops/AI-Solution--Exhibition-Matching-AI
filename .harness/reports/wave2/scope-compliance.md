# QA-003: Scope Compliance Report (Wave 2)

Scope: PROJECT_SCOPE.md §Explicit exclusions check against all net-new code from this wave
(`apps/kiosk/**`, `apps/admin/**`, `ai/**`, and the new BACKEND-006/008 router/service files).

## Verdict: PASS

## Method

Grepped (case-insensitive, Korean + English variants) for each excluded item in
PROJECT_SCOPE.md across the new code:

```
kafka, 실시간 재고 / real-time inventory, dedicated/vector DB, 장기 CRM / long-term CRM,
견적/계약서 / quotes/contracts, sample shipping, multi-armed bandit / 온라인 학습,
meeting-room auto-assignment / 회의실 자동 배정, indoor precision navigation / 정밀 위치추적,
congestion prediction / 혼잡도 예측
```

against:

```
apps/kiosk/**  apps/admin/**  ai/**
apps/api/app/api/v1/routers/{exhibition_public,search,kiosk}.py
apps/api/app/services/{catalog_search,exhibition_public,exhibition_public_repository,
  search_query_interpreter,search_sessions,kiosk}.py
apps/api/app/models/kiosk.py
apps/api/app/schemas/{search,kiosk,exhibition_public}.py
```

No matches found anywhere in that set.

## Kiosk-specific scope checks

- `apps/kiosk` has zero `<input>`/`<textarea>` elements anywhere (`grep -rn "<input\|<textarea"
  apps/kiosk --include="*.tsx"` returns nothing) — search entry goes through a custom
  `OnScreenKeyboard` component operating on in-memory state, not a native text field that could
  be repurposed to collect identity data.
- `apps/kiosk/lib/types.ts`, `storage.ts`, `api-client.ts` all carry explicit comments stating no
  name/phone/email/signup/password/long-lived-profile fields exist, and the actual type
  definitions (`KioskSession`, `StoredKioskState`, `SearchResult`, etc.) contain no such fields.
- `apps/api/app/models/kiosk.py` (`KioskSession`, `KioskQrHandoff`) has no identity/contact
  columns; `apps/api/app/schemas/kiosk.py` (Pydantic request/response models) likewise has none.
- No map/navigation code beyond static `map_x`/`map_y` booth coordinates + a static zone map
  response (`PublicMapResponse` / `get_event_map`) — no turn-by-turn or precision indoor
  positioning logic.
- No inventory/quantity-tracking fields introduced; `ProductAttribute`/`EventProduct` filtering
  is approval-status only, not stock levels.

## Admin-specific scope checks

- `apps/admin/app/exhibitors/new/page.tsx` collects `managerName` / `managerPhone` /
  `managerEmail` — this is the **exhibiting company's business contact info**, entered by an
  event operator/data reviewer as part of the company's B2B master record (same category of data
  already stored in `apps/api/app/models/exhibitor.py` pre-existing schema), not personal data
  collected from an anonymous kiosk visitor or from an admin user's own login credentials. This
  does not fall under the kiosk-specific "no personal data" rule (that rule targets the kiosk
  module and unregistered visitors) and is in scope for ADMIN's exhibitor-management mandate.
- No quotes/contracts/settlement UI, no shipping/logistics UI, no Kafka/queue references, no
  meeting-room auto-assignment logic found in `apps/admin/**`.

## Gap noted (scope of *this task*, not an exclusion violation)

- ADMIN-001's backlog acceptance criteria calls for "역할별 로그인 및 메뉴 분기" (role-based
  *login* and menu branching). What's implemented (`apps/admin/lib/auth-state.ts` +
  `components/SessionSwitcher.tsx`) is an explicit, clearly-labeled ("임시세션" badge) dev-only
  role switcher that sets an `X-Actor-User-Id` header — not a real login/MFA flow. The module's
  own docstring says this is intentional because "실제 관리자 로그인·MFA 화면은 요구하지
  않는다" for *this specific task instruction* and defers full MFA to ADMIN-001's proper scope.
  This is not a PROJECT_SCOPE.md exclusion violation (login/MFA is in-scope, just not yet built)
  and is not a privacy violation (no real credentials are faked), but it does mean ADMIN-001's
  formal acceptance criteria ("로그인 및 메뉴 분기") is only partially met — flagged here for the
  ADMIN track/gate reviewer, not blocking QA-003's scope-compliance verdict.

## Summary

| Check | Result |
|---|---|
| Excluded-feature string search across all new code | PASS (no matches) |
| Kiosk collects no personal data (fields, storage, DB, schemas) | PASS |
| Kiosk has no native input fields at all | PASS |
| Admin exhibitor-contact fields are legitimate B2B data, not personal-visitor data | PASS |
| ADMIN-001 real login/MFA still outstanding (documented TODO, not this task's scope) | NOTE (not a violation) |
