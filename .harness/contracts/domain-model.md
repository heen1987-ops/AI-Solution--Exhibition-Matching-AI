# Domain Model (formalized from existing implementation)

> Task: CONTRACT-002. Source of truth remains [docs/db-erd-table-spec.md](../../docs/db-erd-table-spec.md)
> and `apps/api/app/models/**` (16 mapped domain modules plus `common.py`, 17 Alembic migrations,
> 94 tables, SQL-compile verified). This file is a navigable summary, not a duplicate — do not let it drift; regenerate
> when model files change materially.

## Module → schema → responsibility

| Model file | Postgres schema(s) | Responsibility |
|---|---|---|
| `core.py` | `core`, `exhibition` | Tenant, Event, EventDay, EventZone |
| `identity.py` | `profile`, `identity` | UserAccount, UserIdentity (encrypted PII + HMAC), AuthenticationMethod, Role, UserRole, GuestSession |
| `consent.py` | `profile`, `privacy`, `audit` | ConsentPolicy, UserConsent, PrivacyRequest, RetentionPolicy, DeletionJob, AuditLog |
| `ontology_refs.py` | `ontology` (referenced) | Shared FK helpers into the ontology package's `concept`/`concept_revision`/`taxonomy_version` tables |
| `profile.py` | `profile` | UserProfile, ProfileAttribute, InferredPreference, ProfileVersion, ContextProfile, VisitSession, BuyerNeed |
| `exhibitor.py` | `exhibition` | Exhibitor, ExhibitorBusinessType, ExhibitorParticipation, ParticipationCategory, ExhibitorStaff, StaffTopic, Product, EventProduct, ProductAttribute, ProductImage, TradeCondition, TradeConditionTerm, Booth, BoothStatusHistory, BoothQr, Program, plus §27 supply-profile extension tables (ExhibitorProfile, ProductProfile, SupplyCapability, ExhibitorBuyerPreference, SupplyProfileAttribute) |
| `matching.py` | `exhibition`, `interaction`, `matching` | Recommendable (polymorphic target registry), InteractionEvent, RecommendationSession (= MatchRun), MatchResult, MatchReason, RecommendationDelivery |
| `meeting.py` | `interaction` | AvailabilitySlot, MeetingRequest, MeetingSlotRequest, MeetingContactShare, MeetingStatusHistory, Lead (MeetingOutcome), FollowUp (FollowUpAction) |
| `integration.py` | `integration` | SourceSystem, ExternalReference, SyncJob, SyncRowError, IdempotencyRecord |
| `conversation.py` | `conversation` | Conversational profiling — messages, entity extraction, decisions (stage 19 lineage) |
| `kiosk.py` | `kiosk` | 익명 단기 세션 수명주기와 서명 QR 인계 감사 원장(이름·전화·이메일 등 PII 컬럼 없음) |
| `filtering.py`, `policy.py`, `ai.py`, `cold_start.py`, `learning.py` | `matching`/`ai`/various | Hard-filter evaluation records, versioned 512-dimension public-catalog embeddings, policy/AI registries, cold-start persistence, behavior-learning evidence |

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

- Alembic head: 2026-08-02 검증 기준 단일 선형 체인 `0017_object_embedding`.
  동시 작업 후에는 `alembic heads`로 재검증한다.
