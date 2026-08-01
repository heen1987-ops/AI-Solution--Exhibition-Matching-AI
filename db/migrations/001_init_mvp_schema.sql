-- MVP schema for the Exhibition Matching AI service.
-- Scope: section 39 "MVP 필수" table list from docs/design/06-db-erd-schema-design.md,
-- plus profile.consent_policy (referenced by user_consent as a required FK target).
--
-- Internal PKs use UUID. Native pgcrypto gen_random_uuid() generates UUIDv4;
-- if the application layer needs UUIDv7 ordering, generate it there and pass it in.

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS vector;

CREATE SCHEMA IF NOT EXISTS identity;
CREATE SCHEMA IF NOT EXISTS profile;
CREATE SCHEMA IF NOT EXISTS exhibition;
CREATE SCHEMA IF NOT EXISTS matching;
CREATE SCHEMA IF NOT EXISTS interaction;
CREATE SCHEMA IF NOT EXISTS ai;
CREATE SCHEMA IF NOT EXISTS audit;

-- =========================================================================
-- profile.user_account (§6.1) — created first, everything else hangs off it
-- =========================================================================
CREATE TABLE profile.user_account (
  user_id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  account_type        VARCHAR NOT NULL
                       CHECK (account_type IN ('GUEST','VERIFIED','BUYER','EXHIBITOR','OPERATOR','ADMIN')),
  account_status      VARCHAR NOT NULL DEFAULT 'ACTIVE'
                       CHECK (account_status IN ('ACTIVE','SUSPENDED','WITHDRAWN')),
  default_language    VARCHAR(10),
  timezone            VARCHAR(50),
  last_login_at       TIMESTAMPTZ,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at          TIMESTAMPTZ
);

-- =========================================================================
-- identity.user_identity (§5.1) — direct PII, encrypted at the application layer.
-- Operational services must not query this table directly.
-- =========================================================================
CREATE TABLE identity.user_identity (
  identity_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id             UUID NOT NULL UNIQUE REFERENCES profile.user_account(user_id),
  name_enc            BYTEA,
  phone_enc           BYTEA,
  phone_hash          CHAR(64),
  email_enc           BYTEA,
  email_hash          CHAR(64),
  birth_year_enc      BYTEA,
  age_verified        BOOLEAN NOT NULL DEFAULT FALSE,
  phone_verified_at   TIMESTAMPTZ,
  email_verified_at   TIMESTAMPTZ,
  retention_until     DATE,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at          TIMESTAMPTZ
);

CREATE UNIQUE INDEX idx_user_identity_phone_hash
  ON identity.user_identity(phone_hash) WHERE deleted_at IS NULL;
CREATE INDEX idx_user_identity_retention
  ON identity.user_identity(retention_until);

