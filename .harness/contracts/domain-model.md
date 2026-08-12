# Domain Model (formalized from existing implementation)

> Task: CONTRACT-002. Source of truth remains [docs/db-erd-table-spec.md](../../docs/db-erd-table-spec.md)
> and `apps/api/app/models/**` (28 mapped domain modules plus `common.py`, 32 Alembic migrations,
> single head `0032_favorite`, 136 tables, SQL-compile verified). This file is a
> navigable summary, not a duplicate — do not let it drift; regenerate when model files change
> materially.
>
> **2026-08-11**: rewritten at the close of the WAVE2C/2D/2E -> main unification merge. The
> pre-merge snapshot (16 modules, 17 migrations, 94 tables) is preserved in git history; this
> revision adds the ten modules ported from the WAVE2C/2D/2E worktree. See
> `.harness/decisions.md` DECISION-023..028 for the conflict-resolution record behind the additions.
>
> **2026-08-13 (CONTRACT-005)**: adds `favorite.py` / migration `0032_favorite` —
> `interaction.favorite`, a persistent saved-items table. Model + migration + contract docs only;
> BACKEND-009 owns the CRUD API. See
> `.harness/handoffs/contracts/change-request-005-favorites.md`.

## Module → schema → responsibility

| Model file | Postgres schema(s) | Responsibility |
|---|---|---|
| `core.py` | `core`, `exhibition` | Tenant, Event, EventDay, EventZone |
| `identity.py` | `profile`, `identity` | UserAccount, UserIdentity (encrypted PII + HMAC), AuthenticationMethod, Role, UserRole, GuestSession |
| `auth.py` | `identity` | Server-managed session/credential store behind CR-006: browser sessions, WebAuthn/TOTP/recovery MFA, personal access links. The only authentication substrate in the merged repo — WAVE2C/2D/2E's ported routers were rewired onto it (`app/core/router_auth.py`), not merged as a parallel system. |
| `consent.py` | `profile`, `privacy`, `audit` | ConsentPolicy, UserConsent, PrivacyRequest, RetentionPolicy, DeletionJob, AuditLog |
| `ontology_refs.py` | `ontology` (referenced) | Shared FK helpers into the ontology package's `concept`/`concept_revision`/`taxonomy_version` tables |
| `profile.py` | `profile` | UserProfile, ProfileAttribute, InferredPreference, ProfileVersion, ContextProfile, VisitSession, BuyerNeed |
| `exhibitor.py` | `exhibition` | Exhibitor, ExhibitorBusinessType, ExhibitorParticipation, ParticipationCategory, ExhibitorStaff, StaffTopic, Product, EventProduct, ProductAttribute, ProductImage, TradeCondition, TradeConditionTerm, Booth, BoothStatusHistory, BoothQr, Program, plus §27 supply-profile extension tables (ExhibitorProfile, ProductProfile, SupplyCapability, ExhibitorBuyerPreference, SupplyProfileAttribute) |
| `matching.py` | `exhibition`, `interaction`, `matching` | Recommendable (polymorphic target registry), InteractionEvent, RecommendationSession (= MatchRun), MatchResult, MatchReason, RecommendationDelivery |
| `meeting.py` | `interaction` | AvailabilitySlot, MeetingRequest (+ WAVE2C `product_id`/`order_scale_code`), MeetingSlotRequest, MeetingContactShare (+ WAVE2C `exhibitor_enabled_at`/`exhibitor_enabled_by_staff_id` — the third contact-disclosure gate, see DECISION-026), MeetingStatusHistory, Lead (MeetingOutcome), FollowUp (FollowUpAction) |
| `integration.py` | `integration` | SourceSystem, ExternalReference, SyncJob, SyncRowError, IdempotencyRecord (migration 0031, added during this merge — declared since the pre-merge codebase but never had a creating migration on either tree); NotificationDelivery/NotificationAttempt/OutboxEvent (outbound Alimtalk->SMS->EMAIL provider fan-out, distinct from `notification.py`'s inbox — see DECISION-024) |
| `conversation.py` | `conversation` | Conversational profiling — messages, entity extraction, decisions (stage 19 lineage) |
| `kiosk.py` | `kiosk` | 익명 단기 세션 수명주기와 서명 QR 인계 감사 원장(이름·전화·이메일 등 PII 컬럼 없음) |
| `filtering.py`, `policy.py`, `ai.py`, `cold_start.py`, `learning.py` | `matching`/`ai`/various | Hard-filter evaluation records, `ai.object_embedding` (real pgvector VECTOR(512), see below), policy/AI registries, cold-start persistence, behavior-learning evidence |
| `buyer_profile.py` *(WAVE2C)* | `profile` | Verified-buyer trade profile fields extending `profile.buyer_need`, not a duplicate table |
| `buyer_match.py` *(WAVE2C)* | `matching` | Deterministic hard-filter/scoring B2B match session + result rows behind `POST /buyer/matches` and `POST /buyer/compare`; coexists with `matching.py`'s general RecommendationSession by design (DECISION-023) |
| `exhibitor_preference.py` *(WAVE2C)* | `exhibition` | Exhibitor-declared trade cooperation types and availability; public read is scoped to the row's own `APPROVED` `master_approval_status` (fixed during this merge) |
| `document.py` *(WAVE2D)* | `document` | SourceDocument, DocumentVersion, uploaded through `services/document/storage.py`'s `ObjectStorageAdapter` (`LocalFilesystemStorageAdapter` shipped) |
| `extraction.py` *(WAVE2D)* | `document` | ExtractedAttribute, ContentReviewRequest, PublishedContentVersion — DB-enforced exhibitor-confirm -> operator-approve gate before any AI-extracted attribute reaches the search/embedding index |
| `indexing.py` *(WAVE2D)* | `indexing` | PUBLIC/VERIFIED_BUYER search-tier `SearchDocument` — a grain-level exposure-tier layer complementary to (not a duplicate of) `ai.object_embedding`'s vector-recall layer; see DECISION-025 |
| `interaction_event.py` *(WAVE2E)* | `interaction` | `EventIngestionFailure` (migration 0030) backing main's authenticated `POST /interactions/batch`; the worktree's own anonymous `/events/interaction` router was not ported (folded in, see DECISION-027) |
| `favorite.py` *(CONTRACT-005)* | `interaction` | `Favorite` (migration 0032) — persistent saved-items ("watchlist") table, db-erd §16.1. Owner is exactly one of `user_id`/`guest_session_id` (`CHECK num_nonnulls(...) = 1`); target is the standard three-column composite FK into `exhibition.recommendable`; duplicate prevention uses two partial UNIQUE indexes (one per owner type, scoped `WHERE deleted_at IS NULL`) so a soft-deleted favorite never blocks a later re-favorite of the same pair. **Distinct from** `matching.py::InteractionEvent`'s `FAVORITE_ADD`/`FAVORITE_REMOVE` `event_type` values, which are an unrelated append-only behavior-event log (migration 0008) — do not conflate the two. Model + migration only; the CRUD API (`GET/POST/DELETE /me/favorites`) is BACKEND-009's separate downstream task. See `.harness/handoffs/contracts/change-request-005-favorites.md`. |
| `analytics.py` *(WAVE2E)* | `analytics` | Rollup tables with a DB-level `CHECK '(suppressed=false) OR (event_count IS NULL AND distinct_actor_count IS NULL)'` making a suppressed (k<5) row physically incapable of carrying counts |
| `notification.py` *(WAVE2E)* | `notification` | In-app inbox: Notification, NotificationPreference, NotificationTemplate, NotificationRule, `NotificationChannelDelivery`/`NotificationChannelDeliveryAttempt` (renamed from the worktree's own `NotificationDelivery`/`NotificationDeliveryAttempt` to resolve a `configure_mappers()` class-name collision with `integration.py` — table names unchanged, see DECISION-024) |
| `event_message.py` *(WAVE2E)* | `event_message` | Operator-authored event-wide broadcasts; approve/schedule/publish are irreversible and require `require_roles('EVENT_ADMIN', fresh_mfa=True)` |

## Cross-cutting conventions (verified in code, not just docs)

- **Ontology reference pattern**: business tables never store a bare category code. They store a
  composite `(taxonomy_version_id, concept_id)` foreign key into `ontology.concept_revision`
  (see `docs/db-erd-table-spec.md` §11 and every domain model file). A `attribute_code` column may
  exist *denormalized* for readability, but it is tied back to `concept_id` via a DB-level FK to
  `ontology.concept(concept_id, concept_code)` — see `profile.py`'s `ProfileAttribute`.
- **Tenant/event isolation**: every business table carries `tenant_id` + `event_id`.
- **Polymorphic references**: use the `exhibition.recommendable` registry table (booth / event_product /
  participation / program), never a bare `object_type` + `object_id` pair without a FK.
- **PII separation**: `identity.user_identity` holds `name_enc` / `phone_enc` / `phone_hmac` /
  `email_enc` / `email_hmac`; no other table stores raw contact info.
- **Versioning**: published/immutable artifacts (profile snapshots, match runs, pricing, ontology
  concepts) are versioned, never mutated in place.
- **Search embeddings**: `ai.object_embedding` is tenant/event-bound to `exhibition.recommendable`,
  stores SHA-256 content lineage and exactly one active pointer per content/language, and only an
  `EMBEDDING` model with the configured 512 dimensions may become active. Source/membership triggers
  fail closed by deactivating a participation's active catalog vectors whenever embedded catalog,
  approval, or recommendable fields change. Triggers and final activation share a short global
  catalog advisory lock, and activation rechecks the latest source snapshot inside that lock.

## Verified cross-cutting checks

- RISK-005 (`.harness/risks.md`) is resolved: `matching.py` targets
  `ontology.taxonomy_version`, and `test_profile_foundation.py` guards against the former invalid
  `exhibition.taxonomy_version` reference.

## Recurring verification

- Alembic head: 2026-08-11 WAVE2C/2D/2E -> main 통합 병합 후 검증 기준 단일 선형 체인
  `0031_integration_source_sync` (31개 마이그레이션, 135 ORM 테이블). 병합 계획은 마지막
  리비전을 `0030_event_ingestion_failure`로 예상했으나, Foundation 단계가 병합 중 발견한
  추가 드리프트(`app/models/integration.py`의 SourceSystem/ExternalReference/SyncJob/
  SyncRowError/IdempotencyRecord 5개 테이블에 대해 어느 쪽 코드베이스에도 생성 마이그레이션이
  없었음)를 `0031`로 반영했다 — `tests/test_alembic_orm_parity.py`가 이후 이 부류의 드리프트를
  차단한다. 동시 작업 후에는 `alembic heads`로 재검증한다(단일 head여야 함).
- 2026-08-13 CONTRACT-005: `0032_favorite`로 단일 head 갱신(32개 마이그레이션, 136 ORM
  테이블). `interaction.favorite` 하나만 추가하는 순수 가법적 변경 — 기존 테이블·제약은
  변경하지 않았다. `python -m pytest apps/api/tests -q` 1141 passed(=1126+15)/3 skipped/1
  xfailed, `alembic heads` 단일 `0032_favorite`, `alembic upgrade head --sql` 오프라인 컴파일
  통과로 검증했다.
