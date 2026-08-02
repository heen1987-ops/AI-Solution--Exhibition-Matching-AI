# CR-012 — Alimtalk-first informational notification delivery

Status: APPROVED
Requested: 2026-08-03
Approved by: explicit user direction that Kakao Alimtalk is the primary doorway to mobile My Event,
with SMS fallback and email as a secondary receipt-like channel

## Product boundary

The service product remains the responsive My Event web. Notification channels only announce an
approved business event and carry one opaque personal access link. They never contain a ranked
company list, internal score, detailed behavioral history, or contact-sharing data.

The MVP channel order is fixed:

1. `KAKAO_ALIMTALK`
2. `SMS` only when Alimtalk cannot be sent
3. `EMAIL` only when the preceding phone channels cannot be sent

Kakao Talk Message API is not an outbound service-notification provider. Alimtalk is supplied via
a Kakao official dealer and requires an approved informational template and a legally collected
phone number. The provider remains an adapter until an operator selects a dealer, channel, approved
template codes, callback authentication contract, and production credentials.

Official references reviewed on 2026-08-03:

- https://business.kakao.com/info/bizmessage/
- https://kakaobusiness.gitbook.io/main/ad/infotalk
- https://kakaobusiness.gitbook.io/main/ad/infotalk/audit
- https://developers.kakao.com/docs/ko/kakaotalk-message/faq

## Allowed informational triggers

- `REGISTRATION_COMPLETED`
- `RECOMMENDATION_READY`
- `EVENT_EVE_REMINDER`
- `MEETING_STATUS_CHANGED`
- `MEETING_IMMINENT`
- `POST_EVENT_SUMMARY`

MVP implementation begins with `RECOMMENDATION_READY`. A rank movement, one newly approved
exhibitor, saved-item change, search query, or ordinary web refresh is not a notification trigger.
Every trigger requires a stable dedupe key, and its cadence is independently enforced from matching.

## Message policy

- `message_class` is `INFORMATIONAL` only. Marketing or sponsored content is rejected.
- The initial text template contains event name, recipient name, factual recommendation count, and
  a short My Event invitation. Specific exhibitors, discounts, sponsor placement, or purchase
  inducement are absent.
- Alimtalk text is limited to 1,000 characters and at most five buttons. MVP uses one `WL` web-link
  button labelled `나의 추천 업체 확인`.
- Template variables are bounded before provider dispatch. Provider template approval remains a
  release prerequisite even if local validation succeeds.

## Persistence and privacy

`integration.notification_delivery` stores tenant/event/user identifiers, notification type,
template code, snapshot/link references, safe status/timestamps, dedupe key, and an AEAD-encrypted
access URL. It does not store raw phone, email, name, or token columns.

`integration.notification_attempt` is append-only per channel attempt and stores only channel,
provider code, safe provider message ID, safe failure code, and timestamps. Provider response bodies
and contact values are forbidden.

`integration.outbox_event` is inserted in the same transaction as the notification delivery. Its
JSON payload carries only the notification delivery ID. Workers claim rows with `SKIP LOCKED` and
retry from the Outbox; matching calculation never calls a provider.

At dispatch time the worker reads the encrypted contact from `identity.user_identity` and decrypts
it only in memory. A successful personal-link exchange records `clicked_at` through the stored link
reference without exposing a click-tracking token.

## Deferred provider-specific work

- official dealer selection and API schema
- Kakao channel/business verification and approved template codes
- provider webhook signature, replay, status-code, and retry contract
- SMS and email provider selection
- production secret/KMS provisioning
- legal/operations approval of every template and fallback policy

No fake production provider, credential, or callback endpoint is introduced before those decisions.

## Scope compatibility

This change extends the approved CR-011 delivery boundary and stays within the CR-009 web-first
scope. It does not add a native app, dedicated kiosk, CRM, marketing campaign automation, or a new
matching policy.