-- =========================================================================
-- exhibition.event / event_zone (§11)
-- =========================================================================
CREATE TABLE exhibition.event (
  event_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  event_code    VARCHAR NOT NULL UNIQUE,
  event_name    VARCHAR NOT NULL,
  venue_name    VARCHAR,
  timezone      VARCHAR,
  start_date    DATE NOT NULL,
  end_date      DATE NOT NULL,
  event_status  VARCHAR NOT NULL DEFAULT 'PREPARING'
                CHECK (event_status IN ('PREPARING','OPEN','CLOSED')),
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE exhibition.event_zone (
  zone_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  event_id        UUID NOT NULL REFERENCES exhibition.event(event_id),
  zone_code       VARCHAR NOT NULL,
  zone_name       VARCHAR NOT NULL,
  floor           VARCHAR,
  map_x           NUMERIC,
  map_y           NUMERIC,
  parent_zone_id  UUID REFERENCES exhibition.event_zone(zone_id),
  zone_type       VARCHAR CHECK (zone_type IN ('ENTRANCE','BOOTH_AREA','STAGE','REST')),
  UNIQUE (event_id, zone_code)
);

-- =========================================================================
-- profile.guest_session / visit_session (§7)
-- =========================================================================
CREATE TABLE profile.guest_session (
  guest_session_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_token_hash   CHAR(64) NOT NULL,
  event_id             UUID NOT NULL REFERENCES exhibition.event(event_id),
  entry_channel        VARCHAR CHECK (entry_channel IN ('QR','WEB','KIOSK')),
  entry_code           VARCHAR,
  device_type          VARCHAR CHECK (device_type IN ('MOBILE_WEB','DESKTOP','KIOSK')),
  language             VARCHAR,
  expires_at           TIMESTAMPTZ NOT NULL,
  converted_user_id    UUID REFERENCES profile.user_account(user_id),
  created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_guest_session_token ON profile.guest_session(session_token_hash);

-- =========================================================================
-- exhibition.exhibitor / exhibitor_participation (§12)
-- =========================================================================
CREATE TABLE exhibition.exhibitor (
  exhibitor_id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  company_name                VARCHAR NOT NULL,
  business_registration_hash  CHAR(64),
  company_summary             TEXT,
  business_type               VARCHAR,
  region_code                 VARCHAR,
  website_url                 TEXT,
  approval_status             VARCHAR NOT NULL DEFAULT 'DRAFT'
                               CHECK (approval_status IN ('DRAFT','SUBMITTED','APPROVED','REJECTED')),
  data_completeness_score     NUMERIC(5,2),
  profile_version             INTEGER NOT NULL DEFAULT 1,
  created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE exhibition.exhibitor_participation (
  participation_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  event_id               UUID NOT NULL REFERENCES exhibition.event(event_id),
  exhibitor_id           UUID NOT NULL REFERENCES exhibition.exhibitor(exhibitor_id),
  participation_status   VARCHAR NOT NULL DEFAULT 'APPLIED'
                          CHECK (participation_status IN ('APPLIED','APPROVED','CANCELLED')),
  exhibition_categories  JSONB,
  promotion_summary      TEXT,
  consultation_enabled   BOOLEAN NOT NULL DEFAULT FALSE,
  approved_at            TIMESTAMPTZ,
  UNIQUE (event_id, exhibitor_id)
);

-- =========================================================================
-- exhibition.product / product_attribute (§13)
-- =========================================================================
CREATE TABLE exhibition.product (
  product_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  exhibitor_id           UUID NOT NULL REFERENCES exhibition.exhibitor(exhibitor_id),
  product_name           VARCHAR NOT NULL,
  category_code          VARCHAR NOT NULL,
  product_summary        TEXT,
  alcohol_percentage     NUMERIC(5,2),
  retail_price           INTEGER,
  event_price            INTEGER,
  currency               CHAR(3) NOT NULL DEFAULT 'KRW',
  main_ingredients       JSONB,
  production_method      TEXT,
  tasting_available      BOOLEAN NOT NULL DEFAULT FALSE,
  purchase_available     BOOLEAN NOT NULL DEFAULT FALSE,
  inventory_status       VARCHAR NOT NULL DEFAULT 'AVAILABLE'
                         CHECK (inventory_status IN ('AVAILABLE','LOW','SOLD_OUT')),
  approval_status        VARCHAR NOT NULL DEFAULT 'DRAFT'
                         CHECK (approval_status IN ('DRAFT','SUBMITTED','APPROVED','REJECTED')),
  created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_product_category
  ON exhibition.product(category_code, approval_status);
CREATE INDEX idx_product_price
  ON exhibition.product(retail_price) WHERE approval_status = 'APPROVED';

CREATE TABLE exhibition.product_attribute (
  product_attribute_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  product_id            UUID NOT NULL REFERENCES exhibition.product(product_id),
  attribute_group       VARCHAR NOT NULL
                        CHECK (attribute_group IN ('TASTE','AROMA','USE','CERTIFICATION')),
  attribute_code        VARCHAR NOT NULL,
  attribute_value       NUMERIC,
  source                VARCHAR CHECK (source IN ('EXHIBITOR','AI','OPERATOR')),
  confidence            NUMERIC(4,3),
  approved              BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX idx_product_attributes
  ON exhibition.product_attribute(attribute_group, attribute_code);

-- =========================================================================
-- exhibition.trade_condition (§14.1)
-- =========================================================================
CREATE TABLE exhibition.trade_condition (
  trade_condition_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  exhibitor_id               UUID NOT NULL REFERENCES exhibition.exhibitor(exhibitor_id),
  product_id                 UUID REFERENCES exhibition.product(product_id),
  min_order_quantity          INTEGER,
  max_order_quantity          INTEGER,
  monthly_capacity            INTEGER,
  wholesale_price_min          INTEGER,
  wholesale_price_max          INTEGER,
  oem_available                BOOLEAN,
  private_label_available      BOOLEAN,
  exclusive_distribution       BOOLEAN,
  export_available             BOOLEAN,
  lead_time_days               INTEGER,
  valid_from                   DATE,
  valid_until                  DATE,
  approval_status              VARCHAR NOT NULL DEFAULT 'DRAFT'
                               CHECK (approval_status IN ('DRAFT','SUBMITTED','APPROVED','REJECTED'))
);

CREATE INDEX idx_trade_moq
  ON exhibition.trade_condition(min_order_quantity, monthly_capacity);

-- =========================================================================
-- exhibition.booth (§15.1)
-- =========================================================================
CREATE TABLE exhibition.booth (
  booth_id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  event_id                 UUID NOT NULL REFERENCES exhibition.event(event_id),
  participation_id         UUID NOT NULL REFERENCES exhibition.exhibitor_participation(participation_id),
  zone_id                  UUID REFERENCES exhibition.event_zone(zone_id),
  booth_number             VARCHAR NOT NULL,
  map_x                    NUMERIC,
  map_y                    NUMERIC,
  operating_status         VARCHAR NOT NULL DEFAULT 'OPEN'
                           CHECK (operating_status IN ('OPEN','PAUSED','CLOSED')),
  congestion_level         VARCHAR CHECK (congestion_level IN ('LOW','MEDIUM','HIGH')),
  estimated_wait_minutes   INTEGER,
  tasting_status           VARCHAR CHECK (tasting_status IN ('AVAILABLE','PAUSED','ENDED')),
  sales_status             VARCHAR CHECK (sales_status IN ('AVAILABLE','LIMITED','ENDED')),
  updated_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (event_id, booth_number)
);

CREATE INDEX idx_booth_event_status ON exhibition.booth(event_id, operating_status);
CREATE INDEX idx_booth_zone_congestion ON exhibition.booth(zone_id, congestion_level);

-- =========================================================================
-- profile.visit_session (§7.2) — depends on event/booth zone + user/guest
-- =========================================================================
CREATE TABLE profile.visit_session (
  visit_session_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  event_id             UUID NOT NULL REFERENCES exhibition.event(event_id),
  user_id              UUID REFERENCES profile.user_account(user_id),
  guest_session_id     UUID REFERENCES profile.guest_session(guest_session_id),
  profile_id           UUID, -- FK added after profile.user_profile is created
  visit_date           DATE NOT NULL,
  entry_at             TIMESTAMPTZ,
  exit_at              TIMESTAMPTZ,
  available_minutes    INTEGER CHECK (available_minutes > 0),
  remaining_minutes    INTEGER,
  current_zone_id      UUID REFERENCES exhibition.event_zone(zone_id),
  route_preference     VARCHAR,
  session_status       VARCHAR NOT NULL DEFAULT 'PLANNED'
                        CHECK (session_status IN ('PLANNED','ACTIVE','COMPLETED','CANCELLED')),
  created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (user_id IS NOT NULL OR guest_session_id IS NOT NULL),
  CHECK (exit_at IS NULL OR entry_at IS NULL OR exit_at >= entry_at)
);

-- =========================================================================
-- profile.consent_policy / user_consent (§8)
-- consent_policy is not itself in the MVP list but user_consent requires it.
-- =========================================================================
CREATE TABLE profile.consent_policy (
  consent_policy_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  consent_type       VARCHAR NOT NULL
                     CHECK (consent_type IN (
                       'AGE_CONFIRMATION','PERSONALIZED_RECOMMENDATION','BEHAVIOR_DATA',
                       'CONTACT_SHARING','MARKETING','THIRD_PARTY_PROVISION'
                     )),
  version            VARCHAR NOT NULL,
  title              VARCHAR NOT NULL,
  body               TEXT NOT NULL,
  required           BOOLEAN NOT NULL DEFAULT FALSE,
  effective_from     TIMESTAMPTZ NOT NULL,
  effective_until    TIMESTAMPTZ,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (consent_type, version)
);

CREATE TABLE profile.user_consent (
  consent_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id              UUID REFERENCES profile.user_account(user_id),
  guest_session_id     UUID REFERENCES profile.guest_session(guest_session_id),
  consent_policy_id    UUID NOT NULL REFERENCES profile.consent_policy(consent_policy_id),
  agreed               BOOLEAN NOT NULL,
  agreed_at            TIMESTAMPTZ,
  withdrawn_at         TIMESTAMPTZ,
  source_channel       VARCHAR CHECK (source_channel IN ('WEB','QR','KIOSK')),
  ip_hash              CHAR(64),
  created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (user_id IS NOT NULL OR guest_session_id IS NOT NULL)
);

-- =========================================================================
-- profile.user_profile and related (§9)
-- =========================================================================
CREATE TABLE profile.user_profile (
  profile_id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id                UUID NOT NULL REFERENCES profile.user_account(user_id),
  event_id               UUID NOT NULL REFERENCES exhibition.event(event_id),
  user_type              VARCHAR NOT NULL CHECK (user_type IN ('GENERAL_VISITOR','BUYER')),
  profile_status         VARCHAR NOT NULL DEFAULT 'DRAFT'
                         CHECK (profile_status IN ('DRAFT','COMPLETE','INACTIVE')),
  primary_goal_code      VARCHAR,
  profile_completeness   NUMERIC(5,2) NOT NULL DEFAULT 0,
  current_version        INTEGER NOT NULL DEFAULT 1,
  created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at             TIMESTAMPTZ
);

CREATE UNIQUE INDEX idx_user_profile_unique
  ON profile.user_profile(user_id, event_id, user_type) WHERE deleted_at IS NULL;
CREATE INDEX idx_profile_user_event ON profile.user_profile(user_id, event_id);
CREATE INDEX idx_profile_user_type ON profile.user_profile(event_id, user_type, profile_status);

ALTER TABLE profile.visit_session
  ADD CONSTRAINT fk_visit_session_profile
  FOREIGN KEY (profile_id) REFERENCES profile.user_profile(profile_id);

CREATE TABLE profile.profile_goal (
  profile_goal_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  profile_id        UUID NOT NULL REFERENCES profile.user_profile(profile_id),
  goal_code         VARCHAR NOT NULL,
  priority          SMALLINT NOT NULL,
  source            VARCHAR NOT NULL CHECK (source IN ('USER_SELECTED','AI_EXTRACTED')),
  confidence        NUMERIC(4,3) NOT NULL DEFAULT 1.0,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (profile_id, priority)
);

CREATE TABLE profile.consumer_preference (
  profile_id             UUID PRIMARY KEY REFERENCES profile.user_profile(profile_id),
  alcohol_min             NUMERIC(5,2),
  alcohol_max             NUMERIC(5,2),
  price_min               INTEGER,
  price_max               INTEGER,
  currency                CHAR(3) NOT NULL DEFAULT 'KRW',
  purchase_intent         VARCHAR CHECK (purchase_intent IN ('NONE','POSSIBLE','LIKELY')),
  preferred_distance_m    INTEGER,
  avoid_congestion        BOOLEAN NOT NULL DEFAULT FALSE,
  updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE profile.preference_item (
  preference_item_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  profile_id           UUID NOT NULL REFERENCES profile.user_profile(profile_id),
  attribute_group      VARCHAR NOT NULL,
  attribute_code       VARCHAR NOT NULL,
  preference_level     SMALLINT CHECK (preference_level BETWEEN 1 AND 5),
  source               VARCHAR NOT NULL CHECK (source IN ('USER','BEHAVIOR','AI')),
  confidence           NUMERIC(4,3),
  valid_from           TIMESTAMPTZ NOT NULL DEFAULT now(),
  valid_until          TIMESTAMPTZ
);

CREATE TABLE profile.buyer_need (
  profile_id                  UUID PRIMARY KEY REFERENCES profile.user_profile(profile_id),
  organization_type            VARCHAR,
  target_price_min             INTEGER,
  target_price_max             INTEGER,
  price_basis                  VARCHAR CHECK (price_basis IN ('RETAIL','WHOLESALE')),
  monthly_units_min             INTEGER,
  monthly_units_max             INTEGER,
  decision_timeline             VARCHAR,
  business_email_verified       BOOLEAN NOT NULL DEFAULT FALSE,
  company_verified              BOOLEAN NOT NULL DEFAULT FALSE,
  updated_at                    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE profile.buyer_need_item (
  buyer_need_item_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  profile_id           UUID NOT NULL REFERENCES profile.user_profile(profile_id),
  need_group           VARCHAR NOT NULL CHECK (need_group IN ('CATEGORY','CHANNEL','REGION','INTEREST')),
  need_code            VARCHAR NOT NULL,
  required             BOOLEAN NOT NULL DEFAULT FALSE,
  priority             SMALLINT,
  created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- =========================================================================
-- ai.ai_model_version (§27.1) — created before recommendation_session/object_embedding
-- =========================================================================
CREATE TABLE ai.ai_model_version (
  model_version_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  model_type         VARCHAR NOT NULL CHECK (model_type IN ('EMBEDDING','LLM','RANKING')),
  model_name         VARCHAR NOT NULL,
  provider           VARCHAR,
  version            VARCHAR NOT NULL,
  config_json        JSONB,
  deployed_at        TIMESTAMPTZ,
  retired_at         TIMESTAMPTZ,
  status             VARCHAR NOT NULL DEFAULT 'TEST' CHECK (status IN ('TEST','ACTIVE','RETIRED'))
);

-- =========================================================================
-- matching.recommendation_session / match_result / match_reason (§18, §19)
-- =========================================================================
CREATE TABLE matching.recommendation_session (
  recommendation_session_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  event_id                    UUID NOT NULL REFERENCES exhibition.event(event_id),
  profile_id                  UUID NOT NULL REFERENCES profile.user_profile(profile_id),
  profile_version_id          UUID, -- profile.profile_version is a 2차 확장 table, kept nullable for MVP
  visit_session_id            UUID REFERENCES profile.visit_session(visit_session_id),
  recommendation_type         VARCHAR NOT NULL
                              CHECK (recommendation_type IN ('BOOTH','PRODUCT','MEETING','MIXED')),
  model_version_id            UUID REFERENCES ai.ai_model_version(model_version_id),
  policy_version_id           UUID,
  context_snapshot            JSONB,
  candidate_count             INTEGER,
  filtered_count              INTEGER,
  status                      VARCHAR NOT NULL DEFAULT 'ACTIVE'
                              CHECK (status IN ('ACTIVE','EXPIRED','INVALIDATED')),
  generated_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at                  TIMESTAMPTZ,
  latency_ms                  INTEGER
);

CREATE TABLE matching.match_result (
  match_result_id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  recommendation_session_id    UUID NOT NULL REFERENCES matching.recommendation_session(recommendation_session_id),
  object_type                  VARCHAR NOT NULL CHECK (object_type IN ('BOOTH','PRODUCT','EXHIBITOR','PROGRAM')),
  object_id                    UUID NOT NULL,
  raw_score                    NUMERIC(8,5),
  normalized_score              NUMERIC(5,2),
  rank                          INTEGER,
  hard_filter_passed            BOOLEAN NOT NULL DEFAULT TRUE,
  preference_score              NUMERIC(8,5),
  goal_score                    NUMERIC(8,5),
  trade_score                   NUMERIC(8,5),
  context_score                 NUMERIC(8,5),
  behavior_score                 NUMERIC(8,5),
  diversity_adjustment           NUMERIC(8,5),
  trust_score                    NUMERIC(8,5),
  recommended_action             VARCHAR CHECK (recommended_action IN ('VISIT_NOW','SAVE','REQUEST_MEETING')),
  created_at                     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_match_session_rank
  ON matching.match_result(recommendation_session_id, rank);
CREATE INDEX idx_match_object
  ON matching.match_result(object_type, object_id);
CREATE INDEX idx_match_normalized_score
  ON matching.match_result(normalized_score DESC);

CREATE TABLE matching.match_reason (
  match_reason_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  match_result_id      UUID NOT NULL REFERENCES matching.match_result(match_result_id),
  reason_code          VARCHAR NOT NULL,
  reason_text          VARCHAR,
  source_attribute     VARCHAR,
  target_attribute     VARCHAR,
  contribution_score   NUMERIC(8,5),
  display_order        SMALLINT,
  generated_by         VARCHAR CHECK (generated_by IN ('TEMPLATE','LLM')),
  ai_run_id            UUID, -- ai.ai_run is a 2차 확장 table, kept as a loose reference for MVP
  approved             BOOLEAN NOT NULL DEFAULT FALSE
);

-- =========================================================================
-- interaction.favorite / check_in / feedback / meeting / interaction_event (§21-25)
-- =========================================================================
CREATE TABLE interaction.favorite (
  favorite_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id            UUID NOT NULL REFERENCES profile.user_account(user_id),
  event_id           UUID NOT NULL REFERENCES exhibition.event(event_id),
  object_type        VARCHAR NOT NULL CHECK (object_type IN ('BOOTH','PRODUCT','PROGRAM')),
  object_id          UUID NOT NULL,
  source             VARCHAR CHECK (source IN ('SEARCH','RECOMMENDATION')),
  match_result_id    UUID REFERENCES matching.match_result(match_result_id),
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at         TIMESTAMPTZ
);

CREATE UNIQUE INDEX idx_favorite_unique
  ON interaction.favorite(user_id, event_id, object_type, object_id) WHERE deleted_at IS NULL;

CREATE TABLE interaction.check_in (
  check_in_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  event_id             UUID NOT NULL REFERENCES exhibition.event(event_id),
  visit_session_id     UUID REFERENCES profile.visit_session(visit_session_id),
  user_id              UUID REFERENCES profile.user_account(user_id),
  guest_session_id     UUID REFERENCES profile.guest_session(guest_session_id),
  booth_id             UUID NOT NULL REFERENCES exhibition.booth(booth_id),
  match_result_id      UUID REFERENCES matching.match_result(match_result_id),
  check_in_method      VARCHAR NOT NULL CHECK (check_in_method IN ('QR','MANUAL','STAFF')),
  activities           JSONB,
  checked_in_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_check_in_session_booth_time
  ON interaction.check_in(visit_session_id, booth_id, checked_in_at);

CREATE TABLE interaction.feedback (
  feedback_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id              UUID NOT NULL REFERENCES profile.user_account(user_id),
  visit_session_id     UUID REFERENCES profile.visit_session(visit_session_id),
  object_type          VARCHAR NOT NULL,
  object_id            UUID NOT NULL,
  match_result_id      UUID REFERENCES matching.match_result(match_result_id),
  rating               VARCHAR NOT NULL CHECK (rating IN ('VERY_RELEVANT','NEUTRAL','IRRELEVANT')),
  positive_reasons     JSONB,
  negative_reasons     JSONB,
  comment              TEXT,
  created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE interaction.meeting (
  meeting_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  event_id                 UUID NOT NULL REFERENCES exhibition.event(event_id),
  buyer_profile_id         UUID NOT NULL REFERENCES profile.user_profile(profile_id),
  exhibitor_id             UUID NOT NULL REFERENCES exhibition.exhibitor(exhibitor_id),
  staff_id                 UUID, -- exhibition.exhibitor_staff is a 2차 확장 table, kept as a loose reference for MVP
  booth_id                 UUID REFERENCES exhibition.booth(booth_id),
  topic_code               VARCHAR,
  message                  TEXT,
  status                   VARCHAR NOT NULL DEFAULT 'REQUESTED'
                           CHECK (status IN ('REQUESTED','CONFIRMED','DECLINED','COMPLETED','CANCELLED')),
  confirmed_start          TIMESTAMPTZ,
  confirmed_end            TIMESTAMPTZ,
  contact_share_consent    BOOLEAN NOT NULL DEFAULT FALSE,
  match_result_id          UUID REFERENCES matching.match_result(match_result_id),
  created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at               TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_meeting_exhibitor_time
  ON interaction.meeting(exhibitor_id, confirmed_start);
CREATE INDEX idx_meeting_buyer_time
  ON interaction.meeting(buyer_profile_id, confirmed_start);

-- interaction_event is a high-volume append-only log; partitioned by event_date (§25.1).
CREATE TABLE interaction.interaction_event (
  event_log_id                 UUID NOT NULL DEFAULT gen_random_uuid(),
  event_id                      UUID NOT NULL REFERENCES exhibition.event(event_id),
  event_type                    VARCHAR NOT NULL,
  user_id                       UUID,
  guest_session_id              UUID,
  visit_session_id              UUID,
  object_type                   VARCHAR,
  object_id                     UUID,
  recommendation_session_id     UUID,
  match_result_id               UUID,
  rank_at_event                 INTEGER,
  screen_code                   VARCHAR,
  context_json                  JSONB,
  occurred_at                   TIMESTAMPTZ NOT NULL,
  received_at                   TIMESTAMPTZ NOT NULL DEFAULT now(),
  event_date                    DATE NOT NULL,
  PRIMARY KEY (event_log_id, event_date)
) PARTITION BY RANGE (event_date);

CREATE INDEX idx_interaction_event_date_type
  ON interaction.interaction_event(event_date, event_type);
CREATE INDEX idx_interaction_event_user_time
  ON interaction.interaction_event(user_id, occurred_at DESC);
CREATE INDEX idx_interaction_event_object
  ON interaction.interaction_event(object_type, object_id, occurred_at);
CREATE INDEX idx_interaction_event_rec_session
  ON interaction.interaction_event(recommendation_session_id);
CREATE INDEX idx_interaction_event_occurred_brin
  ON interaction.interaction_event USING BRIN (occurred_at);

-- Create one partition per event day is expected in the application/ops pipeline, e.g.:
--   CREATE TABLE interaction.interaction_event_2026_10_09
--     PARTITION OF interaction.interaction_event
--     FOR VALUES FROM ('2026-10-09') TO ('2026-10-10');

-- =========================================================================
-- ai.object_embedding (§28.1)
-- =========================================================================
CREATE TABLE ai.object_embedding (
  embedding_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  object_type         VARCHAR NOT NULL CHECK (object_type IN ('EXHIBITOR','PRODUCT')),
  object_id           UUID NOT NULL,
  content_type        VARCHAR NOT NULL CHECK (content_type IN ('SUMMARY','TRADE','PRODUCT')),
  content_text        TEXT NOT NULL,
  content_hash        CHAR(64) NOT NULL,
  embedding           VECTOR(1536),
  model_version_id    UUID NOT NULL REFERENCES ai.ai_model_version(model_version_id),
  language            VARCHAR,
  active              BOOLEAN NOT NULL DEFAULT TRUE,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_object_embedding_hnsw
  ON ai.object_embedding USING hnsw (embedding vector_cosine_ops);
CREATE INDEX idx_object_embedding_object
  ON ai.object_embedding(object_type, object_id, content_type) WHERE active;

-- =========================================================================
-- audit.audit_log (§31.1) — append-only; no updated_at/deleted_at by design.
-- =========================================================================
CREATE TABLE audit.audit_log (
  audit_log_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  actor_user_id    UUID,
  actor_role       VARCHAR,
  action_type      VARCHAR NOT NULL CHECK (action_type IN ('VIEW','CREATE','UPDATE','DELETE','EXPORT')),
  resource_type    VARCHAR NOT NULL,
  resource_id      UUID,
  before_hash      CHAR(64),
  after_hash       CHAR(64),
  reason_code      VARCHAR,
  request_id       UUID,
  ip_hash          CHAR(64),
  occurred_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_audit_log_actor_time ON audit.audit_log(actor_user_id, occurred_at DESC);
CREATE INDEX idx_audit_log_resource ON audit.audit_log(resource_type, resource_id, occurred_at DESC);

-- Application code must never UPDATE or DELETE audit.audit_log rows; enforce with a
-- REVOKE UPDATE, DELETE ON audit.audit_log FROM <app_role>; grant in the deploy step.
