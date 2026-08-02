# NOTIFY-001 Handoff — Alimtalk-first informational delivery foundation

Date: 2026-08-03
Status: DONE
Decision: DECISION-022
Contract: CR-012

## Delivered

- `enqueue_recommendation_ready` creates a single-use personal link, notification delivery, and
  privacy-minimized Outbox event in the caller transaction.
- Stable dedupe is scoped to tenant, event, user, and recommendation Snapshot. Rank-only changes
  and ordinary catalog/web interactions are not notification triggers.
- The logical `RECOMMENDATION_READY_V1` message is informational, bounded to the official Alimtalk
  text/button limits, contains no named recommendation or score, and links to mobile My Event.
- Dispatch order is `KAKAO_ALIMTALK`, then `SMS`, then `EMAIL`, stopping after the first accepted
  send. Provider implementations are dependency-injected and none is enabled in production.
- Delivery stores an encrypted access URL and pseudonymous IDs only. Channel attempts store safe
  provider message IDs/failure codes only. Identity contacts are decrypted in worker memory.
- Outbox workers use `FOR UPDATE SKIP LOCKED`, expiring leases, due retries, and append-only attempt
  sequence numbers. Link exchange sets the first `clicked_at` using `personal_access_link_id`.

## Verification

- Notification delivery tests: 9 passed.
- Full API: 257 passed, 2 PostgreSQL environment-gated skips.
- Common matching engine: 72 passed.
- Alembic: `0019_notification_outbox` is the single head; full offline upgrade DDL passed.
- Touched Ruff, compileall, pip check, harness parse, and diff check passed.

## Required before live sending

Operations must select a Kakao official dealer, create/verify the Kakao Business channel, obtain
approved information-template codes, and freeze that dealer's request, idempotency, callback
signature, status, rate-limit, and retry contract. SMS and email providers, production KMS/secrets,
and template/legal approval are also required. The worker must dispatch or safely reissue links
within the 15-minute personal-link lifetime. Until these are supplied, external sending must remain
disabled; tests may inject adapters, production code must not use a fake provider.
