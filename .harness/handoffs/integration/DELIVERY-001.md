# DELIVERY-001 Handoff — My Event Snapshot Delivery

Date: 2026-08-03
Status: DONE
Decision: DECISION-021
Contract: CR-011

## Delivered boundary

- `POST /api/v1/recommendations` remains the explicit calculation command.
- `GET /api/v1/home` selects the newest owned `ACTIVE` persisted snapshot and returns its versioned
  items. It performs no implicit matching, LLM call, or provider dispatch.
- No snapshot returns `404 RECOMMENDATION_NOT_READY`; expired snapshots are returned with
  `stale=true`; invalidated snapshots are excluded.
- `/home` and `/e/{eventSlug}/my` share `MyEventDashboard`, so an exchanged personal link opens the
  actual recommendation, saved, meeting, schedule, search, and map surface rather than a hidden
  intermediate menu.
- My Event renders up to ten persisted cards. `RecommendationCard` keeps numeric scores hidden,
  shows grounded reasons, supports save and eligible detail/meeting actions, and records explicit
  “관심 없음” as the existing `RECOMMENDATION_DISMISSED` learning event.

## Scope retained

Kakao, SMS, and email are entry-link adapters only and are not implemented in this unit. Dedicated
kiosk work remains excluded by CR-009. Matching policies, score formulas, Hard Filters, snapshot
persistence models, and personal-link authentication semantics are unchanged.

## Verification

- Common matching engine: 72 passed.
- API: 248 passed, 2 PostgreSQL environment-gated skips.
- User web: 5 passed; typecheck and lint passed; 21-route production build passed on clean NTFS.
- Frozen OpenAPI: 75 paths parsed and every local `$ref` resolved.
- Touched Python Ruff and `git diff --check`: passed.

## Next integration point

Batch generation and approved notification adapters may schedule or announce snapshot availability,
but must call the calculation boundary explicitly and must never add generation side effects to
`GET /home`.
